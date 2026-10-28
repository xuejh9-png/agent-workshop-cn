# 当前任务｜Agent Studio v1.2：项目经理、员工授权、项目对话与真实协作

> 2026-10-28｜状态：REQUIREMENTS READY / IMPLEMENTATION NOT VERIFIED
> 工程仓库：`xuejh9-png/agent-workshop-cn`（private）。本文件是工程入口，**不是另一份产品决策**。
> 正式权威：`xuejh9-png/my-ai-context`，仅用原 Issue #10 协作。

## 开工先读（按顺序）

1. [原 Issue #10 / 已置顶最新要求](https://github.com/xuejh9-png/my-ai-context/issues/10)
2. [AGENTS.md](https://github.com/xuejh9-png/my-ai-context/blob/main/AGENTS.md)、[SYNC_PROTOCOL.md](https://github.com/xuejh9-png/my-ai-context/blob/main/SYNC_PROTOCOL.md)
3. [AW-D-007 决策](https://github.com/xuejh9-png/my-ai-context/blob/main/projects/agent-workshop/DECISIONS.md)（与旧决策冲突的交互要求以 AW-D-007 为准）
4. [产品需求 v1.2](https://github.com/xuejh9-png/my-ai-context/blob/main/projects/agent-workshop/PRODUCT_REQUIREMENTS_AND_ACCEPTANCE_V1_2.md)
5. [基于真实代码评审的分阶段执行方案](https://github.com/xuejh9-png/my-ai-context/blob/main/projects/agent-workshop/IMPLEMENTATION_PLAN_V1_2_CODE_REVIEW.md)
6. [当前状态](https://github.com/xuejh9-png/my-ai-context/blob/main/projects/agent-workshop/CURRENT_STATUS.md) 和最新本项目 handoff。原 `evidence/m2/VERIFICATION.md` / `SECURITY_REVIEW.md` 为历史 M2 基线，仅适用于被测旧功能。

## 最新授权产品方向（不可仍按旧 M2 规格施工）

- 保留负责人已认可的白灰+克制紫色方案 B，不全盘重画。唯一主聊天角色命名「项目经理」，身份介绍使用当前工程名 Agent Studio（将来可配置替换），在任务详情披露真实执行环境/型号证据。
- 对话输入框**仅选「项目经理宿主（Codex/Claude Code/WorkBuddy，必须已验证可调用）」+「本次允许员工（多选）」**；具体模型、推理强度在设置提前配置，输入框不再提供第二个可选具体型号的下拉。
- Codex / Claude Code / WorkBuddy **分别**进行可控调用和型号验证；WorkBuddy 桌面不等于 CodeBuddy CLI，更不等于第三方 DeepSeek/Claude API。未接通请禁用并标 UNSUPPORTED，不得冒充。
- 设置保存必须真正写入后端并经读取、刷新、重启和下一次真实调用验证。当前源码已有 `POST /api/settings` 和 SQLite 写入，旧 M2 记载 GUI 保存测试成功，**先实机定位当前故障，不得武断称是假按钮或无理由重写**。
- 项目经理可直接答复或按任务委派已勾选员工；勾选不等于强制调用。不再通过可见的单次 1/2 调用上限阻塞多员工任务，仍保留后端风控、防无限循环、文件权限、费用来源和危险操作审批。
- 左侧是直观的「项目 -> 项目知识与对话」树，支持多项目与独立对话。项目知识不在全局底部，切换不靠隐藏工作空间弹窗。旧 SQLite/workspace/run/file 历史非破坏性保留。
- 展示真实运行状态与尽可能真实增量响应；没有原生内容流时可进行平滑分块呈现但不得伪装实时模型思考。取消、断连、刷新不得重复消息、篡改任务状态。
- 真实可用的工作台必须最终支持**获得授权的实际项目目录和已有代码修改**（先只读/预览后写入、diff 和回滚），不能长期停留在应用内部只新建 md/txt 文件的演示范围；不触碰未经授权的 YiPex/投资 OS 生产数据或任何业务生产发布。

## 施工顺序与逐关验收

- **G0｜基线与保存按钮诊断**：本机 `git status / diff`、安全确认并 `fetch/pull --ff-only`、记录真实 HEAD 和 Context SHA；检查 `.studio` 私有数据保护。复现实机保存的请求/错误/SQLite 值；运行原 21 项测试并记录失败集合。
- **G1｜经理/员工与设置闭环**：配置数据模型（host+account+model 独立验证）、真实保存/读回，Codex 经理+Codex 员工许可和路由；每次 run 固化用户授权；调整对话输入区，不假显示 Claude/WorkBuddy 已接入。保证一次短问答不产生额外执行器调用。
- **G2｜真正的项目+对话存储和侧栏**：从原 workspace+parent-run 链兼容迁移，独立 Conversation/Message/Run 关系。保留历史/附件，项目知识归项目；测试多项目隔离、长历史分页。
- **G3｜可观察运行与流式呈现**：真实事件、状态、工具进度；尽可能实流式，必要时明确区分显示动效与原生内容流；避免当前每 900ms 整块重绘聊天 DOM。
- **G4｜真实第二员工、授权外部项目、独立审核**：优先接 Claude Code；WorkBuddy 单独验证第三方可控性/型号切换。经理完成真实任务交接；外部项目只在逐目录明确授权下访问；实际代码修改必须有安全审批、diff、测试、回滚。先顺序协作，再评估并行与隔离。
- **G5｜最终回归和负责人验收**：原有 21 项测试不可退化，新增 v1.2 的 AT-19～30；真实模型、切型号、停止/断连、配置保存、权限越界、跨项目、独立审核、深浅色 1440/1024/768/375 截图与真实任务产物逐项核对。

每关都先给**可观察验收结果**；未完成仍标 NOT VERIFIED / BLOCKED。不要直接跳到美化按钮或增加工作流框架。真实结果由负责人最终验收。

## 当前基线和交接保护

- 远端代码 `main` 在本次任务入口改动前检查的 HEAD：`c4bd71058a4ab8fe6014db78351bd4ffa5644fc8`；M2 被测实现 SHA：`5816b185ecf013377f7cabcfd851a69b06f59606`。这些是**远端已提交快照**，不代表接手者本机没有后续未提交改动。
- 保留已有 `index.html/app.js/server.py/runtime.py/file_tools.py/tests/`，可在核实差异后局部改动、修 bug、重构。不要 `reset --hard`、强推、删本机 `.studio`、覆盖他人未提交代码或将私有记录推送 GitHub。
- 独立安全审查覆盖新增高风险权限/路径/并发/执行能力；原 M2 的安全独审不能直接等同于 G4 已过。
- 交付按根协议：源码 SHA、实际命令/真实模型事件、测试及失败集合、产物/截图、限制、回滚，在 Context Hub `projects/agent-workshop/handoffs/` 追加精简交接，并更新**同一** Issue #10 的 READY_FOR_REVIEW。未部署标 NOT_DEPLOYED。

## 历史说明

此前本文件的「M2 真实最小闭环」已在 `evidence/m2/VERIFICATION.md` 和 Git 历史保留。本次只更新后续任务入口，不修改 M2 代码/测试/证据，也不宣称 G0–G5 已执行完成。
