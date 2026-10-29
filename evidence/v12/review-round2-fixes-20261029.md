# 第二轮独立复核：发现、修复与实证

日期：2026-10-29｜分支：opus-v12-handoff｜提交：a3a4962（修复）、132a98f（取消归属）
复核方式：独立只读子 Agent（独立上下文，未参与编码），不读取 `.studio`，不发起真实模型调用。
前三次尝试被上游 502/503 打断，第四次换模型实例完成，报告结论为 **PASS WITH ISSUES：无 P1，三条 P2，其余 P3**。

## 一、复核发现与处理

### P2-1 非对象 JSON 使 run 永久卡在 running（已修）

`work_v12` 里 `json.loads` 接受 `[...]` 或标量，随后 `decision.get()` 抛 `AttributeError`，
该异常不在 `except (RuntimeError,ValueError,OSError,TimeoutError)` 内，只有 `finally` 执行：
线程死亡、`status` 仍是 `running`、`error` 为 `None`，并且**后续任何任务都会被「已有任务执行中」挡住**。

复现（修复前）：喂 `[{"x":1}]` → `status running, error None, worker alive False`，下一个请求被拒。
修复：`decision` 必须为 dict；`reason` 强制 `str().切片`；补 `except Exception` 兜底标记 `failed`。
复现（修复后）：`status failed, error 项目经理返回的结构无法解析，请重试`，下一个请求正常入队。

### P2-2 委派任务发送后步骤消息永不出现（已修，含一处连带渲染缺陷）

两个独立问题叠在一起：

1. 前端只在发送瞬间读一次对话，那时经理还没答复，步骤消息尚未产生；`poll` 只取 run 不取消息，
   而 `renderMessages` 一看到 `run.steps.length` 就删掉聚合气泡，页面于是只剩用户那一条。
2. 修复过程中又暴露一个渲染游标缺陷：删除聚合节点后，`pointer` 仍指向这个**已脱离文档**的节点，
   下一次 `insertBefore(node, pointer)` 抛 `NotFoundError`，整轮渲染中断——所以第 2 步永远插不进去，
   而手动再调一次 `renderMessages` 却能补上（那时聚合节点已不存在）。

修复：`poll` 在存在未渲染步骤时补读对话；`settled` 以 `runId:version` 为键，避免空转；
删除聚合节点前先把 `pointer` 移到它的下一个兄弟；`stepsPending()` 同时看状态与已读消息。
实测：两步任务结束后 DOM 为「你 / Codex·第1步 / Codex·第2步」，4 秒内 0 个请求（轮询已收敛）。

### P2-3 `route=answer` 但 `answer` 为空串 → 空白成功气泡（已修）

`ROUTE_SCHEMA` 未设 `minLength`，空串是合法输出；`patch` 存 `completed`，`page()` 返回空文本，
前端因 run 已终态且无 error 而不显示任何状态。修复：空/纯空白回答判为失败（与 `verify()` 的判据一致）。
另对前端文本加 `String(...)` 兜底，避免非字符串 answer 让 `markdown()` 抛错中断整轮渲染。

### P3 文件路由只认 workspace id（已修）

`/api/files`、`/api/file`、`/api/upload` 原先只按 workspace id 解析，可读写别的项目的工作空间。
新增 `Studio.workspace_for(pid, workspace)`，要求经 `projectId` 解析且与 workspace 一致，前端三处调用同步改。

### P3 已修（提交 5a3373d）

- `loadSeq` 原先只保护 `state.before`，快速连点「加载更早消息」可能让游标回退。现在同一时刻只允许一个分页请求在途；
  迟到响应仍合并更早的消息，但不再改游标与滚动位置。浏览器实测连点三次只发出 1 个请求。
- 步骤记录已落 run 但消息写入失败时，原先要等下一次读取才补齐且顺序可能不对。现在 `page()` 读取时自愈：
  缺失的步骤消息补在队尾，顺序与步号不符则按步号在原槽位重排，重复读取幂等；
  `step()` 也不再让消息写失败连带把 run 判为 failed。

### P3 未修（已知、风险低）

- `loadSeq` 只保护 `state.before`，快速双击「加载更早消息」可能让游标回退到旧页；无数据错乱。
- `step()` 中步骤记录已写入、消息写入失败时，下次 `page()` 会补齐；仅暂时不一致。
- `loadSeq` 之外的后台任务查询已带归属；`/api/bootstrap` 按设计返回全部项目供侧栏渲染。

## 二、复核确认「成立」的部分（未改动）

- **逐步持久化确实可靠**：`adapter.call` 返回 → `calls.append` → `step()` → `patch()` 顺序固定；
  `patch()` 从不写 `answer`，后续步骤失败不会覆盖前序记录。复核方在取消窗口注入 `patch(cancelled)` 实测：
  `status=cancelled, steps=[(1,'completed')], answer=结果一`，页面可见步骤消息。
  唯一无法覆盖的是进程被 kill 在「模型返回」与「落盘」之间，属固有限制。
- **测试无空转**：19→45 项，关键断言（调用次数、步骤数、跨项目拒绝）均能区分正确与错误实现。
  原先用 `inspect.getsource` 断言源码字符串的取消测试已改为真实驱动 `Handler.do_POST`。
- **`/api/conversation`、`/api/progress`、`/api/run`、`/api/cancel` 归属校验**逐一核对通过。

## 三、测试与实证

- `python3 -m unittest discover -s tests`：**45/45 通过**（原 21 项未改；新增 24 项）。
- `node --check app.js` 通过。
- 隔离实例（假适配器、2s 延迟）验证委派渲染：发送后 59ms 仅 2 条消息，结束后自动补齐为 4 条，
  DOM 显示两条步骤，轮询在 4 秒窗口内 0 请求。
- 8891 服务以最新代码重启：1 个项目、9 条对话、设置 v2、`gpt-6.1-sol` 已验证、Codex 已连接。

## 四、仍未验证

- 未用真实模型复跑「非对象 JSON」「空回答」两条异常路径（`--output-schema` 通常能挡住，但未实测）。
- Claude Code / WorkBuddy 宿主仍未接入，多员工跨宿主协作未验证。
- 外部项目目录授权、diff/审批/回滚、独立审核（G4/G5）未开始。
- 本轮未部署，未推送远端。

## 五、回滚

本轮为两次提交：`132a98f`（取消归属）、`a3a4962`（三项 P2 + 文件路由）。
`git revert a3a4962 132a98f` 可回到 `243ce0f`。数据库另有 `backups/pre-restart-20261028T190619.sqlite`。
