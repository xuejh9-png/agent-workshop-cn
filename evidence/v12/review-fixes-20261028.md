# v1.2 独审三项待修：修复与实证记录

日期：2026-10-28｜分支：opus-v12-handoff｜状态：三项已修 + 新增确定性测试；真实 E2E 仅覆盖主控短问答与设置闭环，员工多步仍未真实跑

## 1. 修了什么

### P1 app.js `loadConversation` 乱序响应（45 行）
- 请求时捕获 `cid/pid/before`，返回后校验 `page.conversation.id===cid` 且 `cid===state.conversation`、`pid===state.workspace`，不匹配直接丢弃，不写全局 `state.messages`。
- 增加请求代次 `loadSeq`，只有最新一次请求能更新 `state.before`，旧的分页游标不会覆盖新的。
- `sendOrStop`：请求发出后用户切走时不再把当前对话强制切回该 run 的 conversation，只提示「任务已派发，返回该项目可查看进度」。
- `poll`：后台 run 查询补 `projectId`（旧 run 用 `workspace` 兜底）。
- `loadMoreConversations`：项目已切换则不再重渲染侧栏。
- **`renderMessages` 增加 DOM 清理**：删除不在 `state.messages` 里的 `.turn` 节点。没有这一步，状态层虽正确，屏幕上仍会残留上一个对话的旧节点（浏览器实测复现过，见 §3.1）。

### P2 server.py `/api/run` 归属校验
- 新增 `Studio.run_for(ident,pid)`：校验项目存在、run 存在、`run.projectId or run.workspace == pid`，否则 400。
- `/api/run` 改为必须带 `projectId`；前端 poll 同步改。
- 旧记录（无 `projectId`，只有 `workspace`）仍可读，回归测试覆盖。

### P2 server.py `work_v12` 逐步持久化
- run 新增 `steps: []`；新增 `Studio.step()`：按步号 upsert、按步号排序、重算 `answer`（多步为「任务N：」拼接）、`version+1`、同步消息表。
- 每个员工步骤独立落盘：成功 `completed` + 文本；`InterruptedError` 落 `cancelled`；其它异常落 `failed` + 错误摘要，然后才向上抛出（run 终态仍是 cancelled/failed，不会假装整单成功）。
- 后续步骤的「前序交接结果」改为读已完成的步骤记录，不再依赖内存 `outputs`。
- `v12.Projects.step_message()`：每步生成独立 assistant 消息（id `runid:step:N`，sequence 稳定递增）。`page()` 对带 `step` 的消息使用步骤自身文本，聚合 run 消息在存在步骤时返回空文本；前端隐藏该空节点。
- 失败也能在页面上看到已完成步骤的内容，不再「后面一步失败，前面全丢」。

### 附带修复（本轮发现）
- `start_v12` 自身补 `schemaVersion!=2` 校验（原先只有 HTTP 层拦，直接调用可绕过）。测试 `test_request_fields_cannot_override_settings` 先红后绿。
- `runtime.codex_binary()`：`STUDIO_CODEX_BIN` → `PATH` → `/Applications/ChatGPT.app/.../codex-cli/bin/codex`。GUI 环境启动的服务往往没有 CLI 的 PATH，旧实现会误报「未安装 Codex CLI」（本轮实测复现）。
- `renderMessages` 标签回归：项目经理回复曾被误标为「员工」，已修正为无 step 时显示「项目经理」。

## 2. 新增测试（tests/test_v12.py，19 项，全部确定性、无真实模型）

| 测试 | 覆盖 |
|---|---|
| test_manager_direct_answer_uses_one_call | 短问答只产生 1 次调用，无步骤消息 |
| test_delegate_without_allowed_employees_blocks_without_call | 无授权员工 → blocked，不调用员工 |
| test_manager_cannot_plan_unallowed_employee | 经理越权指派 → failed，员工零调用 |
| test_plan_over_four_steps_rejected_before_any_employee | 超过 4 步在产生副作用前拒绝 |
| test_later_failure_keeps_earlier_step_output | 第二步失败，第一步文本仍在 run/消息中 |
| test_cancel_keeps_completed_step_and_marks_stopped_step | 取消保留已完成步，停止步标 cancelled |
| test_step_messages_have_stable_sequence_and_no_duplicates | 步消息序号稳定、重复读取不增量 |
| test_run_for_rejects_other_project_and_unknown | 跨项目 / 未知 run / 未知项目均拒绝；旧记录可读 |
| test_conversation_cannot_be_reused_across_projects | 跨项目复用 conversation 被拒 |
| test_progress_returns_only_changed_runs | 增量只回变化 run；非法游标拒绝 |
| test_conversation_paging_is_isolated | 对话隔离 + before 分页 |
| test_settings_save_bumps_revision_and_is_durable | 保存后 revision 递增并落盘 |
| test_settings_revision_conflict_leaves_store_untouched | 版本冲突不改动已存值 |
| test_settings_reject_unverified_model_and_unsupported_host | 未验证型号、未接通宿主、审核开关均拒绝 |
| test_unsupported_manager_host_rejected_on_start | 起点处拒绝 claude/workbuddy |
| test_request_fields_cannot_override_settings | 请求体夹带 model / 旧 schemaVersion 拒绝 |
| test_request_nonce_is_idempotent | 同请求重放返回同一 run；改内容拒绝 |
| test_migration_is_idempotent | 迁移重复执行不新增记录 |
| test_legacy_run_migrates_into_conversation | 旧 run 迁移为对话，原记录 JSON 不变 |

