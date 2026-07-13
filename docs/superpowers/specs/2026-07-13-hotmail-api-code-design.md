# Hotmail/Outlook 外部 API 验证码设计

## 目标

为 Hotmail/Outlook 增加第三种验证码获取方式 `api`。选择该模式时，注册流程使用 `utils/verification_code.py` 中的 `VerificationCodeFetcher.fetch_code()` 获取验证码，同时保留现有 `manual` 和 `imap` 行为。

## 配置与界面

`hotmail_code_mode` 支持以下值：

- `manual`：通过 CLI 或 GUI 由用户手动输入验证码，继续作为默认值。
- `imap`：使用现有 Microsoft OAuth2 XOAUTH2 IMAP 流程自动收码。
- `api`：调用外部验证码 API 自动收码。

GUI 的 Hotmail 验证码方式下拉框增加 `api` 选项。`config.example.json` 和 README 同步说明第三种模式。未知配置值继续抛出明确错误，不静默回退。

## 架构与数据流

核心分流继续集中在 `grok_register_ttk.get_oai_code()`：

1. 检测当前邮箱提供商是否为 Hotmail/Outlook。
2. 读取并标准化 `hotmail_code_mode`。
3. `manual` 和 `imap` 保持原有调用路径。
4. `api` 模式延迟导入并创建 `VerificationCodeFetcher`，调用 `fetch_code(email, timeout_seconds=timeout)`。
5. 返回的验证码交给现有网页填写与提交逻辑处理。

直接复用工具类，不复制其 HTTP、重试、代理回退或验证码提取实现。延迟导入使其他邮箱提供商以及 Hotmail 的 `manual`、`imap` 模式不依赖该模块的初始化。

## 超时、日志与错误

- 将 `get_oai_code()` 接收到的 `timeout` 作为 `fetch_code()` 的 `timeout_seconds`，保持上层超时配置有效。
- API 工具继续使用文件中已有的默认 API Key、请求超时、重试次数和代理故障直连行为。
- 获取成功时，通过现有 `log_callback` 输出不包含密钥的成功信息。
- `VerificationCodeError` 和其他 API 调用异常统一包装为包含原始原因的 `RuntimeError`，错误前缀为“Hotmail API 获取验证码失败”。
- 取消回调在开始 API 请求前检查一次。由于现有 `fetch_code()` 是同步阻塞调用，请求进行中不能即时取消；完成或超时后仍由现有上层流程处理。
- API 失败继续参与现有邮箱阶段失败、别名标记及重试机制。

## 依赖

`utils/verification_code.py` 使用 `requests`。项目运行环境当前能够导入并编译该文件；本次接入不改写工具实现。若独立安装环境未通过传递依赖提供 `requests`，应在项目直接依赖中补充它，以确保依赖声明完整。

## 测试

在现有 Hotmail 验证码测试中新增以下覆盖：

1. `api` 模式创建 `VerificationCodeFetcher` 并使用目标邮箱调用 `fetch_code()`。
2. 上层 `timeout` 正确传给 `timeout_seconds`。
3. API 返回验证码时，核心函数原样返回该验证码供现有填写流程使用。
4. API 工具异常被包装为带明确前缀和原始原因的错误。
5. API 模式开始调用前执行取消检查。
6. 未知模式错误信息列出 `manual`、`imap`、`api`。
7. 原有 `manual`、`imap`、CLI 和 GUI 测试继续通过。
8. GUI 下拉框和示例配置包含 `api`。

测试使用替身隔离外部网络，不真实调用验证码 API。

## 范围外事项

- 不修改 `VerificationCodeFetcher` 的外部 API 协议、默认密钥或重试算法。
- 不改变 Hotmail 邮箱和 plus alias 的分配方式。
- 不修改其他邮箱提供商的验证码获取逻辑。
- 不把外部 API 模式设为默认值。
