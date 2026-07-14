"""CLI-only browser environment API integration."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import requests
from DrissionPage import Chromium, ChromiumOptions


LogFn = Callable[[str], None]


def parse_browser_env_ids(raw: object) -> list[int]:
    """Validate and normalize the ordered CLI browser environment IDs."""
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


class BrowserEnvApiClient:
    """Start, attach to, and stop browser environments for CLI workers."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        env_ids: list[int],
        start_wait_seconds: float = 3,
        timeout: float = 30,
        session: Any = None,
        log_callback: LogFn | None = None,
    ) -> None:
        base_url = str(base_url or "").strip().rstrip("/")
        token = str(token or "").strip()
        if not base_url:
            raise ValueError("browser_api_base is required")
        if not token:
            raise ValueError("browser API token is required")

        self.base_url = base_url
        self.token = token
        self.env_ids = parse_browser_env_ids(env_ids)
        self.start_wait_seconds = max(0.0, float(start_wait_seconds))
        self.timeout = max(0.1, float(timeout))
        self.session = session or requests
        self.log_callback = log_callback
        self._lock = threading.RLock()
        self._thread_local = threading.local()
        self._active_env_ids: set[int] = set()
        self._browser_env_ids: dict[int, int] = {}

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def bind_worker(self, env_id: int) -> None:
        """Bind the current worker thread to one configured environment."""
        normalized = int(env_id)
        if normalized not in self.env_ids:
            raise ValueError(f"browser env_id is not configured: {normalized}")
        self._thread_local.env_id = normalized

    def bound_env_id(self) -> int:
        env_id = getattr(self._thread_local, "env_id", None)
        if env_id is None:
            raise RuntimeError("browser worker has no bound env_id")
        return int(env_id)

    def _log(self, message: str) -> None:
        if self.log_callback:
            self.log_callback(message)

    def _post(self, action: str, env_id: int):
        response = self.session.post(
            f"{self.base_url}/api/browser/{action}",
            json={"envId": env_id},
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    def _update_cookie(self, env_id: int) -> None:
        response = self.session.post(
            f"{self.base_url}/api/browser/cookie/update",
            json={"envId": env_id, "cookie": None},
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        self._log(f"[*] browser env cookies cleared: env_id={env_id}")

    def _stop_env(self, env_id: int, *, raise_errors: bool) -> None:
        try:
            self._post("stop", env_id)
            self._log(f"[*] browser env stopped: env_id={env_id}")
        except Exception as exc:
            self._log(f"[!] failed to stop browser env {env_id}: {exc}")
            if raise_errors:
                raise RuntimeError(f"failed to stop browser env {env_id}: {exc}") from exc
        finally:
            with self._lock:
                self._active_env_ids.discard(env_id)

    def start_browser(self):
        """Start the bound environment and attach DrissionPage to its port."""
        env_id = self.bound_env_id()
        with self._lock:
            if env_id in self._active_env_ids:
                raise RuntimeError(f"browser env_id already active: {env_id}")
            self._active_env_ids.add(env_id)

        start_attempted = False
        try:
            self._update_cookie(env_id)
            start_attempted = True
            response = self._post("start", env_id)
            payload = response.json()
            try:
                debug_port = int(payload["data"]["port"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"browser start response missing valid debug port for env_id={env_id}"
                ) from exc
            if not 1 <= debug_port <= 65535:
                raise RuntimeError(
                    f"browser start response has invalid debug port for env_id={env_id}: {debug_port}"
                )

            if self.start_wait_seconds > 0:
                time.sleep(self.start_wait_seconds)
            options = ChromiumOptions()
            options.set_local_port(debug_port)
            options.existing_only(True)
            browser = Chromium(options)
            with self._lock:
                self._browser_env_ids[id(browser)] = env_id
            self._log(
                f"[*] browser env started: env_id={env_id} debug_port={debug_port}"
            )
            return browser
        except Exception as exc:
            if start_attempted:
                self._stop_env(env_id, raise_errors=False)
            else:
                with self._lock:
                    self._active_env_ids.discard(env_id)
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"failed to start browser env {env_id}: {exc}") from exc

    def stop_browser(self, browser: Any) -> None:
        """Stop the environment associated with a previously attached browser."""
        with self._lock:
            env_id = self._browser_env_ids.pop(id(browser), None)
            if env_id is None:
                bound = getattr(self._thread_local, "env_id", None)
                if bound in self._active_env_ids:
                    env_id = int(bound)
        if env_id is None:
            return
        self._stop_env(env_id, raise_errors=True)
