# Client Expense Add Form Collapse

## Summary

The `Add Client Expense` section now starts collapsed so the filters and expense
grid are easier to see. The save button is available even when AI receipt
extraction is not configured.

## Changed Files

- `app/main.py`
- `tests/test_client_expenses.py`

## Verification

- `uv run python -m py_compile app/main.py tests/test_client_expenses.py`
- `uv run pytest tests/test_client_expenses.py tests/test_client_expense_model.py -q`
