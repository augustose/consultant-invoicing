# Invoice List Filters and Sort Design

## Goal

Add a compact set of reset-on-page-load filters and sorting controls to the invoice list so users can quickly find the invoices they need without turning the invoice page into a report screen.

## Current Context

The `/invoices` page currently loads customers, services, and invoices once, then renders every invoice in a NiceGUI table. Rows are built with `build_invoice_list_row`, which already exposes display status, raw status, customer name, formatted date, formatted total, and action eligibility flags.

The reports and expenses pages already use in-page filter state and explicit refresh functions. The invoice list should follow that style instead of introducing persistence or new backend endpoints.

## Approved Behavior

Filters reset whenever the invoice page reloads. The default view shows all invoices sorted by newest invoice date first.

The invoice list will include a compact control bar above the table:

- Search input for invoice number and customer name.
- Status selector with All, Draft, Sent, Overdue, Paid, Written Off, and Cancelled.
- Customer selector with All customers plus existing customers.
- Period selector with All Time, This Month, Last Month, This Year, Last Year, and Custom.
- Custom date inputs shown only when Custom is selected.
- Sort selector with Date newest, Date oldest, Total high, Total low, Customer A-Z, and Invoice #.
- Clear button that resets filters to defaults.

Controls should update the table immediately when values change. Custom date inputs should validate `YYYY-MM-DD`; invalid dates should show a notification and leave the current filtered table unchanged.

## Architecture

Keep invoice filtering client-page-local inside `invoices_page`.

Add a small filter state dictionary with defaults:

- `query`: empty string
- `status`: `All`
- `customer_id`: `All`
- `period`: `All Time`
- `from`: start boundary used for custom or preset periods
- `to`: end boundary used for custom or preset periods
- `sort`: `Date newest`

Add helper logic near the invoice table to:

1. Convert invoices to list rows using `build_invoice_list_row`.
2. Apply search, status, customer, and period filters.
3. Sort the filtered rows.
4. Re-render or update the table container.

No database schema changes, no persistent user settings, and no new API route are required.

## UI Details

The controls should use the app's existing premium-card styling and report/expense filter conventions. Keep the layout responsive with wrapping rows, compact inputs, and clear labels.

The invoice action buttons and status badge should continue working exactly as they do now after filtering or sorting.

When no invoices match the active filters, show an empty state inside the table area with a search-off style icon and short text.

## Error Handling

Invalid custom dates should show a red notification. A custom period with the end date before the start date should also show a red notification.

If a customer referenced by an invoice is missing, the existing `?` fallback remains unchanged.

## Testing

Add or update tests for the filtering and sorting helper behavior if the current test structure allows it without heavy UI automation. Cover:

- Default date-newest ordering.
- Status filtering, including Overdue display status.
- Customer filtering.
- Search by invoice number and customer name.
- Date range filtering.
- Total-high or total-low sorting.

Run the existing test suite. Also smoke-test the invoice page in the browser to confirm controls render, filters update the table, clear resets the view, and invoice action buttons remain available.
