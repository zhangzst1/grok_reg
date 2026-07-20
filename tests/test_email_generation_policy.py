from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

import grok_register_ttk as reg


def load_alias_generator() -> ModuleType:
    module_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "generate_hotmail_aliases.py"
    )
    if not module_path.exists():
        raise AssertionError(f"missing alias generator: {module_path}")
    spec = importlib.util.spec_from_file_location("generate_hotmail_aliases", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load alias generator: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeEmailGenerationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = dict(reg.config)
        self.original_reserved = set(reg._hotmail_reserved_aliases)
        self.original_token_map = dict(reg._hotmail_token_map)
        reg._hotmail_reserved_aliases.clear()
        reg._hotmail_token_map.clear()

    def tearDown(self) -> None:
        reg.config.clear()
        reg.config.update(self.original_config)
        reg._hotmail_reserved_aliases.clear()
        reg._hotmail_reserved_aliases.update(self.original_reserved)
        reg._hotmail_token_map.clear()
        reg._hotmail_token_map.update(self.original_token_map)

    def test_generated_email_providers_fail_before_creation(self) -> None:
        providers = ("duckmail", "yyds", "cloudflare", "cloudmail")

        with (
            mock.patch.object(
                reg,
                "pick_domain",
                side_effect=AssertionError("DuckMail creation was called"),
            ) as duckmail_create,
            mock.patch.object(
                reg,
                "yyds_get_email_and_token",
                side_effect=AssertionError("YYDS creation was called"),
            ) as yyds_create,
            mock.patch.object(
                reg,
                "cloudflare_create_temp_address",
                return_value=("generated@example.com", "generated-token"),
            ) as cloudflare_create,
            mock.patch.object(
                reg,
                "generate_username",
                side_effect=AssertionError("random email generation was called"),
            ) as random_generation,
        ):
            for provider in providers:
                with self.subTest(provider=provider):
                    reg.config.update(
                        {
                            "email_provider": provider,
                            "allow_yyds_generation": False,
                            "cloudflare_api_base": "https://mail.invalid",
                            "defaultDomains": "example.com",
                        }
                    )
                    expected = (
                        "allow_yyds_generation"
                        if provider == "yyds"
                        else "邮箱自动生成已禁用"
                    )
                    with self.assertRaisesRegex(RuntimeError, expected):
                        reg.get_email_and_token()

        duckmail_create.assert_not_called()
        yyds_create.assert_not_called()
        cloudflare_create.assert_not_called()
        random_generation.assert_not_called()

    def test_default_provider_uses_an_existing_hotmail_mailbox(self) -> None:
        reg.config.pop("email_provider", None)

        self.assertEqual(reg.get_email_provider(), "hotmail")

    def test_gui_offers_existing_mailboxes_and_opt_in_yyds(self) -> None:
        source = Path(reg.__file__).read_text(encoding="utf-8")

        self.assertIn('values=["hotmail", "outlookmail", "yyds"]', source)
        self.assertIn('text="允许 YYDS 创建临时邮箱"', source)
        self.assertIn('config["allow_yyds_generation"] = bool(', source)
        self.assertIn('config["yyds_api_key"] = self.yyds_api_key_var.get()', source)
        self.assertNotIn(
            'values=["duckmail", "yyds", "cloudflare", "cloudmail", "hotmail", "outlookmail"]',
            source,
        )

    def test_example_config_defaults_to_hotmail(self) -> None:
        config_path = Path(reg.__file__).with_name("config.example.json")
        example = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(example["email_provider"], "hotmail")
        self.assertIs(example["allow_yyds_generation"], False)

    def test_hotmail_returns_an_unused_main_mailbox(self) -> None:
        account = {
            "email": "existing@hotmail.com",
            "password": "password",
            "client_id": "client-id",
            "refresh_token": "refresh-token",
        }
        reg.config["email_provider"] = "hotmail"

        with (
            mock.patch.object(reg, "_hotmail_load_accounts", return_value=[account]),
            mock.patch.object(reg, "is_email_used", return_value=False),
            mock.patch.object(reg, "get_rejected_email_domains", return_value=set()),
            mock.patch.object(
                reg.secrets,
                "choice",
                side_effect=AssertionError("alias generation was called"),
            ) as random_alias,
        ):
            email, token = reg.get_email_and_token()

        self.assertEqual(email, "existing@hotmail.com")
        self.assertEqual(reg._hotmail_token_map[token]["email"], email)
        random_alias.assert_not_called()

    def test_hotmail_does_not_generate_alias_when_main_mailbox_is_used(self) -> None:
        account = {
            "email": "used@hotmail.com",
            "password": "password",
            "client_id": "client-id",
            "refresh_token": "refresh-token",
        }
        reg.config["email_provider"] = "hotmail"

        with (
            mock.patch.object(reg, "_hotmail_load_accounts", return_value=[account]),
            mock.patch.object(reg, "is_email_used", return_value=True),
            mock.patch.object(reg, "get_rejected_email_domains", return_value=set()),
            mock.patch.object(
                reg.secrets,
                "choice",
                side_effect=AssertionError("alias generation was called"),
            ) as random_alias,
        ):
            with self.assertRaisesRegex(RuntimeError, "自动 alias 生成已禁用"):
                reg.get_email_and_token()

        random_alias.assert_not_called()


class YydsCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = dict(reg.config)

    def tearDown(self) -> None:
        reg.config.clear()
        reg.config.update(self.original_config)

    def test_yyds_generation_requires_explicit_opt_in(self) -> None:
        reg.config.update({"email_provider": "yyds", "allow_yyds_generation": False})
        with mock.patch.object(reg, "yyds_get_email_and_token") as create:
            with self.assertRaisesRegex(RuntimeError, "allow_yyds_generation"):
                reg.get_email_and_token()
        create.assert_not_called()

    def test_yyds_opt_in_requires_literal_boolean_true(self) -> None:
        for value in (1, "true", "yes", [], {}):
            with self.subTest(value=value):
                reg.config["allow_yyds_generation"] = value
                self.assertFalse(reg.yyds_generation_allowed())
        reg.config["allow_yyds_generation"] = True
        self.assertTrue(reg.yyds_generation_allowed())

    def test_enabled_yyds_provider_calls_generator(self) -> None:
        reg.config.update({"email_provider": "yyds", "allow_yyds_generation": True})
        with mock.patch.object(
            reg,
            "yyds_get_email_and_token",
            return_value=("temp@example.com", "temp-token"),
        ) as create:
            result = reg.get_email_and_token()

        self.assertEqual(result, ("temp@example.com", "temp-token"))
        create.assert_called_once_with(api_key=None, jwt=None)

    def test_yyds_create_uses_official_local_part_field(self) -> None:
        response = mock.Mock()
        response.json.return_value = {
            "success": True,
            "data": {"address": "prefix@example.com", "token": "temp-token"},
        }
        with mock.patch.object(reg, "http_post", return_value=response) as post:
            result = reg.yyds_create_account(
                local_part="prefix",
                domain="example.com",
                api_key="AC-key",
            )

        self.assertEqual(result["address"], "prefix@example.com")
        post.assert_called_once_with(
            "https://maliapi.215.im/v1/accounts",
            json={"localPart": "prefix", "domain": "example.com"},
            headers={"Content-Type": "application/json", "X-API-Key": "AC-key"},
        )

    def test_yyds_uses_returned_final_address_and_token(self) -> None:
        reg.config.update({"yyds_api_key": "AC-key"})
        with (
            mock.patch.object(reg, "yyds_generate_username", return_value="prefix"),
            mock.patch.object(reg, "yyds_pick_domain", return_value="example.com"),
            mock.patch.object(
                reg,
                "yyds_create_account",
                return_value={"address": "prefix.sub.example.com", "token": "temp-token"},
            ) as create,
            mock.patch("builtins.print"),
        ):
            result = reg.yyds_get_email_and_token()

        self.assertEqual(result, ("prefix.sub.example.com", "temp-token"))
        create.assert_called_once_with(
            local_part="prefix",
            domain="example.com",
            api_key="AC-key",
            jwt="",
        )

    def test_yyds_messages_accept_list_response_payload(self) -> None:
        response = mock.Mock()
        response.json.return_value = {"success": True, "data": [{"id": "message-1"}]}
        with mock.patch.object(reg, "http_get", return_value=response):
            messages = reg.yyds_get_messages("prefix@example.com", token="temp-token")

        self.assertEqual(messages, [{"id": "message-1"}])

    def test_yyds_message_detail_forwards_address_query(self) -> None:
        response = mock.Mock()
        response.json.return_value = {"success": True, "data": {"id": "message-1"}}
        with mock.patch.object(reg, "http_get", return_value=response) as get:
            result = reg.yyds_get_message_detail(
                "message-1",
                token="temp-token",
                address="prefix@example.com",
            )

        self.assertEqual(result, {"id": "message-1"})
        get.assert_called_once_with(
            "https://maliapi.215.im/v1/messages/message-1",
            headers={"Authorization": "Bearer temp-token"},
            params={"address": "prefix@example.com"},
        )

    def test_yyds_uses_verification_code_from_message_list(self) -> None:
        message = {
            "id": "message-1",
            "to": [{"address": "prefix@example.com"}],
            "verificationCode": "384729",
        }
        with (
            mock.patch.object(reg, "yyds_get_messages", return_value=[message]),
            mock.patch.object(
                reg,
                "yyds_get_message_detail",
                side_effect=AssertionError("detail should not be required"),
            ),
        ):
            try:
                code = reg.yyds_get_oai_code(
                    "temp-token",
                    "prefix@example.com",
                    timeout=0.01,
                    poll_interval=0,
                )
            except Exception:
                code = None

        self.assertEqual(code, "384729")

    def test_yyds_token_refresh_uses_current_temp_token(self) -> None:
        response = mock.Mock()
        response.json.return_value = {
            "success": True,
            "data": {"token": "new-temp-token"},
        }
        with mock.patch.object(reg, "http_post", return_value=response) as post:
            try:
                token = reg.yyds_get_token(
                    "prefix@example.com",
                    temp_token="current-temp-token",
                )
            except TypeError:
                token = None

        self.assertEqual(token, "new-temp-token")
        post.assert_called_once_with(
            "https://maliapi.215.im/v1/token",
            json={"address": "prefix@example.com"},
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer current-temp-token",
            },
        )

    def test_yyds_uses_official_server_verification_code(self) -> None:
        message = {
            "id": "message-1",
            "to": [{"address": "prefix@example.com"}],
        }
        detail = {
            "verificationCode": "384729",
            "subject": "Your verification code",
            "text": "",
            "html": [],
        }
        with (
            mock.patch.object(reg, "yyds_get_messages", return_value=[message]),
            mock.patch.object(reg, "yyds_get_message_detail", return_value=detail),
        ):
            try:
                code = reg.yyds_get_oai_code(
                    "temp-token",
                    "prefix@example.com",
                    timeout=0.01,
                    poll_interval=0,
                )
            except Exception:
                code = None

        self.assertEqual(code, "384729")



