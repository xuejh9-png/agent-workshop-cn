# 给 Opus 5.5：v1.2 暂停施工接手说明

**负责人要求暂停 Codex，由 Opus 继续。本分支是 WIP，不是验收通过或产品发布。**

## 先定位正确代码

- 当前本机目录：`/Users/c0437/Desktop/agent-studio-v01`，当前分支 **opus-v12-handoff**。没有另建项目。
- WIP 源码提交：`c3c3905f1da076de052890b7d46cc7020a6c0416`。
- 本轮基线／保留的 main：`ce525e9be2b82a9307862a8ecdb0d8662e6cb70b`（只更新过 CURRENT_TASK；此前已跑通 M2）。
- Context Hub pinned：`94ad6dc2d438da0dafde1e1c38c01bedbc2cd053`。
- 权威需求：Context Hub AW-D-007、PRODUCT_REQUIREMENTS_AND_ACCEPTANCE_V1_2.md、IMPLEMENTATION_PLAN_V1_2_CODE_REVIEW.md；原 Issue #10。继续读本工程 CURRENT_TASK.md。不要按旧M2输入区型号下拉继续施工。
- 接手先 `git status --short --branch`、核对未提交差异和远端分支。别 reset/清理或覆盖新改动；本轮只提交自己的改动。不要把本分支当已合并 main。

## 当前实际进展

**G0**：基线21测试全部通过。旧设置按钮实机把经理强度 high→medium，SQLite确实写入；未复现用户遇到的具体失败，不能称它是假按钮。测试后已恢复用户原配置：经理/执行均 `gpt-6.1-sol` / high，旧 maxCalls=2 原值保留。完整的关闭/刷新/重启/下一次真实请求矩阵尚未完成。

**G1/G2/G3 代码已起稿，功能未验收**：

- 新增 `v12.py`：版本化设置、按宿主/账号/连接配置/型号分隔验证；项目、conversation、message、run_link 的追加式迁移；分页、项目和对话重命名。
- `server.py`：新 HTTP 请求 schemaVersion=2，经理型号从后端设置解析；allowedEmployees 固化快照；整份员工计划先验证再执行，最多4员工步骤替代公开的两次门槛；旧方法只作原21测试/历史兼容，新HTTP拒绝旧engine/model请求；按version增量查询。
- `runtime.py`：account/read获取账号元数据后只生成本机随机命名空间的哈希绑定，不保存/返回邮箱或凭据；经理schema增加多步tasks；增加真实工具开始事件。未新增Claude/WorkBuddy适配。
- `app.js/index.html`：项目树与项目资料入口、独立对话分页、项目经理宿主＋本次员工复选框；型号只在设置；保存后GET读回、失败提示在dialog内部并保留表单；message ID更新DOM，CLI最终回答分块显示并明确非实时Token。新界面尚未做浏览器验收。
- 原路径安全、只读/仅新建文本、进程组取消等边界保留；未开放外部目录、Shell、覆盖、删除、发布。

## 立即先修：独立审查静态确认，尚未修复

审查者 Ohm 是独立只读子Agent；用户暂停后也已停止。其隔离快照非最终完整验收。

1. **P1，app.js `loadConversation`（约45行）**：A项目/对话请求在切换到B后迟到，直接写全局messages，未校验请求时的projectId/conversationId。需要请求代次/捕获ID＋返回时匹配，分页、poll、文件预览等异步入口也检查。加乱序响应测试，禁止跨项目混消息。
2. **P2，server.py `/api/run`（约288行）**：仍仅按run ID返回，没有项目/对话归属校验；新版progress的校验没覆盖此入口。修API和前端后台任务查询参数，并回归旧记录的可读性。
3. **P2，server.py `work_v12`（约237行）**：每步员工输出只在局部outputs，全部成功才写answer；后续步失败/取消会丢前序回复。每步应持久化独立输出/消息及稳定顺序，取消后保留完成部分，不将其当全部任务成功。

