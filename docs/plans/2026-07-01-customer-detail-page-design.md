# Customer Detail Page ("ficha") — Design

## Goal
From the customer list, clicking a customer's name should open a detail page for
that customer showing their contact info, their invoices (most recent first),
and a button to create a new invoice for them.

## Navigation
- New route: `/customer/{id}`.
- In `/customers` ([app/main.py:2298](../../app/main.py)), the customer name label
  becomes clickable (`cursor-pointer text-indigo-600 hover:underline`), navigating
  to `/customer/{cust.id}`.
- `/customer/{id}` has a "← Back to Customers" link at the top.
- If `id` doesn't exist in the DB: notify error and redirect to `/customers`.

## Ficha content (read-only)
- Card with customer name as title, and below it: email, phone, address, contact
  person.
- No inline editing here — editing stays on `/customers`, which already supports it.
- No summary metrics (invoice counts/totals) — out of scope per user decision.

## Invoice list section
- Title "Invoices for {name}" + button "Create invoice for this customer".
- Reuses existing helpers `build_invoice_list_row` / `invoice_list_columns` /
  `filter_and_sort_invoice_rows` ([app/main.py:284-333](../../app/main.py)),
  filtered by `customer_id`, sorted `Date newest` (most recent first, fixed sort —
  no sort selector on this page).
- Columns: number, date, status (badge), total. No customer column (redundant),
  no edit/delete/mark-paid actions.
- Clicking a row opens the existing preview dialog
  (`open_invoice_preview`, [app/main.py:454](../../app/main.py)), from which the
  PDF can be downloaded.
- Empty state: "No invoices yet" message, same visual style as `/invoices`' empty
  state.

## Create-invoice dialog reuse
The new-invoice dialog currently lives inline in `/invoices`
([app/main.py:593-656](../../app/main.py)) with a freely selectable customer.
Extract it into a shared function:

```python
def render_new_invoice_dialog(customers, services, default_customer_id=None,
                               lock_customer=False, redirect_to='/invoices'):
    ...
```

- `/invoices` calls it with no `default_customer_id` (current behavior unchanged).
- `/customer/{id}` calls it with `default_customer_id=cust.id, lock_customer=True,
  redirect_to=f'/customer/{cust.id}'`. The customer select is pre-filled and
  disabled; on save, the user returns to the ficha (not `/invoices`), where the
  new invoice appears at the top of the list.
- The "Create invoice for this customer" button opens this dialog directly on the
  ficha page (no navigation away).

## Out of scope
- No customer editing on the ficha.
- No summary metrics/totals on the ficha.
- No edit/delete/mark-paid actions in the ficha's invoice list.
- No changes to tax/numbering logic.
