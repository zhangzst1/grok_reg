from __future__ import annotations

import unittest
import threading
import runpy
from pathlib import Path
from unittest import mock

import requests

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

    def test_cli_manual_mode_has_no_console_prompt(self) -> None:
        source = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertNotIn("manual_hotmail_code_input", source)
        self.assertNotIn("input(", source)

    def test_gui_manual_mode_has_no_tk_code_dialog(self) -> None:
        source = Path(reg.__file__).read_text(encoding="utf-8")
        self.assertNotIn("simpledialog", source)
        self.assertNotIn("request_manual_hotmail_code", source)


class ManualVerificationCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = dict(reg.config)
        reg.config["mail_retry_count"] = 3

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

    def test_manual_mode_is_handled_by_browser_flow(self) -> None:
        reg.config.update({"email_provider": "hotmail", "hotmail_code_mode": "manual"})
        with mock.patch.object(reg, "hotmail_get_oai_code") as imap:
            with self.assertRaisesRegex(RuntimeError, "浏览器验证码页面"):
                reg.get_oai_code("dev-token", "user@hotmail.com")
        imap.assert_not_called()

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

    def assert_api_http_attempts(self, mail_retry_count: int, expected_attempts: int) -> None:
        from utils.verification_code import VerificationCodeFetcher

        reg.config.update(
            {
                "email_provider": "hotmail",
                "hotmail_code_mode": "api",
                "mail_retry_count": mail_retry_count,
            }
        )
        with (
            mock.patch.object(
                VerificationCodeFetcher,
                "_do_get",
                side_effect=requests.exceptions.ConnectionError("temporary failure"),
            ) as request_get,
            mock.patch("utils.verification_code.time.sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Hotmail API 获取验证码失败"):
                reg.get_oai_code("dev-token", "user@hotmail.com")

        self.assertEqual(request_get.call_count, expected_attempts)

    def test_api_mode_disables_http_retries_when_mail_retry_count_is_zero(self) -> None:
        self.assert_api_http_attempts(mail_retry_count=0, expected_attempts=1)

    def test_api_mode_keeps_default_http_retries_when_mail_retry_count_is_one(self) -> None:
        self.assert_api_http_attempts(mail_retry_count=1, expected_attempts=3)

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

    def test_browser_manual_timeout_is_retryable_but_cancellation_is_not(self) -> None:
        self.assertTrue(reg.should_retry_verification_error("未收到验证码邮件"))
        self.assertTrue(
            reg.should_retry_verification_error("等待在浏览器输入 Hotmail 验证码超时")
        )
        self.assertFalse(reg.should_retry_verification_error("验证码输入已取消"))


class HotmailMainMailboxSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = dict(reg.config)
        self.original_reserved = set(reg._hotmail_reserved_aliases)
        self.original_token_map = dict(reg._hotmail_token_map)
        reg.config["email_provider"] = "hotmail"
        reg._hotmail_reserved_aliases.clear()
        reg._hotmail_token_map.clear()

    def tearDown(self) -> None:
        reg.config.clear()
        reg.config.update(self.original_config)
        reg._hotmail_reserved_aliases.clear()
        reg._hotmail_reserved_aliases.update(self.original_reserved)
        reg._hotmail_token_map.clear()
        reg._hotmail_token_map.update(self.original_token_map)

    def test_selects_each_unused_main_mailbox_once(self) -> None:
        accounts = [
            {"email": "first@hotmail.com"},
            {"email": "second@hotmail.com"},
        ]
        with (
            mock.patch.object(reg, "_hotmail_load_accounts", return_value=accounts),
            mock.patch.object(reg, "is_email_used", return_value=False),
            mock.patch.object(reg, "get_rejected_email_domains", return_value=set()),
        ):
            first_email, _ = reg.hotmail_get_email_and_token()
            second_email, _ = reg.hotmail_get_email_and_token()

        self.assertEqual(first_email, "first@hotmail.com")
        self.assertEqual(second_email, "second@hotmail.com")

    def test_concurrent_workers_reserve_distinct_main_mailboxes(self) -> None:
        accounts = [
            {"email": "first@hotmail.com"},
            {"email": "second@hotmail.com"},
        ]

        allocated: list[str] = []
        errors: list[Exception] = []

        def allocate() -> None:
            try:
                allocated.append(reg.hotmail_get_email_and_token()[0])
            except Exception as exc:
                errors.append(exc)

        with (
            mock.patch.object(reg, "_hotmail_load_accounts", return_value=accounts),
            mock.patch.object(reg, "is_email_used", return_value=False),
            mock.patch.object(reg, "get_rejected_email_domains", return_value=set()),
        ):
            threads = [
                threading.Thread(target=allocate)
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(set(allocated), {"first@hotmail.com", "second@hotmail.com"})
        self.assertTrue(all("+" not in email.split("@", 1)[0] for email in allocated))


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


class BrowserManualVerificationCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = dict(reg.config)
        reg.config.update(
            {
                "email_provider": "hotmail",
                "hotmail_code_mode": "manual",
                "mail_timeout": 30,
            }
        )

    def tearDown(self) -> None:
        reg.config.clear()
        reg.config.update(self.original_config)

    def test_wait_reads_code_entered_in_browser(self) -> None:
        page = mock.Mock()
        page.run_js.side_effect = ["waiting:", "code:abc123"]
        log_callback = mock.Mock()
        with mock.patch.object(reg, "human_sleep"):
            code, already_submitted = reg.wait_for_manual_code_in_browser(
                page,
                "user@hotmail.com",
                timeout=10,
                log_callback=log_callback,
            )

        self.assertEqual(code, "ABC123")
        self.assertFalse(already_submitted)
        log_callback.assert_called_once()

    def test_wait_accepts_page_that_already_advanced(self) -> None:
        page = mock.Mock()
        page.run_js.return_value = "submitted:"
        code, already_submitted = reg.wait_for_manual_code_in_browser(
            page,
            "user@hotmail.com",
            timeout=10,
        )
        self.assertIsNone(code)
        self.assertTrue(already_submitted)

    def test_wait_prefers_profile_over_remembered_code(self) -> None:
        """If profile form is already visible, treat code as browser-submitted."""
        page = mock.Mock()
        # Production JS now checks profile before returning a remembered code.
        page.run_js.return_value = "submitted:"
        code, already_submitted = reg.wait_for_manual_code_in_browser(
            page,
            "user@hotmail.com",
            timeout=10,
        )
        self.assertIsNone(code)
        self.assertTrue(already_submitted)

    def test_wait_honors_cancellation(self) -> None:
        page = mock.Mock()
        with self.assertRaises(reg.RegistrationCancelled):
            reg.wait_for_manual_code_in_browser(
                page,
                "user@hotmail.com",
                timeout=10,
                cancel_callback=lambda: True,
            )
        page.run_js.assert_not_called()

    def test_wait_reports_timeout(self) -> None:
        page = mock.Mock()
        with (
            mock.patch.object(reg.time, "time", side_effect=[0, 2]),
            self.assertRaisesRegex(RuntimeError, "浏览器输入.*超时"),
        ):
            reg.wait_for_manual_code_in_browser(
                page,
                "user@hotmail.com",
                timeout=1,
            )
        page.run_js.assert_not_called()

    def test_fill_manual_mode_skips_mail_fetch_and_submits_browser_code(self) -> None:
        page = mock.Mock()
        page.run_js.side_effect = ["filled-aggregate", "clicked"]
        with (
            mock.patch.object(reg, "_get_page", return_value=page),
            mock.patch.object(reg, "check_timeout"),
            mock.patch.object(reg, "dump_state"),
            mock.patch.object(reg, "take_screenshot"),
            mock.patch.object(reg, "human_sleep"),
            mock.patch.object(
                reg,
                "wait_for_manual_code_in_browser",
                return_value=("ABC123", False),
            ) as browser_wait,
            mock.patch.object(reg, "get_oai_code") as mail_fetch,
        ):
            code = reg.fill_code_and_submit("user@hotmail.com", "dev-token")

        self.assertEqual(code, "ABC123")
        browser_wait.assert_called_once()
        mail_fetch.assert_not_called()

    def test_fill_manual_mode_accepts_browser_auto_submit(self) -> None:
        page = mock.Mock()
        with (
            mock.patch.object(reg, "_get_page", return_value=page),
            mock.patch.object(reg, "check_timeout"),
            mock.patch.object(reg, "dump_state"),
            mock.patch.object(reg, "take_screenshot"),
            mock.patch.object(
                reg,
                "wait_for_manual_code_in_browser",
                return_value=(None, True),
            ),
            mock.patch.object(reg, "get_oai_code") as mail_fetch,
        ):
            code = reg.fill_code_and_submit("user@hotmail.com", "dev-token")

        self.assertEqual(code, "已在浏览器提交")
        mail_fetch.assert_not_called()
        page.run_js.assert_not_called()

    def test_fill_manual_mode_skips_re_fill_when_profile_already_visible(self) -> None:
        """Race: code captured while OTP still present, then page advanced."""
        page = mock.Mock()
        page.run_js.return_value = "not-ready"
        log_callback = mock.Mock()
        with (
            mock.patch.object(reg, "_get_page", return_value=page),
            mock.patch.object(reg, "check_timeout"),
            mock.patch.object(reg, "dump_state"),
            mock.patch.object(reg, "take_screenshot"),
            mock.patch.object(reg, "human_sleep"),
            mock.patch.object(
                reg,
                "wait_for_manual_code_in_browser",
                return_value=("ABC123", False),
            ),
            mock.patch.object(
                reg,
                "_page_has_visible_profile_form",
                return_value=True,
            ) as profile_check,
            mock.patch.object(reg, "get_oai_code") as mail_fetch,
        ):
            code = reg.fill_code_and_submit(
                "user@hotmail.com",
                "dev-token",
                log_callback=log_callback,
            )

        self.assertEqual(code, "已在浏览器提交")
        profile_check.assert_called()
        mail_fetch.assert_not_called()
        log_callback.assert_any_call("[*] 验证码已在浏览器中输入并提交")

    def test_fill_non_manual_mode_does_not_short_circuit_on_profile(self) -> None:
        """imap/api re-fill path must not treat profile form as success."""
        reg.config["hotmail_code_mode"] = "imap"
        page = mock.Mock()
        page.run_js.side_effect = ["not-ready", "filled-aggregate", "clicked"]
        with (
            mock.patch.object(reg, "_get_page", return_value=page),
            mock.patch.object(reg, "check_timeout"),
            mock.patch.object(reg, "dump_state"),
            mock.patch.object(reg, "take_screenshot"),
            mock.patch.object(reg, "human_sleep"),
            mock.patch.object(reg, "get_oai_code", return_value="ABC123"),
            mock.patch.object(
                reg,
                "_page_has_visible_profile_form",
            ) as profile_check,
        ):
            code = reg.fill_code_and_submit("user@hotmail.com", "dev-token")

        self.assertEqual(code, "ABC123")
        profile_check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
