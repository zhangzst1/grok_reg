"""Generate random Hotmail/Outlook aliases from existing credentials."""

from __future__ import annotations

import argparse
import secrets
import string
from collections.abc import Iterable, Sequence
from pathlib import Path


DEFAULT_COUNT_PER_EMAIL = 4
DEFAULT_SUFFIX_LENGTH = 8
RANDOM_ALPHABET = string.ascii_lowercase + string.digits
Credential = tuple[str, str, str, str]


def load_credentials(path: Path) -> list[Credential]:
    """Read unique Hotmail credentials as email, password, client ID, token."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"凭据文件不存在: {path}")

    credentials: list[Credential] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            parts = raw.rstrip("\r\n").split("----", 3)
            if len(parts) < 4:
                continue
            email = parts[0].strip()
            if "@" not in email:
                continue
            password = parts[1].strip()
            client_id = parts[2].strip()
            refresh_token = parts[3].strip()
            local, domain = email.rsplit("@", 1)
            if not local or not domain or not client_id or not refresh_token:
                continue
            key = email.lower()
            if key in seen:
                continue
            seen.add(key)
            credentials.append((email, password, client_id, refresh_token))

    if not credentials:
        raise ValueError(f"凭据文件中没有有效邮箱: {path}")
    return credentials


def load_main_emails(path: Path) -> list[str]:
    """Read unique main mailbox addresses from a credentials text file."""
    return [email for email, _, _, _ in load_credentials(path)]


def generate_aliases(
    main_emails: Iterable[str],
    *,
    count_per_email: int = DEFAULT_COUNT_PER_EMAIL,
    suffix_length: int = DEFAULT_SUFFIX_LENGTH,
) -> list[str]:
    """Generate unique random aliases round by round across main mailboxes."""
    if count_per_email <= 0:
        raise ValueError("每个主邮箱的生成数量必须大于 0")
    if suffix_length <= 0:
        raise ValueError("随机后缀长度必须大于 0")

    mailboxes: list[tuple[str, str, str, int]] = []
    for raw_email in main_emails:
        email = str(raw_email or "").strip()
        if "@" not in email:
            raise ValueError(f"无效邮箱地址: {email}")
        local, domain = email.rsplit("@", 1)
        if not local or not domain:
            raise ValueError(f"无效邮箱地址: {email}")

        max_suffix_length = max(1, 64 - len(local) - 1)
        actual_length = min(suffix_length, max_suffix_length)
        mailboxes.append((email, local, domain, actual_length))

    aliases: list[str] = []
    generated: set[str] = set()
    for _ in range(count_per_email):
        for email, local, domain, actual_length in mailboxes:
            attempts = 0
            max_attempts = max(100, count_per_email * 20)
            while True:
                attempts += 1
                if attempts > max_attempts:
                    raise RuntimeError(f"无法为 {email} 生成足够的唯一随机邮箱")
                suffix = "".join(
                    secrets.choice(RANDOM_ALPHABET) for _ in range(actual_length)
                )
                alias = f"{local}+{suffix}@{domain}"
                alias_key = alias.lower()
                if alias_key in generated:
                    continue
                generated.add(alias_key)
                aliases.append(alias)
                break

    if not aliases:
        raise ValueError("没有可生成 alias 的主邮箱")
    return aliases


def format_credential_lines(
    aliases: Iterable[str], credentials: Sequence[Credential]
) -> list[str]:
    """Attach each round-robin alias to its source mailbox credentials."""
    if not credentials:
        raise ValueError("没有可关联的邮箱凭据")
    lines: list[str] = []
    for index, alias in enumerate(aliases):
        _, password, client_id, refresh_token = credentials[index % len(credentials)]
        lines.append(
            f"{str(alias).strip()}----{password}----{client_id}----{refresh_token}"
        )
    if not lines:
        raise ValueError("没有可写入的邮箱凭据")
    return lines


def write_aliases(path: Path, aliases: Iterable[str]) -> None:
    """Write generated credential lines to a requested .txt file."""
    path = Path(path)
    if path.suffix.lower() != ".txt":
        raise ValueError("输出文件必须使用 .txt 扩展名")
    values = [str(alias).strip() for alias in aliases if str(alias).strip()]
    if not values:
        raise ValueError("没有可写入的邮箱")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(values) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "从 mail_credentials.txt 读取主邮箱并生成随机 Hotmail alias，"
            "输出为 邮箱----password----clientId----refresh_token。"
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("mail_credentials.txt"),
        help="凭据文件路径，默认: mail_credentials.txt",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="输出四段凭据格式的 .txt 文件路径",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT_PER_EMAIL,
        help=f"每个主邮箱生成数量，默认: {DEFAULT_COUNT_PER_EMAIL}",
    )
    parser.add_argument(
        "--length",
        type=int,
        default=DEFAULT_SUFFIX_LENGTH,
        help=f"随机后缀长度，默认: {DEFAULT_SUFFIX_LENGTH}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        credentials = load_credentials(args.input)
        emails = [email for email, _, _, _ in credentials]
        aliases = generate_aliases(
            emails,
            count_per_email=args.count,
            suffix_length=args.length,
        )
        lines = format_credential_lines(aliases, credentials)
        write_aliases(args.output, lines)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(
        f"已从 {len(emails)} 个主邮箱生成 {len(aliases)} 个随机邮箱，保存到: {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
