from __future__ import annotations

import threading
import unittest
import queue
from unittest import mock

import requests


class BrowserEnvConfigurationTests(unittest.TestCase):
    def test_parse_env_ids_preserves_order(self) -> None:
        from cli_browser_env import parse_browser_env_ids

        self.assertEqual(parse_browser_env_ids([900, "901"]), [900, 901])

    def test_parse_env_ids_rejects_invalid_values(self) -> None:
        from cli_browser_env import parse_browser_env_ids

        for value in ([], [900, 900], ["bad"], [True], "900,901"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_browser_env_ids(value)


class BrowserEnvApiClientTests(unittest.TestCase):
    def make_client(self, session: mock.Mock):
        from cli_browser_env import BrowserEnvApiClient

        return BrowserEnvApiClient(
            base_url="http://127.0.0.1:50326/",
            token="secret",
            env_ids=[900, 901],
            start_wait_seconds=0,
            timeout=30,
            session=session,
        )

    def test_start_attaches_to_debug_port_and_stop_uses_same_env(self) -> None:
        session = mock.Mock()
        cookie_response = mock.Mock()
        start_response = mock.Mock()
        start_response.json.return_value = {"data": {"port": 43210}}
        stop_response = mock.Mock()
        session.post.side_effect = [cookie_response, start_response, stop_response]
        chromium = object()
        client = self.make_client(session)
        client.bind_worker(900)

        with (
            mock.patch("cli_browser_env.time.sleep") as sleep,
            mock.patch("cli_browser_env.ChromiumOptions") as options,
            mock.patch("cli_browser_env.Chromium", return_value=chromium) as chromium_cls,
        ):
            options.return_value.set_local_port.return_value = options.return_value
            browser = client.start_browser()
            client.stop_browser(browser)

        self.assertIs(browser, chromium)
        sleep.assert_not_called()
        options.return_value.set_local_port.assert_called_once_with(43210)
        options.return_value.existing_only.assert_called_once_with(True)
        chromium_cls.assert_called_once_with(options.return_value)
        session.post.assert_has_calls(
            [
                mock.call(
                    "http://127.0.0.1:50326/api/browser/cookie/update",
                    json={"envId": 900, "cookie": None},
                    headers={
                        "Authorization": "Bearer secret",
                        "Content-Type": "application/json",
                    },
                    timeout=30,
                ),
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
        cookie_response.raise_for_status.assert_called_once_with()
        start_response.raise_for_status.assert_called_once_with()
        stop_response.raise_for_status.assert_called_once_with()

    def test_same_env_cannot_start_twice(self) -> None:
        session = mock.Mock()
        response = mock.Mock()
        response.json.return_value = {"data": {"port": 43210}}
        session.post.return_value = response
        client = self.make_client(session)
        browsers: list[object] = []
        errors: list[Exception] = []

        def worker() -> None:
            client.bind_worker(900)
            try:
                browsers.append(client.start_browser())
            except Exception as exc:  # noqa: BLE001 - assertion captures the failure
                errors.append(exc)

        with (
            mock.patch("cli_browser_env.ChromiumOptions") as options,
            mock.patch("cli_browser_env.Chromium", return_value=object()),
        ):
            options.return_value.set_local_port.return_value = options.return_value
            first = threading.Thread(target=worker)
            second = threading.Thread(target=worker)
            first.start()
            first.join(timeout=2)
            second.start()
            second.join(timeout=2)

        self.assertEqual(len(browsers), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("already active", str(errors[0]))

    def test_invalid_start_response_releases_reservation(self) -> None:
        session = mock.Mock()
        first_cookie_response = mock.Mock()
        bad_response = mock.Mock()
        bad_response.json.return_value = {"data": {}}
        stop_response = mock.Mock()
        second_cookie_response = mock.Mock()
        good_response = mock.Mock()
        good_response.json.return_value = {"data": {"port": 43210}}
        session.post.side_effect = [
            first_cookie_response,
            bad_response,
            stop_response,
            second_cookie_response,
            good_response,
        ]
        client = self.make_client(session)
        client.bind_worker(900)

        with self.assertRaisesRegex(RuntimeError, "debug port"):
            client.start_browser()

        with (
            mock.patch("cli_browser_env.ChromiumOptions") as options,
            mock.patch("cli_browser_env.Chromium", return_value=object()),
        ):
            options.return_value.set_local_port.return_value = options.return_value
            client.start_browser()

    def test_cookie_update_failure_does_not_start_and_releases_reservation(self) -> None:
        session = mock.Mock()
        cookie_response = mock.Mock()
        start_response = mock.Mock()
        start_response.json.return_value = {"data": {"port": 43210}}
        session.post.side_effect = [
            requests.HTTPError("cookie update failed"),
            cookie_response,
            start_response,
        ]
        client = self.make_client(session)
        client.bind_worker(900)

        with self.assertRaisesRegex(RuntimeError, "cookie update failed"):
            client.start_browser()

        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(
            session.post.call_args.args[0],
            "http://127.0.0.1:50326/api/browser/cookie/update",
        )

        with (
            mock.patch("cli_browser_env.ChromiumOptions") as options,
            mock.patch("cli_browser_env.Chromium", return_value=object()),
        ):
            options.return_value.set_local_port.return_value = options.return_value
            client.start_browser()

        self.assertEqual(
            [call.args[0] for call in session.post.call_args_list],
            [
                "http://127.0.0.1:50326/api/browser/cookie/update",
                "http://127.0.0.1:50326/api/browser/cookie/update",
                "http://127.0.0.1:50326/api/browser/start",
            ],
        )


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

    def test_default_factory_is_unchanged_when_hooks_are_reset(self) -> None:
        from tab_pool import TabPool

        browser = mock.Mock()
        browser.tab_ids = ["tab-1"]
        browser.get_tab.return_value = object()
        options = object()
        TabPool.init(lambda: options)
        TabPool.configure_browser_lifecycle(None, None)

        with mock.patch("DrissionPage.Chromium", return_value=browser) as chromium:
            TabPool.get_tab()
            TabPool.release_tab()

        chromium.assert_called_once_with(options)
        browser.quit.assert_called_once_with(del_data=True)


class CliBrowserEnvironmentTests(unittest.TestCase):
    def test_threads_are_capped_by_env_count(self) -> None:
        import register_cli as cli

        with mock.patch.dict("os.environ", {}, clear=True):
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
        self.assertEqual(client.token, "secret")

    def test_environment_token_overrides_config(self) -> None:
        import register_cli as cli

        with mock.patch.dict(
            "os.environ", {"BROWSER_API_TOKEN": "from-env"}, clear=True
        ):
            client, _, _ = cli.resolve_cli_browser_env(
                {
                    "browser_api_base": "http://127.0.0.1:50326",
                    "browser_api_token": "from-config",
                    "browser_env_ids": [900],
                },
                requested_threads=1,
            )

        self.assertEqual(client.token, "from-env")

    def test_missing_token_is_rejected(self) -> None:
        import register_cli as cli

        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "token"):
                cli.resolve_cli_browser_env(
                    {
                        "browser_api_base": "http://127.0.0.1:50326",
                        "browser_api_token": "",
                        "browser_env_ids": [900],
                    },
                    requested_threads=1,
                )

    def test_register_worker_binds_assigned_env_before_reading_tasks(self) -> None:
        import register_cli as cli

        client = mock.Mock()
        cli._register_worker(
            1,
            queue.Queue(),
            0,
            "accounts_cli.txt",
            None,
            False,
            False,
            browser_client=client,
            env_id=901,
        )

        client.bind_worker.assert_called_once_with(901)


if __name__ == "__main__":
    unittest.main()