## 3. 真实环境证据（本机 8891，2026-10-28 19:0x–19:4x）

### 3.1 浏览器：乱序响应
把 A 对话的首个请求人为延迟 600ms，连续 `openConversation(A)`、`openConversation(B)`：
- 状态层：`state.messages` 仅含 B 的 2 条；`state.conversation===B`。
- 修 DOM 清理前：状态正确，但 `#thread` 残留 4 个节点（A、B 各两条）。
- 修后：`#thread` 仅剩 B 的节点，无跨对话混排。

### 3.2 `/api/run` 归属
`run=e4ffc981…` 属「测试工作空间」：
- 同项目：200
- 另一项目 projectId：400 `任务不属于当前项目`
- 缺 projectId：400 `项目不存在`

### 3.3 设置真实闭环
1. 未验证时保存：400 `此宿主/当前账号/连接配置下的型号未完成真实测试，请先验证`（旧 M2 验证未被继承，符合设计）。
2. `POST /api/verify` codex / gpt-6.1-sol / high：200，14.8s，返回 `accountId=fdacfa06…`、`configId=codex-studio-https-v1`、`input 15124 / output 30`。
3. 再次保存：200，`revision 0→1`；立即 GET 读回与返回值逐字节一致；经理/员工均为 `gpt-6.1-sol / high`。
4. 用旧 revision 重放：400 `配置已被其他页面修改…`。
5. 刷新页面后设置弹窗显示 `gpt-6.1-sol · 已验证`，`verified()` 为 true。

### 3.4 真实主控问答（UI 提交）
- 输入「你是谁？请用一句话介绍。」→ 856ms 内派发，约 20s 完成。
- `route=answer`，`calls=1`，`requestedModel=gpt-6.1-sol`，`usage input 15339 / cached 0 / output 77 / reasoning 25`。
- 回答自报身份为「Agent Studio 的项目经理」，符合 AW-D-007，未自称 Codex/GPT。
- 界面：用户/项目经理两条消息，标签与头像正确，注明「完成后的分段呈现 · 非实时模型 Token」。

### 3.5 截图（1440×900 / 1024×768 / 768×1024 / 375×812，浅色与深色各一组）
已逐档目视核对，均无横向溢出、无遮挡；<860px 侧栏按设计自动收起。截图本身由本机 Browser pane 渲染，未另存文件（下轮若需归档可补 `evidence/v12/screenshots/`）。

## 4. 仍未验证 / 未做

- **员工多步真实调用**（Codex 经理 + Codex 员工，含部分失败、取消）只有替身测试，没有真实模型 E2E。
- 设置矩阵只做了「保存→读回→刷新」；**进程重启后的读回**与「下一次真实请求使用新值」尚未单独取证（本轮验证请求确实用了保存值，但未做改值→重启→再请求的对照）。
- 流式呈现仍是完成后分块，未做真实 Token 流；`renderMessages` 仍整体重建，未做 900ms 整块重绘优化（G3 原任务）。
- G4/G5 未开始：Claude CLI 适配、WorkBuddy 可控性、外部目录授权、diff/审批/回滚、独立审核、AT-19～30。
- 独审（独立子 Agent）尚未对本轮改动重新发起，不能据此宣称权限审查通过。
- 未部署；未推送到 main；未提交前 `.studio` 私有数据不入库。

## 5. 回滚
本轮全部为未提交的工作区改动。`git diff` 可完整查看；`git checkout -- app.js server.py v12.py runtime.py tests/test_v12.py` 即回到 `568c7bf` 交接点。SQLite 另有 `backups/pre-restart-20261028T190619.sqlite`（重启前）与 `pre-v12-20261028T174800.sqlite`（迁移前）。
