# Hotmail API Timeout and Mail Retry Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Hotmail API wait time within the service's 1–120 second contract and make CLI/GUI consistently treat `mail_retry_count=0` as one mailbox attempt with no mailbox replacement.

**Architecture:** Add one pure configuration parser in `grok_register_ttk.py` and reuse it from both front ends. Clamp timeout only inside the Hotmail `api` branch, preserving manual, IMAP, other providers, and the fetcher's independent HTTP retry policy. Lock behavior with focused unit and source-wiring tests before changing production code.

**Tech Stack:** Python 3.13, `unittest`, `unittest.mock`, Tkinter, JSON, Markdown

---

## File map

- `tests/test_hotmail_manual_code.py`: Specify API timeout clamping, retry-count parsing, and CLI/GUI wiring.
- `grok_register_ttk.py`: Implement the shared attempt-count parser, API timeout clamp, and GUI usage.
- `register_cli.py`: Replace the zero-breaking local parser with the shared helper.
- `config.example.json`: Clarify timeout and mailbox-attempt semantics.
- `README.md`: Explain how to disable mailbox replacement without disabling HTTP retries.

### Task 1: Add failing tests for timeout and retry semantics

**Files:**
- Modify: `tests/test_hotmail_manual_code.py`
- Test: `tests/test_hotmail_manual_code.py`

- [ ] **Step 1: Add an API upper-bound timeout test**

Add this method to `ManualVerificationCodeTests`:

```python
def test_api_mode_caps_timeout_at_service_maximum(self) -> None:
    reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "api"})
    with mock.patch("utils.verification_code.VerificationCodeFetcher") as fetcher:
        fetcher.return_value.fetch_code.return_value = "123456"
        code = reg.get_oai_code(
            "dev-token",
            "user@hotmail.com",
            timeout=150,
        )

    self.assertEqual(code, "123456")
    fetcher.return_value.fetch_code.assert_called_once_with(
        "user@hotmail.com",
        timeout_seconds=120,
    )
```

- [ ] **Step 2: Add retry-count parsing tests**

Add this class near the existing configuration tests:

```python
class MailRetryConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = dict(reg.config)

    def tearDown(self) -> None:
        reg.config.clear()
        reg.config.update(self.original_config)

    def test_zero_and_one_disable_mailbox_replacement(self) -> None:
        for value in (0, 1, -1):
            with self.subTest(value=value):
                reg.config["mail_retry_count"] = value
                self.assertEqual(reg.get_mail_attempt_count(), 1)

    def test_positive_value_is_total_mailbox_attempts(self) -> None:
        reg.config["mail_retry_count"] = 2
        self.assertEqual(reg.get_mail_attempt_count(), 2)

    def test_missing_empty_and_invalid_values_use_default(self) -> None:
        for value in (None, "", "invalid"):
            with self.subTest(value=value):
                if value is None:
                    reg.config.pop("mail_retry_count", None)
                else:
                    reg.config["mail_retry_count"] = value
                self.assertEqual(reg.get_mail_attempt_count(), 3)
```

- [ ] **Step 3: Add CLI and GUI wiring tests without starting browsers or Tk**

Add these methods to `HotmailApiConfigurationTests`:

```python
def test_cli_uses_shared_mail_attempt_parser(self) -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    self.assertIn("max_mail_retry = reg.get_mail_attempt_count()", source)

def test_gui_uses_shared_mail_attempt_parser(self) -> None:
    source = Path(reg.__file__).read_text(encoding="utf-8")
    self.assertIn("max_mail_retry = get_mail_attempt_count()", source)
```

- [ ] **Step 4: Run focused tests and verify RED**

Run:

```powershell
uv run python -m unittest tests.test_hotmail_manual_code.ManualVerificationCodeTests tests.test_hotmail_manual_code.MailRetryConfigurationTests tests.test_hotmail_manual_code.HotmailApiConfigurationTests -v
```

Expected: timeout test fails because 150 is forwarded unchanged; retry parser tests error because `get_mail_attempt_count` is missing; source-wiring tests fail because CLI uses `or 3` and GUI hardcodes 3.

### Task 2: Implement the shared parser and API timeout clamp

**Files:**
- Modify: `grok_register_ttk.py:1827`
- Modify: `grok_register_ttk.py:1915`
- Test: `tests/test_hotmail_manual_code.py`

- [ ] **Step 1: Add the shared attempt-count parser**

Add this function near the existing common email helpers:

```python
def get_mail_attempt_count(default=3):
    """Return total mailbox attempts; zero/negative values mean one attempt."""
    raw = config.get("mail_retry_count", default)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default
```