class HotmailAliasGeneratorTests(unittest.TestCase):
    def test_loads_main_emails_from_credentials_file(self) -> None:
        aliasgen = load_alias_generator()
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "mail_credentials.txt"
            input_path.write_text(
                "# credentials\n"
                "first@hotmail.com----pw1----client1----token1\n"
                "SECOND@outlook.com----pw2----client2----token2\n"
                "first@hotmail.com----duplicate----client3----token3\n",
                encoding="utf-8",
            )

            emails = aliasgen.load_main_emails(input_path)

        self.assertEqual(emails, ["first@hotmail.com", "SECOND@outlook.com"])

    def test_generates_random_aliases_in_round_robin_mailbox_order(self) -> None:
        aliasgen = load_alias_generator()

        aliases = aliasgen.generate_aliases(
            [
                "first@hotmail.com",
                "second@outlook.com",
                "third@hotmail.com",
            ],
            count_per_email=2,
        )

        self.assertEqual(len(aliases), 6)
        self.assertEqual(len(set(aliases)), 6)
        expected_patterns = [
            r"^first\+[a-z0-9]{8}@hotmail\.com$",
            r"^second\+[a-z0-9]{8}@outlook\.com$",
            r"^third\+[a-z0-9]{8}@hotmail\.com$",
            r"^first\+[a-z0-9]{8}@hotmail\.com$",
            r"^second\+[a-z0-9]{8}@outlook\.com$",
            r"^third\+[a-z0-9]{8}@hotmail\.com$",
        ]
        for alias, pattern in zip(aliases, expected_patterns, strict=True):
            self.assertRegex(alias, pattern)

    def test_main_writes_alias_with_matching_source_credentials(self) -> None:
        aliasgen = load_alias_generator()

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "mail_credentials.txt"
            output_path = Path(tmp_dir) / "generated.txt"
            input_path.write_text(
                "first@hotmail.com----pw1----client1----token1\n"
                "second@outlook.com----pw2----client2----token2\n",
                encoding="utf-8",
            )

            with mock.patch("builtins.print"):
                result = aliasgen.main(
                    [
                        "--input",
                        str(input_path),
                        "--output",
                        str(output_path),
                        "--count",
                        "2",
                    ]
                )
            saved = output_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(result, 0)
        self.assertEqual(len(saved), 4)
        expected_credentials = [
            (r"^first\+[a-z0-9]{8}@hotmail\.com$", "pw1", "client1", "token1"),
            (r"^second\+[a-z0-9]{8}@outlook\.com$", "pw2", "client2", "token2"),
            (r"^first\+[a-z0-9]{8}@hotmail\.com$", "pw1", "client1", "token1"),
            (r"^second\+[a-z0-9]{8}@outlook\.com$", "pw2", "client2", "token2"),
        ]
        for line, expected in zip(saved, expected_credentials, strict=True):
            parts = line.split("----", 3)
            self.assertEqual(len(parts), 4)
            username, password, client_id, refresh_token = parts
            pattern, expected_password, expected_client_id, expected_token = expected
            self.assertRegex(username, pattern)
            self.assertEqual(password, expected_password)
            self.assertEqual(client_id, expected_client_id)
            self.assertEqual(refresh_token, expected_token)

    def test_rejects_non_txt_output_path(self) -> None:
        aliasgen = load_alias_generator()
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "generated.csv"
            with self.assertRaisesRegex(ValueError, r"\.txt"):
                aliasgen.write_aliases(output_path, ["first+a1b2c3d4@hotmail.com"])

    def test_cli_defaults_match_current_random_alias_configuration(self) -> None:
        aliasgen = load_alias_generator()
        parser = aliasgen.build_parser()

        args = parser.parse_args(["--output", "generated.txt"])

        self.assertEqual(args.input, Path("mail_credentials.txt"))
        self.assertEqual(args.output, Path("generated.txt"))
        self.assertEqual(args.count, 4)
        self.assertEqual(args.length, 8)

if __name__ == "__main__":
    unittest.main()
