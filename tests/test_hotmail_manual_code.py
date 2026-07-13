from __future__ import annotations

import unittest
import threading
import time
import queue
import runpy
from pathlib import Path
from unittest import mock

import grok_register_ttk as reg
import register_cli as cli


class HotmailApiConfigurationTests(unittest.TestCase):
    def test_gui_exposes_api_code_mode(self) -> None:
        source = Path(reg.__file__).read_text(encoding="utf-8")
        self.assertIn('values=["manual", "imap", "api"]', source)

    def test_verification_code_module_load_does_not_request_mail(self) -> None:
        module_path = Path(reg.__file__).with_name("utils") / "verification_code.py"
        with mock.patch(
            "requests.Session.get",
            side_effect=AssertionError("module load attempted a network request"),
        ) as request_get:
            runpy.run_path(str(module_path), run_name="verification_code_import_test")
        request_get.assert_not_called()

    def test_cli_uses_shared_mail_attempt_parser(self) -> None:
        source = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertIn("max_mail_retry = reg.get_mail_attempt_count()", source)

    def test_gui_uses_shared_mail_attempt_parser(self) -> None:
        source = Path(reg.__file__).read_text(encoding="utf-8")
        self.assertIn("max_mail_retry = get_mail_attempt_count()", source)


class ManualVerificationCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = dict(reg.config)

    def tearDown(self) -> None:
        reg.config.clear()
        reg.config.update(self.original_config)

    def test_normalize_accepts_hyphenated_and_compact_codes(self) -> None:
        self.assertEqual(reg.normalize_manual_verification_code("abc-123"), "ABC-123")
        self.assertEqual(reg.normalize_manual_verification_code(" a1b2c3 "), "A1B2C3")

    def test_normalize_rejects_invalid_codes(self) -> None:
        for value in ("", "ABC-12", "ABC-1234", "ABC 123", "ABC_123", "中文123"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "验证码格式无效"):
                    reg.normalize_manual_verification_code(value)

    def test_manual_mode_uses_callback_without_calling_imap(self) -> None:
        reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "manual"})
        callback = mock.Mock(return_value="abc-123")
        with mock.patch.object(reg, "hotmail_get_oai_code") as imap:
            code = reg.get_oai_code(
                "dev-token",
                "user@hotmail.com",
                manual_code_callback=callback,
            )
        self.assertEqual(code, "ABC-123")
        callback.assert_called_once_with("user@hotmail.com")
        imap.assert_not_called()

    def test_manual_mode_requires_callback(self) -> None:
        reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "manual"})
        with self.assertRaisesRegex(RuntimeError, "缺少输入通道"):
            reg.get_oai_code("dev-token", "user@hotmail.com")

    def test_imap_mode_keeps_existing_hotmail_flow(self) -> None:
        reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "imap"})
        with mock.patch.object(reg, "hotmail_get_oai_code", return_value="XYZ-789") as imap:
            code = reg.get_oai_code("dev-token", "user@hotmail.com")
        self.assertEqual(code, "XYZ-789")
        imap.assert_called_once()

    def test_api_mode_uses_external_fetcher_and_forwards_timeout(self) -> None:
        reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "api"})
        log_callback = mock.Mock()
        with mock.patch("utils.verification_code.VerificationCodeFetcher") as fetcher:
            fetcher.return_value.fetch_code.return_value = "123456"
            code = reg.get_oai_code(
                "dev-token",
                "user@hotmail.com",
                timeout=75,
                log_callback=log_callback,
            )
        self.assertEqual(code, "123456")
        fetcher.assert_called_once_with()
        fetcher.return_value.fetch_code.assert_called_once_with(
            "user@hotmail.com",
            timeout_seconds=75,
        )
        log_callback.assert_called_once_with("[*] Hotmail/Outlook 外部 API 已获取验证码")

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

    def test_api_mode_wraps_fetcher_error(self) -> None:
        reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "api"})
        with mock.patch("utils.verification_code.VerificationCodeFetcher") as fetcher:
            fetcher.return_value.fetch_code.side_effect = RuntimeError(
                "service unavailable"
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "Hotmail API 获取验证码失败：service unavailable",
            ):
                reg.get_oai_code("dev-token", "user@hotmail.com")

    def test_api_mode_checks_cancellation_before_fetching(self) -> None:
        reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "api"})
        with mock.patch("utils.verification_code.VerificationCodeFetcher") as fetcher:
            with self.assertRaises(reg.RegistrationCancelled):
                reg.get_oai_code(
                    "dev-token",
                    "user@hotmail.com",
                    cancel_callback=lambda: True,
                )
        fetcher.assert_not_called()

    def test_unknown_hotmail_mode_is_rejected(self) -> None:
        reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "other"})
        with self.assertRaisesRegex(ValueError, "可选值为 manual、imap 或 api"):
            reg.get_oai_code("dev-token", "user@hotmail.com")

    def test_cancelled_manual_input_is_not_retryable(self) -> None:
        self.assertTrue(reg.should_retry_verification_error("未收到验证码邮件"))
        self.assertFalse(reg.should_retry_verification_error("手动验证码输入已取消"))


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