- [ ] **Step 2: Clamp timeout only in the Hotmail API branch**

Change the fetcher call to:

```python
api_timeout = max(1, min(int(timeout), 120))
code = VerificationCodeFetcher().fetch_code(
    email,
    timeout_seconds=api_timeout,
)
```

Do not change IMAP or other provider timeout arguments.

- [ ] **Step 3: Run core tests and verify partial GREEN**

Run:

```powershell
uv run python -m unittest tests.test_hotmail_manual_code.ManualVerificationCodeTests tests.test_hotmail_manual_code.MailRetryConfigurationTests -v
```

Expected: all API timeout and parser tests pass; CLI/GUI source-wiring tests remain RED until Task 3.

### Task 3: Wire CLI and GUI to the shared attempt count

**Files:**
- Modify: `register_cli.py:242`
- Modify: `grok_register_ttk.py:4037`
- Test: `tests/test_hotmail_manual_code.py`

- [ ] **Step 1: Replace the CLI parser**

Replace the CLI `try/except` block that contains `config.get(... ) or 3` with:

```python
max_mail_retry = reg.get_mail_attempt_count()
```

- [ ] **Step 2: Replace the GUI hardcoded value**

Change:

```python
max_mail_retry = 3
```

to:

```python
max_mail_retry = get_mail_attempt_count()
```

- [ ] **Step 3: Run all focused tests and verify GREEN**

Run:

```powershell
uv run python -m unittest tests.test_hotmail_manual_code -v
```

Expected: all Hotmail, configuration, CLI, and GUI tests pass.

### Task 4: Clarify configuration documentation

**Files:**
- Modify: `config.example.json:84-89`
- Modify: `README.md:80-86`

- [ ] **Step 1: Update example configuration comments**

Use these descriptions:

```json
"// mail_timeout": "收验证码总超时（秒）；Hotmail API 模式实际传给外部接口的值会限制在 1-120 秒。",
"// mail_retry_count": "邮箱阶段最大尝试次数；0 或 1 表示只尝试当前邮箱、不换邮箱，2 表示最多尝试两个邮箱。",
```

Keep the existing numeric example values unless changing them is necessary for valid JSON.

- [ ] **Step 2: Add README configuration guidance**

Add these bullets near the Hotmail mode descriptions:

```markdown
- `mail_retry_count=0` 或 `1`：邮箱阶段只尝试一次，验证码失败后不更换邮箱；`2` 表示最多尝试两个邮箱
- `mail_retry_count` 不控制 `VerificationCodeFetcher` 内部的 HTTP 临时错误重试；该工具仍按自身配置重试网络错误、429 和 5xx
- `mail_timeout` 在 Hotmail API 模式会自动限制到外部接口允许的 `1–120` 秒
```

- [ ] **Step 3: Validate JSON and documentation text**

Run:

```powershell
uv run python -m json.tool config.example.json > $null
rg -n "mail_retry_count|mail_timeout|1–120|HTTP 临时错误重试" README.md config.example.json
```

Expected: JSON exits 0; output explains no mailbox replacement at 0/1, API timeout limit, and independent HTTP retries.

### Task 5: Full verification

**Files:**
- Verify: `grok_register_ttk.py`
- Verify: `register_cli.py`
- Verify: `tests/test_hotmail_manual_code.py`
- Verify: `config.example.json`
- Verify: `README.md`

- [ ] **Step 1: Run all unit tests**

Run:

```powershell
uv run python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Compile changed Python files**

Run:

```powershell
uv run python -m py_compile grok_register_ttk.py register_cli.py tests/test_hotmail_manual_code.py
```

Expected: exit code 0 and no output.

- [ ] **Step 3: Validate the lock file remains unchanged and valid**

Run:

```powershell
uv lock --check
```

Expected: exit code 0; no dependency changes are required.

- [ ] **Step 4: Run project checks and classify unrelated failures**

Run:

```powershell
uv run python optimization_checks.py
```

Expected baseline: 9/12 with existing failures `proxy-local proxy`, `gc-tab-restart`, and `error-isolation`. Any additional failure is a regression and must be investigated.

- [ ] **Step 5: Confirm retry layers remain separate**

Use read-only inspection to confirm:

- CLI and GUI both call `get_mail_attempt_count()`.
- `VerificationCodeFetcher.DEFAULT_MAX_RETRIES` remains 3.
- API timeout is clamped only in the API branch.
- `config.json` is not modified; the user's current local settings remain intact.

This workspace has no Git metadata, so commit and branch steps are unavailable. Record that limitation instead of attempting Git operations.
