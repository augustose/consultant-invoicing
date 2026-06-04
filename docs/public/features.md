# Functional Requirements

This document describes the current public feature scope for Consultant Invoicing.

## 1. Client Management

- Store customer name, email, phone, contact person, address, and currency.
- List customers alphabetically.
- Edit customer details inline.
- Prevent deletion when a customer is already tied to invoices.

## 2. Services Catalog

- Store service name, optional description, unit price, and active status.
- Use service defaults when creating invoice line items.
- Edit service details inline.
- Toggle services active or inactive.
- Prevent deletion when a service is already used by invoices.

## 3. Invoicing

- Create invoices by selecting a customer and one or more services.
- Calculate subtotal, Quebec sales tax, and total automatically.
- Generate sequential numeric invoice numbers.
- Track invoice states through Draft, Sent, Paid, Cancelled, and Written Off.
- Display Sent invoices as Overdue after their due date.
- Preview invoices as HTML and download rendered PDFs.
- Support custom HTML invoice templates from Settings.

## 4. Recurring Billing

- Store recurring billing profiles with customer, service, frequency, amount, and next issue date.
- Show recurring profiles in the Subscription page.
- Generate draft recurring invoices in the background when active profiles are due.

## 5. Expense Tracking

- Record business expenses by date, description, account, amount, optional TPS/TVQ, and notes.
- Link expenses to active expense accounts from the chart of accounts.
- Filter expenses by period.
- Export filtered expenses to CSV.

## 6. Chart of Accounts

- Provide default asset, liability, income, and expense accounts.
- Allow custom accounts to be added.
- Protect system accounts from deletion.
- Allow non-system accounts to be edited, activated, deactivated, or deleted.

## 7. Dashboard and Reports

- Show paid, awaiting payment, draft, and client count summaries.
- Chart monthly paid revenue.
- Show recent invoice activity.
- Provide report cards for sales summary, monthly revenue trend, TPS/TVQ collected, income by customer, and aged receivables.
- Support report period presets and custom report dates.

## 8. Settings and Templates

- Configure company legal name, address, phone, email, GST number, and QST number.
- Download the default invoice template.
- Upload a custom HTML invoice template.
- Reset the invoice template to the default.

## 9. Future AI Features

- Voice dictation and command support.
- Natural-language invoice creation.
- Natural-language queries over local accounting data.
- Optional MCP server integration.
