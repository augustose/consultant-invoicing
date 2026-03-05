# User Stories & Acceptance Criteria

This document defines the expected behaviour of the system. Each story follows the standard format and details the technical conditions required for successful implementation.

---

## Client Management (CRM)

### US-01: Client Registration
**Story**: As a consultant, I want to register and manage my clients' information so I don't have to re-enter their details on every invoice.
**Acceptance Criteria:**
- [x] The system must capture: legal name, email, billing address, and currency (USD/CAD).
- [x] Data must persist in the `customer` table in SQLite.
- [x] Duplicate email addresses must be rejected.
- [x] A list view with inline editing and delete capability must exist.

---

## Core Invoicing

### US-02: Manual Invoice Creation
**Story**: As a consultant, I want to create professional invoices to bill for my services.
**Acceptance Criteria:**
- [x] Must allow selecting an existing client from a dropdown.
- [x] Must allow adding multiple line items (service, quantity, unit price).
- [x] Subtotal, taxes (TPS/TVQ), and total must be calculated in real time.
- [x] On save, an invoice number must be generated (format: `INV-MMDDHHMM`).
- [x] Initial status must be "Draft".

### US-03: Invoice Preview & Export
**Story**: As a consultant, I want to preview the invoice in a professional format before sending it.
**Acceptance Criteria:**
- [x] Preview renders using a Jinja2 HTML template via `/preview/{id}`.
- [x] User can print or save as PDF using the browser's native print dialog.
- [x] The template is fully customizable — user can upload a custom HTML template in Settings.

---

## Recurring Billing

### US-04: Recurring Profile Management (Retainers)
**Story**: As a consultant with monthly retainer clients, I want a "set-and-forget" recurring billing system that is extremely easy to configure and manage.
**Acceptance Criteria:**
- [x] **Flexible Frequency**: Weekly, biweekly, monthly, quarterly options.
- [x] **Operation Modes**:
    - *Review Mode*: System creates a Draft on the scheduled date for manual approval.
    - *Autopilot Mode*: System creates and marks as Sent automatically (ideal for fixed fees).
- [x] **Visibility**: Dedicated view showing next billing date, monthly recurring amount, and associated client.
- [x] **Quick Actions**: Pause, skip next cycle, or trigger immediately.

---

## Payment Tracking

### US-05: Recording Received Payments
**Story**: As a consultant, I want to record payments received so I always know which invoices are still outstanding.
**Acceptance Criteria:**
- [x] "Mark as Paid" action available on any Sent invoice.
- [ ] Partial payment support: if payment is less than total, invoice moves to "Partially Paid" status.
- [ ] Payment history per invoice must be visible.

---

## Business Intelligence

### US-06: Financial Health Dashboard
**Story**: As a consultant, I want a visual overview of my business to make quick financial decisions.
**Acceptance Criteria:**
- [x] Clear display of: total collected (Paid), total outstanding (Sent), total drafts.
- [x] Monthly revenue bar chart for the last 12 months.
- [x] Recent invoice activity table with client, date, status, and total.
- [x] Data sourced directly from SQLite queries.

---

## Localisation & Compliance

### US-07: Regional Configuration
**Story**: As a consultant, I want to configure my tax rules and currency for my location (initially Québec, Canada) so the system adapts to my local legislation.
**Acceptance Criteria:**
- [x] **Settings Panel**: Define base currency (CAD, USD, etc.).
- [x] **Tax Management**: TPS (5%) and TVQ (9.975%) pre-configured and displayed on all invoices.
- [x] **Legal Identifiers**: Fields for NEQ, TPS registration number, and TVQ registration number.

### US-08: Tax Collection Report
**Story**: As a consultant in Québec, I need a report that shows exactly how much TPS and TVQ I have collected, to simplify my quarterly or annual tax filing.
**Acceptance Criteria:**
- [x] **Period Selector**: Filter by preset (This Month, Last Month, This Year, Last Year, All Time) or custom date range.
- [x] **Breakdown**: Taxable base, total TPS collected, and total TVQ collected shown separately.
- [ ] **Simple Export**: Button to copy values or export a CSV summary for the accountant.

---

## Accounting Core

### US-09: Chart of Accounts
**Story**: As a consultant, I want the system to manage a flexible Chart of Accounts based on market standards (as seen in Wave) so my accountant can understand and audit my finances.
**Acceptance Criteria:**
- [x] **Standard Hierarchy**: Pre-configured with main categories:
    - **Assets**: Cash, Accounts Receivable, Bank Account.
    - **Liabilities**: Taxes Payable (TPS/TVQ), Accounts Payable.
    - **Income**: Consulting Services, Product Sales.
    - **Expenses**: Software, Office, Travel, etc.
- [x] **Flexibility**: Users can add custom accounts within these categories.
- [x] **System Account Protection**: Built-in accounts cannot be deleted or have their type changed.

---

## Internationalisation & Portability

### US-10: Multi-Language UI (i18n)
**Story**: As a consultant, I want the interface available in multiple languages (English/Spanish) so I can work in my preferred language.
**Acceptance Criteria:**
- [x] Translation dictionary in `main.py` for all UI strings.
- [x] User can switch between English and Spanish from the sidebar.
- [x] Default language is English.

### US-11: Data Portability (Backup & Accountant Exchange)
**Story**: As a consultant, I want to export my financial data to send to my accountant.
**Acceptance Criteria:**
- [x] JSON export of invoices and data.
- [ ] CSV export option.
- [ ] Import procedure to restore from a previously exported file.

---

## Future — AI & MCP Readiness
- The system is architected with a clean data layer to eventually act as an **MCP (Model Context Protocol)** server, allowing AI agents to read and write invoices with the user's permission.
