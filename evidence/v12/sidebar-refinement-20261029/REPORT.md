# 项目侧栏局部调整｜2026-10-29

- 用户反馈：参照 ChatGPT 的项目侧栏；新建对话放在项目标题右侧，项目下直接列对话，不要分享入口。
- 修改前：`cda71e9925d98abd0e0d41ce8a03959dd1e83ff5`。
- 被测实现：`1df4e334d7e28d3195ab0d64ca00b56c9b261cf5`，分支 `opus-v12-handoff`。
- 范围：仅 `app.js` / `index.html`。复用原新建对话、重命名、历史分页、资料和源码授权能力；未改后端、数据库或权限边界。

项目标题行现在包含文件夹、项目名、菜单和常显的新建对话按钮。项目下只列历史对话；「项目资料与指令」「本机项目与源码」收进「⋯ → 项目设置」。菜单包含重命名、设置、项目主页及历史分页，没有分享入口。

## 实测

在原有 `tests/g5_fixture.py` 的临时数据环境（8892）通过真实浏览器操作检查：标题行新建对话立即聚焦输入框，原历史仍存在；重命名和项目设置指向被点击的项目；项目B资料预览为B独占内容；源码授权入口可到达；历史分页入口可用；菜单支持上下键、回车和 Escape，关闭后返回触发按钮。

桌面1280×720及手机375×900，深浅色截图见本目录。375宽度下新建按钮与项目名同一行、菜单在视口内，文档宽度375，无横向溢出。结构化检查见 `checks.json`。所有截图均为合成测试数据，没有上传真实会话或凭据。

在被测提交运行：

```text
node --check app.js
退出码 0

node --test tests/frontend.test.cjs
tests 12 / pass 12 / fail 0 / skipped 0

/Users/c0437/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -m unittest discover -s tests
Ran 91 tests in 3.775s
OK

git diff --check
退出码 0
```

实际完整测试输出在 `frontend-tests.txt` / `python-tests.txt`。未修改或跳过原有测试，失败集合为空。此轮未触发真实模型调用；原G5证据与WorkBuddy文件工具限制保持有效。临时fixture进程和标签页收尾清理；本机8891打开更新界面供负责人查看。

状态：局部工程验证通过，负责人视觉验收待确认；ROUTINE / REVIEW_OPTIONAL，本轮未另派独立审查。CI NOT VERIFIED，NOT_DEPLOYED，未合并main。

回滚：`git revert 1df4e334d7e28d3195ab0d64ca00b56c9b261cf5`，刷新页面。