这些问题足以说明 **独审尚未通过**。审查者未发起真实模型、未读取真实.studio，不能把旧21测试通过当G1-G3或权限验收通过。

## 已验证与尚未验证

- 原两个测试文件未改：基线21/21，通过；当前WIP交接再跑21/21，通过（evidence/v12/handoff-tests.txt）。这些主要覆盖旧M2，未覆盖新v1.2。
- `node --check app.js`、Python编译 server/runtime/v12、`git diff --check` 通过。
- 独审隔离复跑旧21项通过，JS与Python语法通过；新权限/迁移/异常/增量查询正式复核未完成。
- 实测Codex account/read可返回account元数据；仅输出字段名/账号类型，未输出身份或令牌。**新版按账号验证、保存、路由、模型回答、多步员工、流式界面没有真实E2E证据。**
- 原8条run在迁移后逐条原始JSON SHA保持不变。新增8 conversation、16 message、8 run_link、1 project、migration元数据；workspace/run/files原样保留。迁移的幂等、循环/孤立parent、长历史等尚未正式新增测试。
- 当前SQLite仍只有旧settings两条；新版 settings v2/verified_v2 尚未完整验证落盘流程；旧验证不能不加实测就提升为当前账号已验证。
- 没有本轮新截图、没有新功能验收、不部署；G4/G5未开始。

## 私有数据与进程现状（非常重要）

- `.studio/` 没有提交GitHub，禁止上传里面的真实对话、数据库、账号元数据、salt或工作文件。
- SQLite备份：`.studio/backups/pre-v12-20261028T174800.sqlite`（本机私有），迁移前；原始记录哈希证据仅含ID/哈希，位于 evidence/v12/baseline-data-hashes.json。
- 临时8892预览由本Agent启动，PID61716，暂停时已发送SIGTERM；不要把这个旧内存快照作为最终服务。
- **8891原M2进程未重启，暂停前观察PID52903。磁盘源码已改成WIP，旧进程＋新JS可能不匹配。接手先确认真实监听进程与活跃任务，统一重启后测试；不能据当前网页判断新版正常。** 不要误杀用户后来启动的进程，以实际PID/命令核实。
- 启动命令 `python3 server.py` 默认127.0.0.1:8891；或用STUDIO_PORT=8892隔离预览。先检查是否有正在跑的任务，禁止擅自中断别人的工作。

## 建议接下来的具体顺序

1. 修上述3项；新增v1.2确定性测试（原21项不删除/跳过/放宽），重新独立权限审查。
2. 在合成数据隔离目录验证：空员工、伪造员工、经理越权计划、账号/host/config验证隔离、配置原子失败/版本冲突、请求去重、迁移幂等/孤立/环、跨项目与超过12/200条历史。
3. 用本机受控Codex测试新版经理身份、设置保存/读回/刷新/重启/真实参数，及Codex经理+Codex员工。新namespace需要真实连接验证，不能复用旧model-only缓存冒充。
4. 浏览器验证切换3项目、多对话、资料、乱序/断连/取消、分块与滚动，1440/1024/768/375浅深色，保存真实截图；检查所有异步响应是否回写正确项目。
5. G0-G3通过后再G4：真实Claude CLI适配、WorkBuddy独立可控性验证、逐目录授权的非生产测试Git项目/diff/审批/回滚、新会话独审；不直接放开全局Shell或业务系统。
6. 按原Issue #10提交阶段证据与新handoff；未完成明确NOT VERIFIED。

## 回滚

代码：先保留后续未提交劳动，再从稳定main检查差异；本WIP未合并main，不需要强推或抹历史。若数据要回退，先停相关服务并另备份当前.studio，再由执行Agent审查后用上述私有SQLite备份恢复；不要在线覆盖SQLite或删除原文件。当前迁移只新增records，旧数据仍在，可优先保留供后续继续。
