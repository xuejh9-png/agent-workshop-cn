# v1.2 真实多步员工 E2E（Codex 经理 + Codex 员工）

日期：2026-10-29｜分支：opus-v12-handoff｜实例：隔离数据目录 `E2E_DATA=/tmp/studio_e2e/data`，端口 8892
真实模型：`gpt-6.1-sol` / effort `high`（经理与员工各自独立验证后保存，rev 1）
未使用任何替身；本记录不包含账号身份、令牌或会话内容以外的私有数据。

## 前置

1. 新数据目录启动 `make_server(8892, /tmp/studio_e2e/data)`，`connection` 正常。
   注意 `accountId` 与前一轮不同（`974c8d68…` vs `fdacfa06…`）：命名空间盐按数据目录生成，符合「不同安装不共享验证」的设计，旧的 model-only 验证不会被继承。
2. `POST /api/verify` codex / gpt-6.1-sol / high：200，17.9s，`input 15112 / output 30`。
3. 保存设置：200，revision 0→1，经理与员工均为 `gpt-6.1-sol / high`。

## 任务（一步到位、两步有依赖）

> 请分两步完成：第一步，在当前项目创建 notes.md，写两句话说明本项目的目标；第二步，读取刚创建的 notes.md，并告诉我它是否真的包含「可验收」三个字。

请求：`allowedEmployees=["codex"]`、`allowWrite=true`、`managerHost=codex`，未带任何 model/effort 字段（新版 schema 拒绝这类覆盖）。

## 结果

| 项 | 值 |
|---|---|
| run | `84e1690f0d6d41879af5a435fd994ece` |
| status / route / phase | `completed` / `delegate` / `employee` |
| error | null |
| 真实调用 | 3 次（经理 1 + 员工 2） |
| 经理 usage | input 15330 / output 613 |
| 步骤 1 usage | input 77555 / output 310 |
| 步骤 2 usage | input 46339 / output 194 |
| run version | 32（增量轮询可用） |

### 步骤记录（`run.steps`，逐步持久化）

- step 1 `completed`，employee `codex`，66 字：
  「已新建 notes.md，并实际读取核验，内容共两句话。由于缺少可确认的项目背景，目标范围限定为本次文件创建与核验，未编造业务目标。」
- step 2 `completed`，employee `codex`，120 字：
  实际读取后回答未包含「可验收」，并引用文件原文。

两步都是 `completed`，且第二步的结论建立在第一步真实生成的文件上，不是凭上下文编造。

### 真实工具事件（按序）

```
manager.delegated
employee.started(codex, step1)
tool.started/completed list_files  (step1)
tool.started/completed write_file  (step1)
tool.started/completed read_file   (step1)
employee.started(codex, step2)
tool.started/completed read_file   (step2)
```

### 文件审计与磁盘内容

`84e1690f….audit.jsonl`：

```json
{"action":"create","path":"notes.md","bytes":221}
{"action":"read","path":"notes.md","bytes":221}
{"action":"read","path":"notes.md","bytes":221}
```

磁盘文件 `workspaces/352009b8…/notes.md` 实际内容（221 字节）：

```
本次任务的目标是在当前项目中新建 notes.md，用两句话说明可确认的任务目标。
由于目前缺少可确认的项目业务背景，本次范围限定为完成该文件的创建与读取核验。
```

写入范围符合声明：只有新建与读取，没有覆盖、删除、Shell。

### 对话记录（`/api/conversation`）

| seq | role | step | status | 文本长度 |
|---|---|---|---|---|
| 1 | user | — | — | 81 |
| 2 | assistant | — | completed | 0（聚合位，存在步骤时不重复内容） |
| 3 | assistant | 1 | completed | 66 |
| 4 | assistant | 2 | completed | 120 |

序号稳定递增、无重复；步骤消息各自带状态，聚合消息为空文本，前端会隐藏该节点。

### 归属校验（同一实例的旁证）

- `/api/run?id=<run>`（缺 projectId）→ 400。

## 本轮修的三项在此次真实运行中的表现

- **逐步持久化**：两次员工调用各自落 `steps`，聚合 `answer` 由已完成步骤重算（「任务1：… 任务2：…」）。
- **乱序/归属**：页面读取走 `/api/conversation?id&projectId`，`/api/run` 必须带归属；未出现跨项目读取。
- **聚合与 UI**：步骤消息按 step 独立成条，经理端（本 run 无）与员工端在标签上可区分。

## 仍未覆盖

- 多步部分失败 / 中途取消的真实模型场景（仅替身测试覆盖）。
- 两个不同员工（Claude Code / WorkBuddy）的真实协作——宿主尚未接通，按设计拒绝。
- 重启后读回设置、改值后再发起请求的对照矩阵。
- 独立子 Agent 对本轮改动（含本次 E2E 代码路径）的复核。

## 清理

隔离实例为临时用途，数据目录 `/tmp/studio_e2e/data` 与 8892 进程在取证后停止/丢弃；未写入本机 `.studio`，未提交任何 `notes.md` 或 SQLite。


## 追加：Claude Code 作为第二员工（同日 14:1x–14:3x）

同一隔离数据目录之外，另在本机 `.studio` 上完成了第二个宿主的接入与真实运行。

- 前置验证：`POST /api/verify {host:claude, model:opus, effort:high}` → 200，2m10s，
  `actualModel=claude-opus-5-5`，`costUSD=0.104248`，账号绑定 `57f35b4b…`（端点哈希，不含令牌）。
- 首个双员工任务（run `a01c9740`）失败：员工第 2 步把 `opus` 发给了 Codex 适配器，
  报「模型调用失败」。定位为接线遗漏（经理调用已按宿主分派，员工调用仍用 `self.adapter`）。
- 修复后重跑（run `f0714188`，`allowedEmployees=["codex","claude"]`）：
  - 状态 `completed`，3 次真实调用：经理 `gpt-6.1-sol`（in 15438 / out 383）、
    Codex 第 1 步（in 62133 / out 338）、Claude 第 2 步（`claude-opus-5-5`，in 80 / out 1875，$0.1669）。
  - 步骤记录：step1 `codex` completed、step2 `claude` completed，页面显示
    「你 / Codex·第1步 / Claude Code·第2步」，不再出现重复的经理聚合气泡。
  - 文件审计仅 `read`，无写入；Claude 步骤通过同一 `file_tools` MCP 读取，未获 Shell。
  - 第二步正确指出 `requirements.md` 要求「最多两句」与任务要求「恰好三句」的冲突，
    并说明未自行取舍——不是照抄指令，这点可作后续验收观察点。
- 测试：48/48（新增「员工步骤使用各自适配器」；未验证的 Claude 型号仍被 settings 拒绝）。

仍未验证：Claude Code 作为「经理」（只验证过作为员工）、WorkBuddy、取消时 Claude 进程组的实际回收时间、
外网/断网下的失败表现。
