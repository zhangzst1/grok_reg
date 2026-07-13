# Hotmail External API Verification Code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `hotmail_code_mode=api` so Hotmail/Outlook registrations obtain verification codes through `utils.verification_code.VerificationCodeFetcher` while retaining the existing manual and IMAP modes.

**Architecture:** Keep provider and mode dispatch in `grok_register_ttk.get_oai_code()`. The new branch lazily imports the existing fetcher, checks cancellation before the blocking call, forwards the registration timeout, logs success without secrets, and wraps failures with a mode-specific message. Configuration, GUI choices, dependency metadata, and documentation expose the third mode.

**Tech Stack:** Python 3.13, `unittest`, `unittest.mock`, Tkinter, `requests`, JSON, Markdown

---

## File map

- `tests/test_hotmail_manual_code.py`: Extend the existing Hotmail mode-dispatch tests with API success, timeout, cancellation, and failure cases.
- `grok_register_ttk.py`: Add the `api` branch and expose it in the GUI combobox and validation error.
- `config.example.json`: Document `api` as a supported configuration value.
- `README.md`: Explain how and when to select the external API mode.
- `pyproject.toml`: Declare the `requests` dependency used directly by `utils/verification_code.py`.
- `uv.lock`: Refresh the dependency lock after editing `pyproject.toml`.

### Task 1: Specify API mode behavior with failing tests

**Files:**
- Modify: `tests/test_hotmail_manual_code.py`
- Test: `tests/test_hotmail_manual_code.py`

- [ ] **Step 1: Add a success and timeout-forwarding test**

Add this method to `ManualVerificationCodeTests`:

```python
def test_api_mode_uses_external_fetcher_and_forwards_timeout(self) -> None:
    reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "api"})
    log_callback = mock.Mock()
    with mock.patch("utils.verification_code.VerificationCodeFetcher") as fetcher_type:
        fetcher_type.return_value.fetch_code.return_value = "123456"
        code = reg.get_oai_code(
            "dev-token",
            "user@hotmail.com",
            timeout=75,
            log_callback=log_callback,
        )

    self.assertEqual(code, "123456")
    fetcher_type.assert_called_once_with()
    fetcher_type.return_value.fetch_code.assert_called_once_with(
        "user@hotmail.com",
        timeout_seconds=75,
    )
    log_callback.assert_called_once_with("[*] Hotmail/Outlook 外部 API 已获取验证码")
```

- [ ] **Step 2: Add failure wrapping and cancellation tests**

Add these methods to `ManualVerificationCodeTests`:

```python
def test_api_mode_wraps_fetcher_error(self) -> None:
    reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "api"})
    with mock.patch("utils.verification_code.VerificationCodeFetcher") as fetcher_type:
        fetcher_type.return_value.fetch_code.side_effect = RuntimeError("service unavailable")
        with self.assertRaisesRegex(
            RuntimeError,
            "Hotmail API 获取验证码失败：service unavailable",
        ):
            reg.get_oai_code("dev-token", "user@hotmail.com")

def test_api_mode_checks_cancellation_before_fetching(self) -> None:
    reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "api"})
    with mock.patch("utils.verification_code.VerificationCodeFetcher") as fetcher_type:
        with self.assertRaises(reg.RegistrationCancelled):
            reg.get_oai_code(
                "dev-token",
                "user@hotmail.com",
                cancel_callback=lambda: True,
            )
    fetcher_type.assert_not_called()
```

- [ ] **Step 3: Strengthen the unknown-mode assertion**

Replace the existing unknown-mode assertion with:

```python
def test_unknown_hotmail_mode_is_rejected(self) -> None:
    reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "other"})
    with self.assertRaisesRegex(
        ValueError,
        "可选值为 manual、imap 或 api",
    ):
        reg.get_oai_code("dev-token", "user@hotmail.com")
```

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_hotmail_manual_code.ManualVerificationCodeTests -v
```

Expected: the three new API-mode tests fail because `get_oai_code()` does not support `api`, and the updated unknown-mode test fails because the error lists only `manual` and `imap`.

### Task 2: Implement the core API dispatch

**Files:**
- Modify: `grok_register_ttk.py:1894`
- Test: `tests/test_hotmail_manual_code.py`

- [ ] **Step 1: Add the minimal API branch**

In `get_oai_code()`, keep the existing manual branch, then add the API branch before IMAP validation:

```python
if mode == "api":
    raise_if_cancelled(cancel_callback)
    try:
        from utils.verification_code import VerificationCodeFetcher

        code = VerificationCodeFetcher().fetch_code(
            email,
            timeout_seconds=timeout,
        )
    except Exception as exc:
        raise RuntimeError(f"Hotmail API 获取验证码失败：{exc}") from exc
    if log_callback:
        log_callback("[*] Hotmail/Outlook 外部 API 已获取验证码")
    return code
if mode != "imap":
    raise ValueError(
        f"不支持的 hotmail_code_mode={mode!r}，可选值为 manual、imap 或 api"
    )
