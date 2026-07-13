# Repository Guidelines

## Project Structure & Module Organization

The main application entry points live at the repository root: `register_cli.py` runs batch registration, while `grok_register_ttk.py` provides the desktop GUI. Shared CPA/OIDC logic is organized under `cpa_xai/`; general helpers belong in `utils/`. Operational scripts are kept in `scripts/`, the Chromium extension is in `turnstilePatch/`, and automated tests live in `tests/`. Configuration templates (`config.example.json`, `.env.example`, and `mail_credentials.example.txt`) document local setup. Design notes and implementation plans are stored under `docs/superpowers/`.

## Build, Test, and Development Commands

- `uv sync` installs the locked Python 3.13 dependencies into the project environment.
- `uv run python -u register_cli.py --count 1` runs one CLI registration flow.
- `uv run python grok_register_ttk.py` launches the GUI; a desktop session and Chromium are required.
- `uv run python -m unittest discover -s tests -v` runs the full test suite.
- `mise run check` compiles the principal Python modules to catch syntax errors.
- `mise run mail-debug` starts the mailbox troubleshooting utility.

Run `mise install` first if using the optional `mise` tasks defined in `mise.toml`.

## Coding Style & Naming Conventions

Use four-space indentation, UTF-8 files, and standard Python conventions: `snake_case` for functions and modules, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Add type hints to new public functions and concise docstrings where behavior is not obvious. Keep provider-specific or CPA-specific code in its existing package instead of expanding the large GUI module. No formatter or linter is currently configured, so follow nearby code and keep imports grouped as standard library, third-party, then local.

## Testing Guidelines

Tests use Python's built-in `unittest` framework and follow `tests/test_*.py`, `*Tests`, and `test_*` naming. Prefer mocks for browser, email, proxy, and network interactions; tests must not require live credentials or external services. Add regression coverage for bug fixes and run both the unittest command and `mise run check` before submitting.

## Commit & Pull Request Guidelines

The history currently contains only an initialization commit, so no established message convention exists. Use short, imperative subjects such as `Add CPA token retry coverage`, and keep unrelated changes separate. Pull requests should explain the behavior change, list verification commands, call out configuration or credential-format changes, and include screenshots for GUI updates. Link the relevant issue when one exists.

## Security & Configuration Tips

Never commit `config.json`, `.env`, `mail_credentials.txt`, generated account ledgers, cookies, logs, screenshots, or `cpa_auths/`. Start from the checked-in example files, redact tokens from diagnostics, and verify that new runtime artifacts are covered by `.gitignore`.