class CliManualVerificationCodeTests(unittest.TestCase):
    def test_cli_accepts_valid_code(self) -> None:
        with mock.patch("builtins.input", return_value="abc-123"):
            self.assertEqual(
                cli.manual_hotmail_code_input("user@hotmail.com"),
                "ABC-123",
            )

    def test_cli_reprompts_after_invalid_code(self) -> None:
        with mock.patch("builtins.input", side_effect=["bad", "XYZ789"]) as prompt:
            self.assertEqual(
                cli.manual_hotmail_code_input("user@hotmail.com"),
                "XYZ789",
            )
        self.assertEqual(prompt.call_count, 2)

    def test_cli_blank_input_cancels(self) -> None:
        with mock.patch("builtins.input", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "已取消"):
                cli.manual_hotmail_code_input("user@hotmail.com")

    def test_cli_serializes_concurrent_stdin_reads(self) -> None:
        state_lock = threading.Lock()
        active = 0
        max_active = 0
        results: list[str] = []

        def fake_input(_prompt: str) -> str:
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with state_lock:
                active -= 1
            return "ABC123"

        def worker(email: str) -> None:
            results.append(cli.manual_hotmail_code_input(email))

        with mock.patch("builtins.input", side_effect=fake_input):
            threads = [
                threading.Thread(target=worker, args=(f"user{i}@hotmail.com",))
                for i in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)

        self.assertEqual(results, ["ABC123", "ABC123"])
        self.assertEqual(max_active, 1)


class _FakeRoot:
    def __init__(self) -> None:
        self.scheduled = []

    def after(self, _delay: int, callback) -> None:
        self.scheduled.append(callback)


class GuiManualVerificationCodeTests(unittest.TestCase):
    def make_gui(self):
        gui = reg.GrokRegisterGUI.__new__(reg.GrokRegisterGUI)
        gui.root = _FakeRoot()
        gui.manual_code_requests = queue.Queue()
        gui._manual_code_dialog_active = False
        gui.stop_requested = False
        gui.is_running = True
        return gui

    def run_request(self, gui, email="user@hotmail.com"):
        result = {}

        def worker() -> None:
            try:
                result["code"] = gui.request_manual_hotmail_code(email)
            except BaseException as exc:  # noqa: BLE001 - assert exact surfaced error
                result["error"] = exc

        thread = threading.Thread(target=worker)
        thread.start()
        deadline = time.time() + 1
        while gui.manual_code_requests.empty() and time.time() < deadline:
            time.sleep(0.01)
        return result, thread

    def test_gui_returns_code_from_main_thread_dialog(self) -> None:
        gui = self.make_gui()
        result, thread = self.run_request(gui)
        dialog = mock.Mock()
        dialog.askstring.return_value = "abc-123"
        with mock.patch.object(reg, "simpledialog", dialog, create=True):
            gui._process_manual_code_requests()
        thread.join(timeout=1)
        self.assertEqual(result.get("code"), "ABC-123")
        self.assertNotIn("error", result)

    def test_gui_reprompts_after_invalid_code(self) -> None:
        gui = self.make_gui()
        result, thread = self.run_request(gui)
        dialog = mock.Mock()
        dialog.askstring.side_effect = ["bad", "XYZ789"]
        with (
            mock.patch.object(reg, "simpledialog", dialog, create=True),
            mock.patch.object(reg.messagebox, "showerror") as showerror,
        ):
            gui._process_manual_code_requests()
        thread.join(timeout=1)
        self.assertEqual(result.get("code"), "XYZ789")
        self.assertEqual(dialog.askstring.call_count, 2)
        showerror.assert_called_once()

    def test_gui_dialog_cancel_surfaces_clear_error(self) -> None:
        gui = self.make_gui()
        result, thread = self.run_request(gui)
        dialog = mock.Mock()
        dialog.askstring.return_value = None
        with mock.patch.object(reg, "simpledialog", dialog, create=True):
            gui._process_manual_code_requests()
        thread.join(timeout=1)
        self.assertIsInstance(result.get("error"), RuntimeError)
        self.assertIn("已取消", str(result["error"]))

    def test_gui_stop_cancels_waiting_request(self) -> None:
        gui = self.make_gui()
        result, thread = self.run_request(gui)
        gui.stop_requested = True
        thread.join(timeout=1)
        self.assertIsInstance(result.get("error"), reg.RegistrationCancelled)


if __name__ == "__main__":
    unittest.main()
