# Client Expense External Ref + Total/Duplicate Filters

## Summary

Added an optional `external_ref` (client reimbursement reference #) to client
expenses, editable inline in the list, plus list filtering by total range and a
"same total" duplicate shortcut.

- `ClientExpense.external_ref` (nullable, free-form, may repeat across expenses).
- Idempotent migration backfills the column on existing DBs.
- `set_client_expense_external_ref()` trims input; blank clears to NULL; raises
  on a missing expense.
- `filter_client_expenses()` is a pure helper filtering by customer, status,
  min/max total, and a `duplicate_total` shortcut (matches within one cent).
- List UI: new "Ref. #" column with an inline editable input; total-range and
  duplicate filters wired to the existing filter bar.

## Changed Files

- `app/database.py` (model field + migration)
- `app/main.py` (helpers + list UI wiring)
- `tests/test_client_expense_model.py` (set_external_ref, filter_client_expenses)
- `tests/test_db_migrations.py` (clientexpense backfill)

## Verification

- `uv run pytest -q` → 128 passed.
- Browser render of `/client-expenses`: no console errors; "Ref. #" column,
  inline ref inputs, and total/duplicate filters present.
