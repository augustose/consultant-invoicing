# Accountant Export Design

## Goal

Add a single accountant-focused export flow that packages the data a small-business accountant is most likely to need for a selected reporting period. The default export should be easy to read in Excel, QuickBooks Online import tools, or any spreadsheet workflow, and it should include a small human-readable HTML report that explains what was exported.

## Scope

- Add an "Export for Accountant" action to the Reports page.
- Reuse the Reports date presets and custom date range pattern.
- Generate a ZIP package as the recommended export format.
- Include accountant-relevant CSV files and a small HTML summary report inside the ZIP.
- Keep invoice line-item detail optional and disabled by default.
- Add a second XML export option as a structured audit file, without claiming QuickBooks import compatibility.
- Leave the existing raw Accounts JSON export untouched for this change.

## Recommended Export: CSV ZIP

The default export format is a ZIP archive named with the reporting period, for example:

`accountant_export_2026-01-01_to_2026-03-31.zip`

The ZIP contains:

- `accountant_report.html`: a compact visual report for the accountant.
- `summary.csv`: period totals and counts.
- `invoices.csv`: invoice-level rows, without line items by default.
- `expenses.csv`: expenses with account, taxes, total, and notes.
- `tax_report.csv`: TPS/TVQ collected on paid invoices and recorded on expenses.
- `customers.csv`: customers referenced by invoices in the selected period.
- `chart_of_accounts.csv`: active and inactive accounts for mapping and review.
- `manifest.json`: machine-readable metadata about the export.

If the user enables "Include invoice line-item details", the ZIP also includes:

- `invoice_items.csv`: invoice lines linked to exported invoices.

## CSV Content

`summary.csv` should contain one row with:

- period start
- period end
- generated at
- currency
- invoice count
- paid invoice count
- sent invoice count
- cancelled invoice count
- expense count
- invoiced subtotal
- invoiced tax total
- invoiced total
- paid subtotal
- paid tax total
- paid total
- expense subtotal
- expense TPS
- expense TVQ
- expense total
- net before taxes, using paid subtotal minus expense subtotal

`invoices.csv` should contain:

- invoice number
- invoice date
- due date
- customer name
- customer email
- status
- subtotal
- TPS
- TVQ
- tax total
- total
- notes

`expenses.csv` should contain:

- date
- description
- account code
- account name
- subtotal
- TPS
- TVQ
- total
- notes

`tax_report.csv` should contain labeled rows for:

- TPS collected from paid invoices
- TVQ collected from paid invoices
- TPS recorded on expenses
- TVQ recorded on expenses
- Net TPS payable estimate
- Net TVQ payable estimate

`customers.csv` should contain:

- name
- contact
- email
- phone
- address
- currency

`chart_of_accounts.csv` should contain:

- code
- name
- type
- description
- active flag
- system flag

`invoice_items.csv`, when included, should contain:

- invoice number
- invoice date
- customer name
- service id
- description
- quantity
- unit price
- line total

## HTML Report

`accountant_report.html` should open directly from the ZIP after extraction. It should use Tailwind via CDN for the small visual report and should not depend on the running app.

The report should show:

- Business identity from Company Settings.
- Selected period and generation timestamp.
- High-level income, expense, net, and tax figures.
- Counts of invoices, paid invoices, expenses, customers, and accounts.
- A short "Files included" table describing each CSV/JSON/XML file in the export.
- A note that CSV files are the primary accountant-friendly interchange format and may be imported or reviewed manually depending on the accountant's software.

The HTML report is a summary and index, not the source of truth. The CSV files remain the canonical exported data.

## XML Option

Add a second format option labeled "Audit XML". This produces one XML file with:

- export metadata
- company settings
- reporting period
- chart of accounts
- customers used in the period
- invoice summaries
- optional invoice line items if the same toggle is enabled
- expenses
- tax summary

The UI copy should avoid promising compatibility with QuickBooks, SAF-T, OFX, or any specific accounting platform. It may describe the file as a structured XML export for archival or custom accountant workflows.

## User Flow

1. The user opens Reports.
2. The user clicks "Export for Accountant".
3. A dialog opens with:
   - period preset buttons matching Reports
   - custom start and end inputs
   - format selector with `CSV ZIP` selected by default
   - optional checkbox for invoice line-item details
   - primary "Export" button
4. The app validates the date range.
5. The app generates the selected export into `data/exports/`.
6. The browser downloads the generated file.
7. The app shows a success notification with the included date range.

## Data Rules

- Period filtering uses invoice date for invoices and expense date for expenses.
- Invoice totals include all invoices in the period except where a specific metric says paid invoices only.
- Tax collected metrics use paid invoices only.
- Customer export includes only customers connected to invoices in the selected period.
- Chart of accounts is exported in full because accountants need account mapping context.
- Expense account names and codes are denormalized into the CSV for easy review.
- Dates use `YYYY-MM-DD`.
- Amounts use decimal strings with two digits and no currency symbol.
- Missing text values are exported as empty strings.

## Error Handling

- Invalid dates show an inline notification and do not create a file.
- End date before start date shows an inline notification.
- Empty exports are allowed as long as the date range is valid; the report and manifest should still explain that no invoices or expenses were found.
- File generation errors are logged and shown as a user-facing error notification.

## Implementation Shape

Add a small export module rather than expanding `app/main.py` further:

- `app/export_utils.py`: build export datasets, write CSV files, render HTML report, render audit XML, and create ZIP files.
- `app/main.py`: add the Reports-page UI dialog and call the export helpers.
- `tests/test_accountant_export.py`: cover dataset filtering, ZIP contents, CSV headers, optional line items, XML structure, and empty-period behavior.

The helper API should accept an explicit SQLModel session, start date, end date, format, and include-line-items flag. This keeps the export logic testable without launching NiceGUI.

## Verification

- Run focused export tests.
- Run existing report, invoice, and expense tests if practical.
- Manually generate a CSV ZIP from the app and inspect the archive contents.
- Open `accountant_report.html` from the generated export and confirm it renders without the app running.
- Confirm default export excludes `invoice_items.csv`.
- Confirm enabling line items includes `invoice_items.csv`.
