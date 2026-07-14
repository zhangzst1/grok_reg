# CLI 浏览器环境 API 接入设计

## 目标

仅将 `register_cli.py` 的账号注册浏览器改为通过本地浏览器环境 API 启动和停止。GUI 注册流程及 CPA/OIDC 独立浏览器保持现有本地 Chromium 行为。

CLI 必须保证：

- 同一次运行中，每个注册工作线程独占一个 `env_id`。
- 同一个 `env_id` 不会同时启动两次。
- 注册浏览器窗口数不超过配置的 `env_id` 数量。
- API 启动、连接或停止失败时明确报错，不回退到本地 Chromium。

## 配置

`config.json` 和 `config.example.json` 增加以下字段：

```json
"browser_api_base": "http://127.0.0.1:50326",
"browser_api_token": "",
"browser_env_ids": [900, 901],
"browser_start_wait_seconds": 3,
"browser_api_timeout": 30
```

API Token 的读取优先级为：

1. 环境变量 `BROWSER_API_TOKEN`
2. `config.json` 的 `browser_api_token`

示例配置不包含真实 Token。Token 不写入日志。

## CLI 线程与环境绑定

CLI 加载配置后解析并去重 `browser_env_ids`。空值、重复值和非整数值视为配置错误。

实际注册线程数为：

```text
min(--threads, browser_env_ids 数量)
```

线程按照工作线程编号绑定环境：W1 使用列表第一个 `env_id`，W2 使用第二个，依此类推。工作线程处理多个注册任务时持续复用自己的环境；浏览器重启后仍使用原来的 `env_id`。

任务数大于工作线程数时进入现有任务队列等待，不创建额外浏览器。

## 浏览器环境客户端

新增一个 CLI 专用模块，负责：

- 保存当前线程绑定的 `env_id`。
- 调用 `POST {browser_api_base}/api/browser/start`，请求体为 `{"envId": env_id}`。
- 校验 HTTP 状态、JSON 结构和 `data.port`。
- 等待 `browser_start_wait_seconds` 后，通过调试端口连接浏览器。
- 调用 `POST {browser_api_base}/api/browser/stop`，请求体为 `{"envId": env_id}`。
- 记录每个 `env_id` 的启动状态，阻止同一环境重复启动。
- 在启动失败时回收内部状态；停止操作保持幂等。

连接现有 DrissionPage 浏览器管理时使用：

```python
options = ChromiumOptions().set_local_port(debug_port)
browser = Chromium(options)
```

这与参考代码使用相同的调试端口连接方式，同时保留项目对 `Chromium`、`tab_ids` 和标签页生命周期的现有依赖。

## TabPool 集成

`TabPool` 增加可选的浏览器创建和释放钩子：

- 未配置钩子时继续执行 `Chromium(options)` 和 `browser.quit()`，保证 GUI 行为不变。
- CLI 启动时配置外部环境创建/释放钩子。
- `TabPool._create_browser()` 通过创建钩子调用启动 API 并连接调试端口。
- `TabPool.release_tab()` 通过释放钩子调用停止 API。
- `restart_browser()` 原有的“释放再启动”调用链自动转化为“停止环境再启动同一 env_id”。

CLI 结束时继续调用 `TabPool.shutdown()`，确保所有已启动的注册环境都执行停止接口。

## 错误处理

以下情况直接终止注册或当前工作线程，并输出不含 Token 的错误：

- 未配置 API Token。
- `browser_env_ids` 为空、重复或格式无效。
- 启动或停止接口 HTTP 失败。
- 启动接口返回值缺少 `data.port` 或端口无效。
- 同一 `env_id` 被重复启动。
- DrissionPage 无法连接返回的调试端口。

停止失败时仍清理本地线程绑定状态，避免程序内部永久占用环境；错误会写入日志，供操作者检查环境管理器状态。

## 测试

使用 `unittest` 和 Mock，不调用真实浏览器服务：

- 配置两个 env ID、请求三个线程时，实际注册线程限制为两个。
- 每个工作线程绑定不同 env ID。
- 启动请求包含正确的 URL、Bearer Token 和 `envId`。
- 启动响应的调试端口传给 `ChromiumOptions.set_local_port()`。
- 重启和线程退出调用对应 env ID 的停止接口。
- 同一个 env ID 的重复启动被拒绝。
- API 错误和无效响应不会回退到本地 Chromium。
- 未启用 CLI 外部钩子时，现有 `TabPool` 行为保持不变。

## 范围外事项

- 不修改 GUI 注册浏览器。
- 不修改 `cpa_xai/browser_confirm.py` 的 CPA/OIDC 浏览器。
- 不改变邮箱分配、注册步骤、Mint 队列或账号输出格式。
- 不把真实 API Token 提交到仓库。
