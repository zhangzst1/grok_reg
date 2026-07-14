# CLI Browser Environment API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CLI registration workers start and stop uniquely assigned browser environments through the local env API while leaving GUI and CPA/OIDC browsers unchanged.

**Architecture:** Add a focused `cli_browser_env.py` client that validates configuration, binds one env ID per worker thread, starts the remote environment, and attaches DrissionPage to the returned debugging port. Add optional creation/release hooks to `TabPool`; `register_cli.py` installs those hooks and caps registration concurrency to the configured env ID count.

**Tech Stack:** Python 3.13, `requests`, DrissionPage 4.1, `threading`, built-in `unittest` and `unittest.mock`.

---

### Task 1: Browser environment API client

**Files:**
- Create: `cli_browser_env.py`
- Create: `tests/test_cli_browser_env.py`

- [ ] **Step 1: Write failing configuration and lifecycle tests**

Create tests that specify the public API:

```python
from __future__ import annotations

import threading
import unittest
from unittest import mock

from cli_browser_env import BrowserEnvApiClient, parse_browser_env_ids


class BrowserEnvConfigurationTests(unittest.TestCase):
    def test_parse_env_ids_preserves_order(self) -> None:
        self.assertEqual(parse_browser_env_ids([900, "901"]), [900, 901])

    def test_parse_env_ids_rejects_empty_duplicate_and_invalid_values(self) -> None:
        for value in ([], [900, 900], ["bad"], [True]):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_browser_env_ids(value)


class BrowserEnvApiClientTests(unittest.TestCase):
    def test_start_attaches_to_returned_debug_port_and_stop_uses_same_env(self) -> None:
        session = mock.Mock()
        start_response = mock.Mock()
        start_response.json.return_value = {"data": {"port": 43210}}
        stop_response = mock.Mock()
        session.post.side_effect = [start_response, stop_response]
        chromium = object()

        client = BrowserEnvApiClient(
            base_url="http://127.0.0.1:50326",
            token="secret",
            env_ids=[900],
            start_wait_seconds=0,
            timeout=30,
            session=session,
        )
        client.bind_worker(900)

        with (
            mock.patch("cli_browser_env.ChromiumOptions") as options,
            mock.patch("cli_browser_env.Chromium", return_value=chromium),
        ):
            browser = client.start_browser()
            client.stop_browser(browser)

        self.assertIs(browser, chromium)
        options.return_value.set_local_port.assert_called_once_with(43210)
        session.post.assert_has_calls(
            [
                mock.call(
                    "http://127.0.0.1:50326/api/browser/start",
                    json={"envId": 900},
                    headers={
                        "Authorization": "Bearer secret",
                        "Content-Type": "application/json",
                    },
                    timeout=30,
                ),
                mock.call(
                    "http://127.0.0.1:50326/api/browser/stop",
                    json={"envId": 900},
                    headers={
                        "Authorization": "Bearer secret",
                        "Content-Type": "application/json",
                    },
                    timeout=30,
                ),
            ]
        )

    def test_same_env_cannot_start_twice(self) -> None:
        session = mock.Mock()
        response = mock.Mock()
        response.json.return_value = {"data": {"port": 43210}}
        session.post.return_value = response
        client = BrowserEnvApiClient(
            base_url="http://127.0.0.1:50326",
            token="secret",
            env_ids=[900],
            start_wait_seconds=0,
            timeout=30,
            session=session,
        )

        browsers: list[object] = []
        errors: list[Exception] = []

        def worker() -> None:
            client.bind_worker(900)
            try:
                browsers.append(client.start_browser())
            except Exception as exc:
                errors.append(exc)

        with (
            mock.patch("cli_browser_env.ChromiumOptions"),
            mock.patch("cli_browser_env.Chromium", return_value=object()),
        ):
            first = threading.Thread(target=worker)
            second = threading.Thread(target=worker)
            first.start()
            first.join(timeout=2)
            second.start()
            second.join(timeout=2)

        self.assertEqual(len(browsers), 1)
        self.assertEqual(len(errors), 1)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
uv run python -m unittest tests.test_cli_browser_env -v
```

Expected: import failure because `cli_browser_env.py` does not exist.

- [ ] **Step 3: Implement the client**

Implement `parse_browser_env_ids()` plus `BrowserEnvApiClient` with:

```python
def parse_browser_env_ids(raw: object) -> list[int]:
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError("browser_env_ids must be a non-empty list")
    result: list[int] = []
    for item in raw:
        if isinstance(item, bool):
            raise ValueError("browser_env_ids must contain integers")
        try:
            env_id = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError("browser_env_ids must contain integers") from exc
        if env_id in result:
            raise ValueError(f"duplicate browser env_id: {env_id}")
        result.append(env_id)
    return result
```

