# Hotmail API 超时与邮箱重试配置修复设计

## 目标

修复 Hotmail 外部 API 模式把超过服务端上限的 `mail_timeout` 原样传给 `timeout_seconds` 而导致 HTTP 400 的问题，并让 CLI 与 GUI 一致遵守 `mail_retry_count`，使配置为 `0` 时不再换邮箱重新注册。

## 已确认根因

外部 `/wait-message` 接口要求 `timeout_seconds` 位于 1–120 秒。当前 `fill_code_and_submit()` 从 `mail_timeout` 读取到 150 后，`get_oai_code()` 的 API 分支将其原样传入 `VerificationCodeFetcher.fetch_code()`，服务端因此返回 `INVALID_PARAM`。

邮箱阶段存在两个独立问题：

- CLI 使用 `config.get("mail_retry_count", 3) or 3`，配置值 `0` 会被替换成默认值 `3`。
- GUI 将最大邮箱尝试次数硬编码为 `3`，完全不读取 `mail_retry_count`。

`VerificationCodeFetcher.DEFAULT_MAX_RETRIES=3` 属于外部 HTTP 请求的临时错误重试，与换邮箱重新注册是不同层级。本次不改变该行为。

## 配置语义

`mail_retry_count` 继续兼容现有“最大邮箱尝试次数”行为：

- `0`：只尝试一个邮箱，不换邮箱。
- `1`：只尝试一个邮箱，不换邮箱。
- `2`：最多尝试两个邮箱。
- 正整数 `N`：最多尝试 N 个邮箱。
- 缺失、空值、非数字或解析失败：使用默认值 3。
- 负数：按 1 次处理。

虽然配置键名称包含 `retry_count`，为避免把现有默认 3 从总计 3 次改变为总计 4 次，本次不将它重新解释为“初次尝试之外的额外重试次数”。示例配置和 README 应明确它实际表示最大邮箱尝试次数。

## 实现设计

在注册核心中增加一个无副作用的配置解析函数，负责把 `mail_retry_count` 转换为最大邮箱尝试次数。CLI 通过 `reg` 调用该函数，GUI 直接调用同一函数，避免两端再次产生不同语义。

Hotmail API 分支在调用 `fetch_code()` 前将上层 timeout 限制到服务端允许范围：

```python
api_timeout = max(1, min(int(timeout), 120))
```

配置为 150 时传 120；配置为合法值时保持原值。该限制只应用于 `hotmail_code_mode=api`，不改变 IMAP、手动模式或其他邮箱提供商的总超时。

## 数据流

邮箱尝试次数：

1. CLI 或 GUI 开始单个账号注册。
2. 统一解析函数读取 `config["mail_retry_count"]`。
3. 两端使用返回值创建邮箱尝试循环。
4. 值为 0 或 1 时循环只执行一次，验证码失败后直接结束当前账号，不再更换邮箱。

API 超时：

1. `fill_code_and_submit()` 读取通用 `mail_timeout`。
2. `get_oai_code()` 检测 Hotmail API 模式。
3. API 分支把 timeout 限制到 1–120。
4. `VerificationCodeFetcher.fetch_code()` 接收合法的 `timeout_seconds`。

## 错误与日志

- API 超时被限制时，可通过现有 `log_callback` 记录实际使用的超时值，便于诊断，但不记录 API Key 或验证码。
- `mail_retry_count=0` 不影响当前邮箱内部的 HTTP 临时错误重试。
- API 的 HTTP 4xx（429 除外）继续由工具类直接抛出，不做内部重试。
- 邮箱阶段失败继续使用现有错误标记与账号失败处理，只是不再在最大尝试次数为 1 时更换邮箱。

## 测试

新增或扩展测试覆盖：

1. API timeout 150 被限制为 120。
2. API timeout 60 保持 60。
3. 邮箱尝试次数解析：0→1、1→1、2→2、缺失/空值/非法值→3、负数→1。
4. CLI 使用统一解析函数，不再通过 `or 3` 把 0 转为 3。
5. GUI 使用统一解析函数，不再硬编码 3。
6. 原有 API、manual、IMAP、CLI 和 GUI 测试继续通过。

测试 mock 外部 API，不发真实网络请求。

## 文档

- `config.example.json` 将 `mail_timeout` 说明补充为 Hotmail API 模式最多传 120 秒。
- `mail_retry_count` 说明改为“邮箱阶段最大尝试次数；0/1 表示不换邮箱”。
- README 增加相同配置说明，明确它不控制外部 API 内部 HTTP 重试。

## 范围外事项

- 不修改 `VerificationCodeFetcher` 的 HTTP 重试次数、退避或代理回退实现。
- 不修改 plus alias 分配方式。
- 不改变其他邮箱提供商的 timeout 行为。
- 不重命名 `mail_retry_count`，以保持配置兼容。
