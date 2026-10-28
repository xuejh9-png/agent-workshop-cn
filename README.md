# Agent Studio · 本地工程工作名

沿用负责人已通过的方案 B。当前是 M2 首条真实执行闭环，M3 部分设置/文本附件已实现；完整跨执行器产品未完成。名字与品牌延后。

## 启动

要求：Python 3.11+、已登录的 Codex CLI。本机实测版本 `0.165.0-alpha.1.2`。

```
python3 server.py
```

打开 http://127.0.0.1:8891 。只绑定本机，不自动部署。数据在被 Git 忽略的 `.studio/`：SQLite 运行/设置、工作空间文件、只含操作路径和大小的审计记录。不要把此目录提交到 GitHub。

首次使用：设置→模型与连接→测试具体型号（一次真实调用会使用额度）→主控与默认执行→分别保存主控/执行型号与强度。目录来自 Codex App Server，候选不等于有权限；只有完成真实测试的型号才可选。输入框可覆盖本次执行方式和型号。运行中变更只影响下次请求。

默认「自动」由主控模型直接回答或委派文件任务；简单问答只调用主控一次，不创建三步卡。手动「Codex」会直接交给执行器；内部消息不刷到主对话。主控使用结构化输出决定 answer/delegate，程序强制执行权限和调用次数上限。

附件与项目知识目前支持真实 UTF-8 md/txt、每份 256KB；只上传到应用内工作空间。模型需通过 MCP read_file 读取，详情记录来源；生成文件需勾选「本次允许…新建」，仅允许创建新的文本，不能覆盖。产物可以真实预览。当前不绑定外部目录，不访问 YiPex/Investment OS。

## 接入和安全边界

- Codex CLI 使用当前已登录身份，未读取/复制密钥，未改用户全局配置。自有临时 `studio_https` provider 仅切换 HTTPS、沿用官方 OpenAI 身份，避免本机 WebSocket 重试延迟，不更换请求模型。
- 用户/项目插件、Hooks、Shell、浏览器、应用与子 Agent 等能力显式关闭；不加载用户 config。执行器仅挂载自有受限 `studio_files` MCP；主控不挂载文件工具。无危险跳过沙箱参数。
- 受限工具只读/创建工作空间文本；文件服务逐级 O_NOFOLLOW、拒绝硬链接/特殊文件、根目录描述符、防覆盖、每次工具调用上限。自有工具白名单可调用不等于任意外部 MCP 授权；写权限仍逐次由后端验证。
- HTTP 检查精确 Host、Origin、跨站来源和每进程令牌；没有跨域放行。CLI 通过参数列表与 stdin 调用，不将任务拼入 Shell。
- 取消终止进程组与 MCP 子进程。取消不自动回滚文件；失败/重启不会自动重试写操作。服务重启后遗留运行标记中断。前端从后端读取状态，不依赖 localStorage 假运行。
- 两次调用硬上限可配置；CLI 返回 Token，未返回实际账单金额，因此费用为未知。CLI 未独立回传上游实际模型名称，显示请求型号、成功会话证据与 actualModel UNKNOWN，不将自报名称当证据。

## 当前限制

Claude Code/WorkBuddy 尚未接入，不可选；第二执行器、独立新会话审核、复杂协作、实际金额预算、外部目录绑定、PDF/DOCX、文件删除与重索引、完整 Token 预扣预算、账户头像等仍未完成。完整产品 AT-01～AT-18 不全部通过。CLI 自身基础指令较长，小任务也有上下文开销；用量详情展示 CLI 实际计量，不假装零费用。

## 验证与回滚

```
python3 -m unittest discover -s tests -v
node --check app.js
python3 -m py_compile server.py runtime.py file_tools.py
```

确定性测试使用接口替身，不冒充真实模型。真实浏览器/CLI证据和权限独审见 `evidence/m2/`；旧 `evidence/VERIFICATION.md` 和旧截图属于 M1 历史 DEMO。

修改基线 `513ba99538675222d33559091711bcc4846abe62`。源码保留 Git 历史；回滚共享实现用普通 `git revert`，数据先备份 `.studio/`（私人本机，禁止上传）；M1 不能读新运行记录，但不会删除其数据。NOT_DEPLOYED。

图标沿用 M1 内联线性 SVG，并新增可替换自制几何临时标识，不决定正式品牌。既有 Lucide 归属参考见 NOTICE-LUCIDE。

协议参考：[App Server](https://learn.chatgpt.com/docs/app-server)、[MCP 配置](https://learn.chatgpt.com/docs/extend/mcp)、[配置项](https://learn.chatgpt.com/docs/config-file/config-reference)。实际能力以本机测试为准。
