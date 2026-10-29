# 交接：Agent Studio v1.2 当前状态（给下一位执行者）

日期：2026-10-29｜分支：`opus-v12-handoff`｜远端：**未推送**（比 origin 多 11 个提交）
最后提交：`ff6195d`

> 本文只描述**现状与证据位置**。产品权威仍以 `xuejh9-png/my-ai-context` 的
> AW-D-007、`PRODUCT_REQUIREMENTS_AND_ACCEPTANCE_V1_2.md`、
> `IMPLEMENTATION_PLAN_V1_2_CODE_REVIEW.md` 和原 Issue #10 为准。

## 一分钟了解

这是本机的 Agent Studio：一个「项目经理 → 授权员工」的本地工作台。
经理拆任务，员工在受限文件工具（只读 / 只新建 md、txt）里干活，全过程落 SQLite 并可查真实用量。
服务只监听 127.0.0.1，页面用一次性 token 校验。

**当前可用宿主**

| 宿主 | 状态 | 说明 |
|---|---|---|
| Codex | 可用 | 经理与员工都跑过真实任务；模型 `gpt-6.1-sol` 已验证 |
| Claude Code | 可用 | headless `claude -p`；`opus` 已验证，真实跑过员工步骤（`claude-opus-5-5`，$0.167） |
| WorkBuddy | **代码已接入，缺 API Key** | 应用包自带 CodeBuddy CLI 2.165.0；42 个真实型号已列出；界面可填 Key |

## 怎么跑起来

```bash
cd /Users/c0437/Desktop/agent-studio-v01
python3 server.py            # 默认 127.0.0.1:8891
```

浏览器打开 `http://127.0.0.1:8891`。数据在 `.studio/`（不入 Git，含真实对话与账号绑定哈希，**不要提交或外传**）。

测试：

```bash
python3 -m unittest discover -s tests     # 50/50
node --check app.js
```

## 这一轮做了什么（按时间）

1. 修复独立复核确认的三项 P2：非对象 JSON 让 run 永久 `running`、委派步骤消息不显示（并牵出渲染游标
   指向已脱离节点导致 `insertBefore` 抛错，第 2 步永不渲染）、空回答存成成功。
2. 修复两个 P3：分页连点导致游标回退、步骤消息写入失败后与 run 记录不一致（`page()` 读取时自愈）。
3. 安全：`/api/run`、`/api/cancel`、`/api/files`、`/api/file`、`/api/upload` 全部要求项目归属；
   `cancel` 的 HTTP 入口不再允许省略 `projectId`。
4. 接入 Claude Code 宿主（经理可选、员工可授权），修掉「员工步骤误用 Codex 适配器」的接线错误。
5. 接入 WorkBuddy 宿主（缺密钥，未验证）。

## 关键文件

| 文件 | 作用 |
|---|---|
| `server.py` | HTTP 服务、`Studio` 编排、`work_v12` 逐步执行、`host_status` |
| `v12.py` | 设置 v2、项目/对话/消息迁移、`page()` 分页与步骤自愈 |
| `runtime.py` | 三个宿主适配器（Codex / Claude / WorkBuddy）+ 进程组终止 |
| `file_tools.py` | 受限文件 MCP（越界、链接、覆盖、大小均拒绝） |
| `app.js` / `index.html` | 单页前端，无框架 |
| `evidence/v12/` | 各轮证据：修复记录、真实 E2E、测试输出 |

## 尚未完成（不要当成已完成）

- **WorkBuddy 真实调用**：缺 API Key。设置 → 连接及验证 → WorkBuddy 有密码输入框，
  保存后写入 `~/.workbuddy/api-key`（0600），再点「测试连接」验证型号（如 `deepseek-v4.1-flash`）。
- **Claude Code 作为经理**：只验证过作为员工。
- **G4 剩余**：外部项目目录逐级授权、真实代码修改的 diff/审批/回滚、独立审核。
- **G5**：AT-19～30、1440/1024/768/375 浅深色回归、原 21 项不得退化。
- 未部署、未推送、未合并 main。

## 已知坑

- 服务启动后的**第一次** bootstrap 偶尔把 Codex 报成「未登录」（app-server 冷启动抖动）。
  已有重试与缓存兜底；再请求一次即正常，不是登录失效。
- Claude Code 冷启动约 1–2 分钟/次，别误判为卡死。
- WorkBuddy 的 CLI 未认证时**退出码是 0**，只能按输出文本判断。
- `.studio/connection-namespace` 是随机盐；换数据目录就会换 `accountId`，旧验证不会继承——这是设计。
- 前端 `renderMessages` 依赖 `state.messages`，修改异步入口时务必保持「请求时绑定 cid/pid + 返回后校验」。

## 回滚

```bash
git revert 533d424 7efc63c 939dd4f 7540f0e 4187fc5 5a3373d 3492393 a3a4962 132a98f
```

数据库备份在 `.studio/backups/`（`pre-v12-*.sqlite` 迁移前、`pre-restart-*.sqlite` 重启前）。
迁移只新增记录，旧 run/workspace/file 原样保留。
