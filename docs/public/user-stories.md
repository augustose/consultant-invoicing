# User Stories and Acceptance Criteria

This document describes the public product behavior expected from Consultant Invoicing.

## Client Management

### US-01: Customer Registration

**Story:** As a consultant, I want to manage customer information so I do not re-enter billing details for every invoice.

**Acceptance Criteria:**

- [x] Store customer name, email, phone, contact person, address, and currency.
- [x] Persist customers in SQLite.
- [x] Reject duplicate customer email addresses.
- [x] Show customers in a list with inline editing.
- [x] Prevent deletion when a customer is already tied to invoices.

## Core Invoicing

### US-02: Manual Invoice Creation

**Story:** As a consultant, I want to create professional invoices for my services.

**Acceptance Criteria:**

- [x] Select an existing customer.
- [x] Add one or more service line items.
- [x] Calculate subtotal, TPS/TVQ, and total.
- [x] Generate sequential numeric invoice numbers.
- [x] Save new invoices as Draft.

### US-03: Invoice Preview and Export

**Story:** As a consultant, I want to preview and export invoices before sending them.

**Acceptance Criteria:**

- [x] Render invoice previews with Jinja2 HTML.
- [x] Download rendered invoice PDFs.
- [x] Support custom HTML invoice templates.
- [x] Allow resetting the template to the default.

### US-04: Invoice Status Workflow

**Story:** As a consultant, I want invoice status rules that protect the accounting trail.

**Acceptance Criteria:**

- [x] Draft invoices can be marked Sent.
- [x] Draft invoices can be cancelled.
- [x] Sent and Overdue invoices can be marked Paid.
- [x] Sent and Overdue invoices can be written off.
- [x] Paid, Written Off, and Cancelled invoices are locked.
- [x] Sent invoices display as Overdue after the due date.

## Recurring Billing

### US-05: Recurring Profile Visibility

**Story:** As a consultant with recurring customers, I want to see recurring billing profiles and have due profiles generate draft invoices.

**Acceptance Criteria:**

- [x] Store recurring profile customer, service, frequency, amount, and next issue date.
- [x] Show recurring profiles in the Subscription page.
- [x] Generate draft recurring invoices for active profiles when due.
- [ ] Add UI to create, edit, pause, skip, or trigger recurring profiles manually.

## Expenses

### US-06: Expense Tracking

**Story:** As a consultant, I want to record business expenses so my reports and exports are easier to prepare.

**Acceptance Criteria:**

- [x] Record date, description, account, subtotal, optional TPS, optional TVQ, total, and notes.
- [x] Link expenses to active expense accounts.
- [x] Filter expenses by This Month, This Year, or All Time.
- [x] Export filtered expenses to CSV.
- [ ] Edit and delete expenses from the Expenses page.

## Dashboard and Reports

### US-07: Dashboard Overview

**Story:** As a consultant, I want a quick financial overview when I open the app.

**Acceptance Criteria:**

- [x] Show paid, awaiting payment, and draft invoice totals.
- [x] Show client count.
- [x] Show monthly paid revenue.
- [x] Show recent invoice activity.

### US-08: Financial Reports

**Story:** As a consultant, I want period-based reports for taxes, revenue, customers, and receivables.

**Acceptance Criteria:**

- [x] Filter reports by preset or custom period.
- [x] Show sales summary.
- [x] Show monthly revenue trend.
- [x] Show TPS and TVQ collected on paid invoices.
- [x] Show income by customer.
- [x] Show aged receivables.
- [ ] Export all report summaries to CSV.

## Configuration and Portability

### US-09: Company Settings

**Story:** As a consultant, I want company metadata to appear correctly on invoices.

**Acceptance Criteria:**

- [x] Store legal name, address, phone, email, GST number, and QST number.
- [x] Use company settings in invoice rendering.

### US-10: Data Portability

**Story:** As a consultant, I want my data to remain local and exportable.

**Acceptance Criteria:**

- [x] Store application data locally in SQLite.
- [x] Ignore private data files in git.
- [x] Export core accounting data to JSON.
- [x] Export expenses to CSV.
- [ ] Restore/import from a previous export.

### US-11: Help and Localization

**Story:** As a consultant, I want in-app guidance and basic language preferences.

**Acceptance Criteria:**

- [x] Help page explains sidebar options.
- [x] Help page explains invoice status rules.
- [x] Sidebar language selector supports English and Spanish labels.
- [ ] Expand translation coverage across every UI string.

## Future AI and Automation

- [ ] Voice dictation and simple voice commands.
- [ ] Natural-language invoice creation.
- [ ] Natural-language questions over accounting data.
- [ ] Optional MCP server integration.
