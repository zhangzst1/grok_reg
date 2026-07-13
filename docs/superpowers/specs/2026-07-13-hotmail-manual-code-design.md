# Hotmail/Outlook 手动验证码设计

## 目标

为 Hotmail/Outlook 邮箱增加可配置的验证码获取方式：默认由用户手动输入，配置为 `imap` 时继续使用现有 XOAUTH2 IMAP 自动收码。命令行版和 GUI 版均需支持，其他邮箱提供商行为不变。

## 配置

新增配置项：

```json
"hotmail_code_mode": "manual"
```

允许值：

- `manual`：默认值，由用户输入验证码。
- `imap`：沿用现有 Microsoft OAuth2 refresh token、XOAUTH2 IMAP 自动收码流程。

未知值应记录清晰错误并终止当前邮箱尝试，不静默回退到另一模式。

## 架构

核心注册流程通过统一的“手动验证码提供器”获取人工输入，不直接依赖 Tkinter 或控制台。提供器接口接收目标邮箱，并返回用户输入的验证码字符串。

验证码数据流：

1. `fill_code_and_submit()` 请求验证码。
2. `get_oai_code()` 检测当前邮箱提供商。
3. Hotmail/Outlook 根据 `hotmail_code_mode` 分流：
   - `manual`：调用传入的手动验证码提供器。
   - `imap`：调用现有 `hotmail_get_oai_code()`。
4. 返回的验证码进入统一的格式校验和标准化逻辑。
5. 现有网页验证码填写逻辑继续负责移除连字符并提交表单。

## 命令行交互

`register_cli.py` 提供控制台验证码提供器：

- 提示中包含目标邮箱，防止多账号混淆。
- 使用进程内锁串行化 `input()`；多注册线程不能同时抢占标准输入。
- 接受 `ABC-123` 或 `ABC123` 格式，忽略首尾空白。
- 格式错误时在同一输入会话中重新提示。
- 空输入、EOF 或键盘中断视为用户取消，当前邮箱尝试失败并走现有错误处理。

手动模式下虽然浏览器注册可以多线程运行，但等待输入的线程会按到达顺序串行提示。

## GUI 交互

`GrokRegisterGUI` 提供 GUI 验证码提供器：

- 工作线程不得直接调用 Tkinter 对话框。
- 工作线程创建等待事件，并通过 `root.after()` 请求主线程显示 `simpledialog.askstring()`。
- 对话框标题和正文包含目标邮箱。
- 输入合法后保存结果并唤醒对应工作线程。
- 格式错误时显示提示并重新打开输入框。
- 用户取消或关闭窗口时，唤醒工作线程并让当前邮箱尝试失败。
- 多个注册线程同时等待验证码时，由 GUI 主线程逐个处理对话框，避免窗口重叠和账号错配。
- 停止批处理时，等待中的验证码请求应被取消，不能永久阻塞退出。

## 验证码格式

统一接受以下格式：

- `ABC-123`
- `ABC123`

校验规则为六位 ASCII 字母或数字，中间可以有一个连字符。返回值保留用户输入中的连字符；现有提交逻辑负责在填写网页前移除连字符。

无效示例包括空字符串、少于或多于六位、包含空格以及包含其他标点符号。

## 错误处理

- 未配置手动提供器时，抛出明确错误：当前 Hotmail 手动模式缺少输入通道。
- 用户取消时，错误信息应明确说明“手动验证码输入已取消”。
- IMAP 模式保持现有超时、重发和 OAuth refresh token 更新行为。
- 手动模式不启动 IMAP、不刷新 Microsoft access token，也不修改 refresh token 文件。
- 用户输入验证码后，若网页拒绝验证码，继续沿用现有注册失败和邮箱错误记录机制。

## 测试

使用 Python 标准库 `unittest`，避免增加运行依赖。测试覆盖：

1. `manual` 模式调用手动验证码提供器，并且不调用 IMAP。
2. `imap` 模式调用原有 Hotmail 自动收码逻辑。
3. `ABC-123` 和 `ABC123` 均通过校验。
4. 空值、长度错误和非法字符被拒绝。
5. 未提供回调和用户取消产生明确错误。
6. 非 Hotmail 邮箱仍走原有 provider 分支。
7. CLI 输入锁保证同时只有一个线程读取标准输入。

## 文档与兼容性

- 更新 `config.example.json` 和 README 的 Hotmail 配置说明。
- `config.json` 未配置 `hotmail_code_mode` 时默认使用 `manual`，符合本次行为变更。
- 已有用户若希望维持自动收码，需要显式设置 `"hotmail_code_mode": "imap"`。
- `mail_credentials.txt` 在手动模式仍用于分配 Hotmail 主邮箱和 plus alias；密码、ClientID、refresh token 不参与验证码获取，但保持原有文件格式以兼容切换回 IMAP。

## 不在本次范围内

- 不移除或重写现有 IMAP 代码。
- 不修改 CloudMail、Cloudflare、DuckMail、YYDS 的验证码逻辑。
- 不增加网页形式的远程验证码输入服务。
- 不改变账号、SSO 或 CPA 凭证输出格式。
