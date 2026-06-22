## Summary

Prevent bulk receipt imports from crashing when the originating NiceGUI client is deleted before AI extraction finishes. The bulk handler now captures the upload client, dismisses progress only while the client exists, skips stale completion notifications, and avoids refreshing deleted UI.

## Changed Files

- `app/main.py`
- `tests/test_client_expenses.py`

## Verification

- `./.venv/bin/pytest tests/test_client_expenses.py::test_safe_client_notify_skips_deleted_client -q`
- `./.venv/bin/python -m py_compile app/main.py`
- `./.venv/bin/pytest tests/test_client_expenses.py -q`
- `./.venv/bin/pytest -q`
