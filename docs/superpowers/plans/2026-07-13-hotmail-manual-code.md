# Hotmail Manual Verification Code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configurable manual Hotmail/Outlook verification-code entry for both CLI and GUI while retaining the existing IMAP mode.

**Architecture:** The registration core accepts an optional manual-code provider callback. Hotmail dispatches by `hotmail_code_mode`; CLI supplies a locked console provider and GUI supplies a Tk-main-thread provider backed by a request queue and threading events. Code validation is centralized so both front ends accept the same formats.

**Tech Stack:** Python 3.13, standard-library `unittest`, `threading`, Tkinter, existing DrissionPage registration flow.

---

### Task 1: Core manual-code validation and Hotmail mode dispatch

**Files:**
- Create: `tests/test_hotmail_manual_code.py`
- Modify: `grok_register_ttk.py`

- [ ] Write failing unit tests for accepted and rejected code formats.
- [ ] Write failing tests showing `manual` mode calls the provided callback and `imap` mode calls the existing IMAP function.
- [ ] Run `python -m unittest tests.test_hotmail_manual_code -v` and confirm failures are caused by the missing API.
- [ ] Add `normalize_manual_verification_code()` and thread an optional `manual_code_callback` through `fill_code_and_submit()` and `get_oai_code()`.
- [ ] Default `hotmail_code_mode` to `manual`; reject unknown modes explicitly.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: Thread-safe CLI input provider

**Files:**
- Modify: `tests/test_hotmail_manual_code.py`
- Modify: `register_cli.py`

- [ ] Write failing tests for valid console input, retry after invalid input, cancellation, and serialized access to `input()`.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Implement a module-level input lock and `manual_hotmail_code_input(email, ...)`.
- [ ] Pass the provider into `reg.fill_code_and_submit()`.
- [ ] Re-run the focused tests and confirm they pass.

### Task 3: Tkinter main-thread GUI input provider

**Files:**
- Modify: `tests/test_hotmail_manual_code.py`
- Modify: `grok_register_ttk.py`

- [ ] Write failing tests for GUI request completion and cancellation using a fake scheduler/dialog function, without opening a real window.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Add a queued GUI request object containing email, result, error, and completion event.
- [ ] Schedule dialogs through `root.after()` and serialize requests on the Tk main thread.
- [ ] Pass `self.request_manual_hotmail_code` into the GUI registration call.
- [ ] Ensure stop requests cancel waiting prompts and wake worker threads.
- [ ] Re-run the focused tests and confirm they pass.

### Task 4: Configuration and documentation

**Files:**
- Modify: `grok_register_ttk.py`
- Modify: `config.example.json`
- Modify: `config.json`
- Modify: `README.md`

- [ ] Add `hotmail_code_mode: manual` to default and example configuration.
- [ ] Set the current local configuration to manual mode so the requested behavior is active immediately.
- [ ] Document `manual` and `imap`, including the CLI/GUI interaction and multi-thread serialization behavior.
- [ ] Validate both JSON configuration files with `python -m json.tool`.

### Task 5: Regression and completion verification

**Files:**
- Verify all modified files.

- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Run `python -m compileall -q .`.
- [ ] Run import smoke checks inside `.venv`.
- [ ] Run `python optimization_checks.py`; record any pre-existing heuristic failures separately.
- [ ] Review the diff-equivalent changed-file list manually because this workspace has no Git metadata.

## Repository limitation

This workspace is not a Git repository, so the commit steps normally required by the planning workflow cannot be performed. Verification artifacts and exact modified paths will be reported instead.
