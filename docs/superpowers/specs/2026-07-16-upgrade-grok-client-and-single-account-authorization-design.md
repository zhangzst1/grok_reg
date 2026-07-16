# Grok 客户端 0.2.101 与单账号文件授权设计

## 目标

- 将 CPA 请求使用的 Grok Shell 客户端标识从 `0.2.93` 升级到 `0.2.101`。
- 保证 `x-grok-client-version` 与 `User-Agent` 中的版本一致。
- 复用现有回填脚本，对只包含一个账号的文件执行独立 OIDC 授权。
- 在 README 中补充可直接执行的 PowerShell 命令。

## 范围

本次只修改客户端请求头版本、相应回归测试和 README 使用说明。不修改 OAuth client ID、scope、token endpoint、CPA base URL、账号文件格式或授权流程。

## 客户端版本

`cpa_xai/schema.py` 中的默认请求头调整为：

- `x-grok-client-version: 0.2.101`
- `User-Agent: grok-shell/0.2.101 (linux; x86_64)`

其他 Grok 请求头保持不变。`probe_models`、`probe_mini_response` 和导出的 CPA JSON 继续复用 `DEFAULT_CLIENT_HEADERS`，因此会统一获得新版本号。

## 单账号文件授权

继续使用 `scripts/backfill_cpa_xai_from_accounts.py`，不新增重复脚本或参数。单账号文件沿用现有格式：

```text
邮箱----密码----sso
```

`sso` 可省略，文件也可以只包含：

```text
邮箱----密码
```

推荐命令：

```powershell
uv run python -u scripts/backfill_cpa_xai_from_accounts.py `
  --accounts "D:\path\single_account.txt" `
  --limit 1 `
  --no-skip-existing `
  --probe
```

- `--accounts` 指定单账号文件。
- `--limit 1` 防止文件意外包含多条有效记录时批量执行。
- `--no-skip-existing` 允许已存在同邮箱 CPA 文件时重新授权并覆盖输出。
- `--probe` 在写出后调用 `/v1/models` 验证访问权限。
- 代理、输出目录和热加载目录继续读取现有配置，也可通过脚本已有参数覆盖。

## 错误处理

保持现有授权脚本行为：解析不到有效账号时不进行授权；OAuth 或探测失败时输出错误并写入失败日志。升级客户端版本不改变 `403 Access denied` 的处理逻辑，也不承诺能够绕过账号 entitlement 或服务端风控。

## 测试

新增针对 `DEFAULT_CLIENT_HEADERS` 的单元测试，验证：

1. `x-grok-client-version` 等于 `0.2.101`。
2. `User-Agent` 使用 `grok-shell/0.2.101`。

实现时先运行新增测试并确认它因旧版本 `0.2.93` 失败，再修改生产代码使其通过。完成后运行完整 unittest 套件和 `mise run check`。

## 非目标

- 不新增单账号专用脚本。
- 不更改或绕过服务端风控。
- 不自动读取、打印或提交账号密码、SSO、access token 和 refresh token。
