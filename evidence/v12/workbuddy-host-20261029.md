# WorkBuddy 宿主接入状态（2026-10-29）

分支：opus-v12-handoff｜提交：7efc63c｜状态：**代码闭环，真实调用未验证（缺 API Key）**

## 事实认定

- WorkBuddy 是 Electron 桌面应用（com.tencent.workbuddy.mac 5.9.3），**PATH 上没有 CLI**。
- 应用包内自带 `@genie/agent-cli` 2.165.0：
  `/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/dist/codebuddy-lite-wb.mjs`
  可用系统 node 直接运行（`--version` → 2.165.0）。
- 参数与 Claude Code 同构：`-p`、`--output-format json`、`--model`、`--mcp-config`、
  `--strict-mcp-config`、`--allowedTools`、`--disallowedTools`、`--effort`、`--json-schema`。
- 认证：`CODEBUDDY_API_KEY` / `CODEBUDDY_AUTH_TOKEN`；无需登录时输出
  `Authentication required. Please use /login command…`，**退出码仍为 0**——必须按文本判定。
- 可用模型（CLI 自述）：auto / glm-5.1 / glm-5.0-turbo / glm-5.0 / glm-4.7 /
  kimi-k2.5 / minimax-m2.7 / deepseek-v3-2-volc。与 Codex、Claude 不是同一模型家族。

## 已实现

- `runtime.WorkBuddyAdapter`：与另两个宿主共用同一套 `file_tools` MCP 与审计；
  仅允许 list/read（授权写入时加 write），Bash/Edit/Read/Glob/Grep/WebFetch/Task 显式拒绝。
- 凭据读取顺序：环境变量 → `~/.workbuddy/api-key` → `~/.codebuddy/api-key` → `~/.codebuddy/settings.json` 的 env。
  密钥不写库、不经 API 返回、不进日志。
- `Studio.hosts` 加入 workbuddy，`adapter_for/verify/resolve/员工步骤` 按宿主分派；
  `host_status` 只对 CLI 宿主做启动重试（缺密钥是配置事实，重试无意义）。
- 未认证时如实返回：「WorkBuddy 未配置 API Key：请把密钥写入 ~/.workbuddy/api-key」。
  界面员工列表里显示为不可勾选，并给出该原因，不用桌面端冒充可用。

## 验证情况

- 测试 50/50：新增「无密钥时报告真实原因且不能启用」「WorkBuddy 员工走自己的适配器」。
- bootstrap 实测：codex ✓ / claude ✓ / workbuddy ✗（原因如上），catalogByHost 中 workbuddy 为空。
- **未做**：带真实密钥的一次 `--verify` 与一次真实员工步骤；因此形态/型号/计费均未实测，
  不能宣称 G4 的 WorkBuddy 部分通过。

## 解锁条件（一步即可）

把 API Key 写入仅本人可读的文件：

    umask 077; printf '%s' 'YOUR_KEY' > ~/.workbuddy/api-key

之后重启服务（或直接刷新页面），在「设置 → 连接及验证 → WorkBuddy」点「测试连接」，
通过后即可在「员工与模型」勾选启用并在输入框授权。

## 回滚

本次为单提交 `7efc63c`；`git revert 7efc63c` 可回到只有 Codex + Claude 的状态。
