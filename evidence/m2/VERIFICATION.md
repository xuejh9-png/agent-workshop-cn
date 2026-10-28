# M2 真实最小闭环 — 2026-10-28

Context pinned: 0174a45860d81467270168860a546d1dc7acecc4。
基线: 513ba99538675222d33559091711bcc4846abe62。
最终被测实现: **5816b185ecf013377f7cabcfd851a69b06f59606**。最终单测21/21、语法检查、GUI文件生成、真实产物预览、多屏截图、设置保存；安全独审确认可在应用内测试工作区验收。后续证据提交不改实现。

## 确定性验证

`python3 -m unittest discover -s tests -v` → Ran 21 tests / OK（unit-tests.txt）。测试使用替身验证状态和模型参数，真实文件边界测试无替身；不以这些代替真实模型。

`node --check app.js`、`python3 -m py_compile server.py runtime.py file_tools.py`、`git diff --check` 均退出0。安全独审额外检查 Host/Origin/CSRF、根与祖先链接、20次工具上限、子进程组停止、状态与产物保留，详见 SECURITY_REVIEW.md。

## 真实本机调用

Codex CLI 0.165.0-alpha.1.2，`codex login status` 返回 Logged in using ChatGPT。不读取/复制凭据，不使用 API Key；Claude Code 2.1.308 安装状态沿用前轮，尚未接入执行适配。

候选目录来自真实 `codex app-server --stdio` 的 initialize → model/list。目录8项；其中 gpt-6-luna 与 gpt-6.1-terra 分别真正完成连接测试（10.8s/9.6s）。其余候选不能直接运行，必须先测试。

调用形状：

```
codex exec --ignore-user-config --ephemeral --skip-git-repo-check \
  --sandbox read-only -C <本次应用工作空间> -m <明确型号> --json \
  -c features.shell_tool=false -c web_search="disabled" \
  -c model_reasoning_effort=<明确强度> ... -
```

任务走 stdin；无 Shell 拼接。临时 studio_https provider 沿用官方身份、关闭 WebSocket；实测默认 WebSocket重试后才能成功，切HTTPS后连接恢复。配置只属于该子进程，不修改用户config，不改变型号。

主控不挂文件工具。执行器仅挂本地 studio_files MCP 的 list/read/write 白名单；自有工具审批配置不是全局放权，写操作仍需实际 run.allowWrite，且只允许在当前空间新建、不覆盖。原型DEMO与假模型已从默认路径移除。

## 实际验收记录

完整脱敏本机测试记录：live-runs.json（仅本轮自造中文测试题/资料，不含凭据、用户真实私人对话或业务数据）。

- **AT-01/02 主控直接回答**：run `01ca08707062417faf6b6e590aafef8e`，界面问“你是谁？请用一句中文回答”，Luna真实返回自然中文，仅1次主控请求，无文件或三步卡。此最早运行在94c775c开发过程中，后续主控接口未改变。
- **AT-03/04 真实读取与切型号**：GUI选择Codex/Terra，run `dadc29a532e4428d838b1d38dc589914`，实际事件 read_file，读取 requirements.md 258字节。再GUI选Codex/Luna，run `3a34bfd2f67a476b831aeeb0cd4514cc`，真实读取并创建 summary.md。请求参数/会话/真实Token均已保存；CLI没有独立回传上游实际型号，因此 actualModel=UNKNOWN，不凭自报名称断言。
- **主控自动委派**：run `a384ec801a7e4bc59f8f39ef73aae3c0`；GUI选择自动、要求读取资料，主控产生delegate决策，随后启动1个真实Codex执行器。共2次模型调用，有文件read审计；无固定三Agent。此运行在0391305安全修复版本，最终后台调度逻辑一致。
- **AT-08 真实附件**：通过浏览器文件选择器上传 tests/fixtures/requirements.md，后端真实保存，再由CLI的MCP工具读取；不是仅记名字。
- **AT-09 最终产物**：最终5816b18上GUI勾本次创建权限，run `cc6936218d5c4964a5f1c1744c219efb` 实际读取资料、创建 summary-final.md（162字节），浏览器打开真实内容。内容/SHA256见 artifact-proof.json；截图1440-final-file.jpg。
- **AT-10 真停止/刷新/重启**：GUI启动run `22dcebe3089341919186b35de8fb81ef`，捕捉真实PID52089后点击停止。API状态cancelled，ps退出1、进程不存在；刷新后记录仍存在。cancel-proof.json。真实服务多次重启后先前回答和产物仍在；运行中重启标记interrupted的处理另由确定性测试验证，未宣称原生会话续跑。
- **AT-12/13 安全/错误局部验证**：http-checks.txt中缺令牌、外Origin为403，越界/覆盖/未知型号/未接入引擎为400；没有静默替换型号。不虚构额度耗尽或未登录实测。
- **AT-14 用量**：调用分别记录coordinator/executor、input/output/cache Token，来源CLI turn.completed；实际扣费未知。取消调用可能消耗但未收到Token，不能当0。
- **AT-16**：真实5816b18页面1440/1024/768/375宽，后三者scrollWidth==clientWidth，浅深色实图。浏览器 error/warn日志[]。
- **设置**：GUI保存主控Luna/low、执行Luna/low；后端持久配置。调用次数上限1/2由后端强制；金额硬预算未实现。

## 已发现并修复的真实失败

1. 早期工具仅因CLI默认never审批而被拒，后端未执行文件。为自有三项受限文件工具增加白名单策略并经独审，真实MCP调用成功；没有使用danger flags。
2. 首次最终复验run `817ad733ed10489aa79fa76494207c7e` 后端allowWrite=true但未把明确授权说明传给模型，模型误拒创建文件。此记录保留，未伪称生成成功。5816b18增加实际权限传递断言并重跑，最终文件创建成功。界面用“已结束”表示调用结束，不冒充目标必然完成。

## 未完成/未验证

AT-05/07/14/17部分实现；完整M3仍缺外部目录绑定、资料删除/重索引、PDF/DOCX、完整预算/账户资料。AT-06复杂跨Harness、AT-11独立产品审核、Claude/WorkBuddy适配未实现。AT-13真实账户登出/额度耗尽、AT-15网络断流后原生续跑、全部键盘/读屏/多标签并发未全面验证。主控/执行的实际模型只能证明明确参数与成功CLI会话，上游标签UNKNOWN。费用未知，不声称免费或已核对订阅账单。

CI未配置：NOT VERIFIED。部署：NOT_DEPLOYED（仅本机loopback）。完整AT-01～18不是全部PASS。
