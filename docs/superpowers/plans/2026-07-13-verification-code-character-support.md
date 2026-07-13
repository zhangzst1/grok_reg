# Verification Code Character Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `VerificationCodeFetcher.extract_code()` to return pure-letter, pure-digit, and mixed ASCII `XXX-XXX` verification codes.

**Architecture:** Keep the existing candidate regex, boundary checks, context scoring, ambiguity handling, and uppercase normalization. Remove only the post-match character-composition filter that currently rejects candidates unless they contain both a letter and a digit.

**Tech Stack:** Python 3.13, `re`, built-in `unittest`, `uv`, `mise`

---

## File Structure

- Modify `tests/test_verification_code.py`: define the expected extraction behavior for pure-letter and pure-digit verification codes.
- Modify `utils/verification_code.py`: accept every candidate already validated by `_CODE_PATTERN` instead of requiring a mixed letter/digit composition.

### Task 1: Accept All Supported Character Compositions

**Files:**
- Modify: `tests/test_verification_code.py:9-75`
- Modify: `utils/verification_code.py:142-174`

- [ ] **Step 1: Write failing regression tests**

Add a pure-letter test and replace the numeric rejection test with a numeric extraction test:

```python
def test_extracts_letter_only_hyphenated_code(self) -> None:
    text = "Your verification code is jfh-kob."

    self.assertEqual(VerificationCodeFetcher.extract_code(text), "JFH-KOB")

def test_extracts_numeric_only_hyphenated_code(self) -> None:
    self.assertEqual(
        VerificationCodeFetcher.extract_code("Code: 123-456"),
        "123-456",
    )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
uv run python -m unittest tests.test_verification_code.VerificationCodeExtractionTests -v
```

Expected: the new pure-letter test and changed numeric-only test fail because `extract_code()` returns `None`; the existing extraction tests pass.

- [ ] **Step 3: Implement the minimal fix**

In `VerificationCodeFetcher.extract_code()`, remove the unused compact value and mixed-composition guard:

```python
for match in cls._CODE_PATTERN.finditer(text):
    code = match.group(0).upper()

    prefix = text[max(0, match.start() - 120):match.start()]
```

Do not change `_CODE_PATTERN`, context scoring, subject handling, boundary rules, or ambiguity behavior.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```powershell
uv run python -m unittest tests.test_verification_code.VerificationCodeExtractionTests -v
```

Expected: every `VerificationCodeExtractionTests` test passes with no errors or failures.

- [ ] **Step 5: Run repository verification**

Run:

```powershell
uv run python -m unittest discover -s tests -v
mise run check
```

Expected: the complete unit-test suite passes and the principal Python modules compile successfully.

- [ ] **Step 6: Review the scoped diff**

Run:

```powershell
git diff --check -- tests/test_verification_code.py utils/verification_code.py
git diff -- tests/test_verification_code.py utils/verification_code.py
```

Expected: no whitespace errors; the diff contains only the two regression-test behavior changes and removal of the mixed letter/digit filter.

- [ ] **Step 7: Commit the implementation**

Run:

```powershell
git add -- tests/test_verification_code.py utils/verification_code.py
git commit -m "Support all verification code character types"
```

Expected: the commit includes only `tests/test_verification_code.py` and `utils/verification_code.py`.
