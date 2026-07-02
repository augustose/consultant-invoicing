## Summary

Task 1 of the invoice-duplicate feature plan (`docs/plans/2026-07-01-invoice-duplicate-implementation.md`). Adds `shift_month_year_in_text`, a standalone pure-text helper that advances every "<Month> <Year>" mention in a string by N months, recognizing English, French, and Spanish month names (accented or not) and preserving the original casing style. Used by a later task to roll forward month mentions in invoice line-item descriptions when an invoice is duplicated.

## Changed Files

- `app/main.py` — added `shift_month_year_in_text` and its private helpers (`_MONTH_NAMES_BY_LOCALE`, `_MONTH_OUTPUT_BY_LOCALE`, `_month_index`, `_apply_case_style`), placed after `invoice_item_description`.
- `tests/test_invoice_duplicate.py` — new file, 9 tests covering EN/FR/ES month names, year rollover at December, case preservation, multi-month shifts, no-match passthrough, and multiple occurrences in one string.

## Verification

- `uv run pytest tests/test_invoice_duplicate.py -v` — confirmed failure first (`ImportError: cannot import name 'shift_month_year_in_text'`) before implementing, then 9/9 passed after implementing.
- `uv run pytest tests/ -q` — full suite, 137 passed, no regressions.

## Note on concurrent workspace edits

While this task was in progress, unrelated in-progress changes (a `render_new_invoice_dialog` extraction and a new `/customer/{id}` detail page) appeared in `app/main.py`'s working tree, matching this project's known "concurrent auto-commit agent" behavior. The first commit attempt (`git add app/main.py`) accidentally swept those unrelated hunks in alongside this task's change. This was caught during self-review, the commit was undone with a non-destructive `git reset` (mixed, local, unpushed — no data loss), and the commit was redone containing only this task's diff (65 lines in `app/main.py` + the new test file, 108 insertions total). The unrelated changes remain uncommitted in the working tree, untouched, for whichever process is handling that feature.