```

- [ ] **Step 2: Run the core tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_hotmail_manual_code.ManualVerificationCodeTests -v
```

Expected: all `ManualVerificationCodeTests` pass, including existing manual and IMAP behavior.

- [ ] **Step 3: Run the complete Hotmail test module**

Run:

```powershell
python -m unittest tests.test_hotmail_manual_code -v
```

Expected: all core, CLI, and GUI Hotmail tests pass.

### Task 3: Expose the API mode in configuration and GUI

**Files:**
- Modify: `grok_register_ttk.py:3683`
- Modify: `config.example.json:13`
- Test: `tests/test_hotmail_manual_code.py`

- [ ] **Step 1: Add a failing source-level GUI option test**

Add imports and a test that verifies the readonly option list without starting Tk:

```python
from pathlib import Path


class HotmailApiConfigurationTests(unittest.TestCase):
    def test_gui_combobox_lists_api_mode(self) -> None:
        source = Path(reg.__file__).read_text(encoding="utf-8")
        self.assertIn('values=["manual", "imap", "api"]', source)
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
python -m unittest tests.test_hotmail_manual_code.HotmailApiConfigurationTests -v
```

Expected: FAIL because the combobox currently contains only `manual` and `imap`.

- [ ] **Step 3: Add `api` to the GUI combobox**

Change the combobox values in `grok_register_ttk.py` to:

```python
values=["manual", "imap", "api"],
```

- [ ] **Step 4: Update the example configuration description**

Change the `hotmail_code_mode` comment in `config.example.json` to:

```json
"// hotmail_code_mode": "验证码获取方式：manual=CLI/GUI 手动输入（默认）；imap=使用 Microsoft OAuth2 XOAUTH2 IMAP 自动收码；api=使用 utils/verification_code.py 的外部 API 自动收码。",
```

- [ ] **Step 5: Run the configuration test and verify GREEN**

Run:

```powershell
python -m unittest tests.test_hotmail_manual_code.HotmailApiConfigurationTests -v
```

Expected: PASS.

### Task 4: Declare the direct HTTP dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Add the dependency used by the fetcher**

Add this item to the project dependencies in `pyproject.toml`:

```toml
"requests>=2.31",       # utils/verification_code.py 外部验证码 API
```

- [ ] **Step 2: Refresh the lock file**

Run:

```powershell
uv lock
```

Expected: exit code 0; `uv.lock` records `requests` as a direct project dependency without downgrading existing packages.

- [ ] **Step 3: Verify the dependency imports in the project environment**

Run:

```powershell
uv run python -c "import requests; from utils.verification_code import VerificationCodeFetcher; print(requests.__version__, VerificationCodeFetcher.__name__)"
```

Expected: prints a requests version followed by `VerificationCodeFetcher`.

### Task 5: Document the new mode

**Files:**
- Modify: `README.md:80`
- Modify: `README.md:343`

- [ ] **Step 1: Extend the Hotmail mode explanation**

After the existing manual and IMAP bullets, add:

```markdown
- `hotmail_code_mode=api`：调用 `utils/verification_code.py` 中的外部 API 等待邮件并提取验证码；使用该文件内置的 API Key、超时重试和代理故障直连逻辑
```

- [ ] **Step 2: Add troubleshooting guidance**

Add this row to the troubleshooting table near the existing Hotmail rows:

```markdown
| Hotmail API 模式取码失败 | 设置 `hotmail_code_mode=api`，确认目标邮箱可被外部服务查询；查看“Hotmail API 获取验证码失败”后的原始错误 |
```

- [ ] **Step 3: Verify documentation mentions all modes**

Run:

```powershell
rg -n "hotmail_code_mode=(manual|imap|api)|manual=.*imap=.*api" README.md config.example.json
```

Expected: output contains documentation for `manual`, `imap`, and `api` in both the README and example configuration.

### Task 6: Full verification

**Files:**
- Verify: `grok_register_ttk.py`
- Verify: `register_cli.py`
- Verify: `utils/verification_code.py`
- Verify: `tests/test_hotmail_manual_code.py`

- [ ] **Step 1: Run all unit tests**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass with no failures or errors.

- [ ] **Step 2: Compile changed Python modules**

Run:

```powershell
python -m py_compile grok_register_ttk.py register_cli.py utils/verification_code.py tests/test_hotmail_manual_code.py
```

Expected: exit code 0 and no output.

- [ ] **Step 3: Run project checks**

Run:

```powershell
uv run python optimization_checks.py
```

Expected: all project optimization checks report success. If a pre-existing unrelated check fails, record its exact name and output rather than changing unrelated code.

- [ ] **Step 4: Review the final diff manually**

Because this workspace has no Git metadata, compare the touched files against the design and confirm:

- only Hotmail API-mode behavior, configuration, dependency declaration, tests, and documentation changed;
- no API Key or credential was added outside the already supplied utility file;
- manual, IMAP, and non-Hotmail paths remain unchanged.

