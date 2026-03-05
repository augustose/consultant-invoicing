# Detailed Functional Requirements

This document details all proposed features for the system, organized by module.

---

## 1. Client Management (CRM)
- **Profile Management**: Legal name, contact email, billing address, default currency.
- **Billing History**: List of all invoices sent to the client with their current status.
- **Preferences**: Invoice language, default payment terms (Net 15, Net 30).

## 2. Services / Products Module
- **Catalog**: Service name, default description, unit price.
- **Per-Item Taxes**: Define which taxes apply to each service (TPS, TVQ, etc.).

## 3. Invoicing Module
- **Invoice Generator**:
    - Client selection (autocomplete dropdown).
    - Dynamic line item rows.
    - Real-time subtotal and tax calculation.
    - Per-invoice notes and terms customization.
- **Status Workflow**: Draft → Sent → Paid → Cancelled.
- **Export**: Professional HTML invoice — print to PDF directly from the browser.

## 4. Recurring Billing
- **Recurring Profile Configuration**:
    - Frequency (Weekly, Monthly, Quarterly).
    - Start and end dates.
    - Auto-generate as Draft or auto-send (configurable).

## 5. Payment Tracking
- **Payment Registration**: Payment date, method (transfer, cash, etc.), amount received.
- **Partial Payments**: Support for multiple payments against a single invoice.

## 6. Dashboard & Reports
- **Visual Dashboard**: Monthly revenue chart, total accounts receivable.
- **Reports**: Tax summary report (total revenue vs. taxes collected — TPS and TVQ).

## 7. Future Phase — Artificial Intelligence
- **Virtual Assistant**: Integration with Anthropic/Google for voice dictation and natural-language invoice creation.
- **Predictive Cash Flow Analysis**.
