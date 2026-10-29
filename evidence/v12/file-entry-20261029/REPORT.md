# 本地HTML错误入口修复｜2026-10-29

用户截图显示新建项目及初始化 `Failed to fetch`，同时反馈整体看起来变大。浏览器当前地址为 `file:///Users/c0437/Desktop/agent-studio-v01/index.html`，而工作台API在 `http://127.0.0.1:8891/`。文件页面的相对API地址无法访问服务。实查8891进程正常，无需重启、清数据或改跨域权限。

修改前 `711b53c1a1efef4b79c2647ec86ff45aaa6ad481`；被测实现 `5a9efef748b0240f79c82558d44d1196eb0e5777`，分支 `opus-v12-handoff`。仅在前端启动时检查 `file:` 并转到固定本机入口，先于任何API请求；README补充打开方式，新增对应回归测试。没有修改字号、布局、后端或权限。

实测：

- `node --check app.js`：退出码0。
- `node --test tests/frontend.test.cjs`：13 tests / 13 pass / 0 fail / 0 skipped。文件入口测试执行实际 `boot()`，确认只重定向本机地址且API请求为0。工作树与上述被测提交内容一致。
- `git diff --check`：退出码0。
- 真实浏览器通过原有临时fixture（8892）创建「入口修复测试」，保存后弹窗关闭、无错误，刷新后项目仍存在；截图 `project-saved.png`，仅含合成数据。临时进程和标签已清理。
- 正常8891重新加载成功，项目名「测试项目集合」，无错误；计算字号body为14px、输入框14.5px。已检查上一轮diff，改变的是侧栏字号，全局、消息和输入字号没有改。已在新开的正常入口执行默认缩放快捷键；截图原文件页是否额外缩放尚未确认，未以CSS反向缩小补偿。

验证限制：浏览器工具不允许直接访问 `file:`，故文件入口跳转由确定性回归验证，未声称已浏览器实测该分支。此轮未重跑Python后端测试，后端没有变化；未触发真实模型或改用户数据。ROUTINE / REVIEW_OPTIONAL，无额外独立审查；CI NOT VERIFIED，NOT_DEPLOYED，待负责人确认显示效果。

回滚：`git revert 5a9efef748b0240f79c82558d44d1196eb0e5777`。
