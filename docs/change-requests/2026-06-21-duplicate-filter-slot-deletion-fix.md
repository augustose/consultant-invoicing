# Duplicate Filter Slot Deletion Fix

## Summary

Fixed a NiceGUI runtime error when clicking the `DUP` badge in client expenses.
Programmatic filter updates are now paused so they do not refresh and delete the
originating table slot before the duplicate filter handler finishes.

## Changed Files

- `app/main.py`
- `tests/test_client_expenses.py`
- `docs/change-requests/2026-06-21-duplicate-filter-slot-deletion-fix.md`

## Verification

- `uv run python -m py_compile app/main.py tests/test_client_expenses.py`
- `uv run pytest tests/test_client_expenses.py tests/test_client_expense_model.py -q`
