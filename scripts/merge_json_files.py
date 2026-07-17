"""Merge JSON files in the current directory into a JSON Lines file."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def merge_json_files(directory: Path, output: Path) -> int:
    """Merge non-recursive JSON files from *directory* into *output*."""
    directory = directory.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    json_files = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".json"
            and path.resolve() != output
        ),
        key=lambda path: (path.name.casefold(), path.name),
    )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

            for json_file in json_files:
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8-sig"))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"{json_file.name} 不是有效的 JSON：{exc.msg} "
                        f"（第 {exc.lineno} 行，第 {exc.colno} 列）"
                    ) from exc

                json.dump(
                    data,
                    temporary_file,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                temporary_file.write("\n")

        os.replace(temporary_path, output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return len(json_files)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="把当前目录下的所有 JSON 文件合并为 JSON Lines 文件。"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("merged.jsonl"),
        help="输出文件路径（默认：merged.jsonl）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the JSON merge command."""
    args = build_parser().parse_args(argv)
    directory = Path.cwd()
    output = args.output if args.output.is_absolute() else directory / args.output

    try:
        merged_count = merge_json_files(directory, output)
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    print(f"已合并 {merged_count} 个 JSON 文件到：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