The client must reserve the env ID under a lock before POSTing `/start`, validate `data.port`, connect with `ChromiumOptions().set_local_port(port)` and `Chromium(options)`, map the returned browser object to its env ID, and remove the reservation after `/stop`. On start/attach failure it must call `/stop` best-effort and clear the reservation.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
uv run python -m unittest tests.test_cli_browser_env -v
```

Expected: all client tests pass.

### Task 2: Optional TabPool lifecycle hooks

**Files:**
- Modify: `tab_pool.py:23-236`
- Modify: `tests/test_cli_browser_env.py`

- [ ] **Step 1: Write failing TabPool hook tests**

Add tests proving that `TabPool.configure_browser_lifecycle(create, release)` uses the custom callbacks and that resetting both callbacks preserves the existing default path.

```python
class TabPoolLifecycleHookTests(unittest.TestCase):
    def tearDown(self) -> None:
        from tab_pool import TabPool

        TabPool.shutdown()
        TabPool.configure_browser_lifecycle(None, None)

    def test_custom_factory_and_releaser_are_used(self) -> None:
        from tab_pool import TabPool

        browser = mock.Mock()
        browser.tab_ids = ["tab-1"]
        browser.get_tab.return_value = object()
        create = mock.Mock(return_value=browser)
        release = mock.Mock()
        TabPool.init(lambda: object())
        TabPool.configure_browser_lifecycle(create, release)

        TabPool.get_tab()
        TabPool.release_tab()

        create.assert_called_once_with()
        release.assert_called_once_with(browser)
        browser.quit.assert_not_called()
```

- [ ] **Step 2: Run the hook test and verify RED**

Run:

```powershell
uv run python -m unittest tests.test_cli_browser_env.TabPoolLifecycleHookTests -v
```

Expected: failure because `configure_browser_lifecycle` does not exist.

- [ ] **Step 3: Add lifecycle hooks without changing defaults**

Add class attributes `_browser_factory` and `_browser_releaser`, a thread-safe `configure_browser_lifecycle()` method, use the factory in `_create_browser()`, and use the releaser in `release_tab()` and `shutdown()`. When hooks are `None`, retain the existing `Chromium(options)` and `browser.quit()` behavior.

- [ ] **Step 4: Run hook and existing tests**

Run:

```powershell
uv run python -m unittest tests.test_cli_browser_env -v
uv run python -m unittest discover -s tests -v
```

Expected: hook tests and all existing tests pass.

### Task 3: Bind CLI workers to unique environments

**Files:**
- Modify: `register_cli.py:505-669`
- Modify: `config.example.json`
- Modify: `.env.example`
- Modify: `tests/test_cli_browser_env.py`

- [ ] **Step 1: Write failing CLI configuration tests**

Add pure-function tests for a new `resolve_cli_browser_env(config, requested_threads)` helper:

```python
class CliBrowserEnvironmentTests(unittest.TestCase):
    def test_threads_are_capped_by_env_count(self) -> None:
        import register_cli as cli

        client, env_ids, threads = cli.resolve_cli_browser_env(
            {
                "browser_api_base": "http://127.0.0.1:50326",
                "browser_api_token": "secret",
                "browser_env_ids": [900, 901],
                "browser_start_wait_seconds": 0,
                "browser_api_timeout": 30,
            },
            requested_threads=3,
        )
        self.assertEqual(env_ids, [900, 901])
        self.assertEqual(threads, 2)
        self.assertIsNotNone(client)
```

Also test that `BROWSER_API_TOKEN` overrides config and that a missing token raises `ValueError`.

- [ ] **Step 2: Run the CLI tests and verify RED**

Run:

```powershell
uv run python -m unittest tests.test_cli_browser_env.CliBrowserEnvironmentTests -v
```

Expected: failure because `resolve_cli_browser_env` does not exist.

- [ ] **Step 3: Implement CLI binding**

In `main()`:

```python
requested_threads = max(1, min(args.threads, 10))
browser_client, browser_env_ids, threads = resolve_cli_browser_env(
    cfg0,
    requested_threads=requested_threads,
)
reg.TabPool.configure_browser_lifecycle(
    browser_client.start_browser,
    browser_client.stop_browser,
)
```

Pass `browser_client` and `browser_env_ids[wid - 1]` to `_register_worker()`. At worker entry call `browser_client.bind_worker(env_id)` before reading the task queue. Keep the existing task queue, retry and shutdown behavior.

Add the documented config keys to `config.example.json` and `BROWSER_API_TOKEN=` to `.env.example`.

- [ ] **Step 4: Run focused and full verification**

Run:

```powershell
uv run python -m unittest tests.test_cli_browser_env -v
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q register_cli.py grok_register_ttk.py cli_browser_env.py tab_pool.py cpa_xai utils tests
git diff --check
```

Expected: all tests pass, compilation exits zero, and `git diff --check` reports no whitespace errors.

### Task 4: Security and final review

**Files:**
- Review: `cli_browser_env.py`
- Review: `register_cli.py`
- Review: `config.example.json`
- Review: `.env.example`

- [ ] **Step 1: Verify secrets are not committed or logged**

Run:

```powershell
rg -n -S "YOUR_API_KEY|Bearer secret" . --glob '!.git/**' --glob '!docs/superpowers/plans/**'
```

Expected: no real API Token in source or configuration templates.

- [ ] **Step 2: Review the final diff**

Run:

```powershell
git diff -- cli_browser_env.py tab_pool.py register_cli.py config.example.json .env.example tests/test_cli_browser_env.py
```

Expected: only CLI registration browser integration, lifecycle hooks, configuration templates and tests are changed; GUI and CPA/OIDC creation code remains unchanged.
