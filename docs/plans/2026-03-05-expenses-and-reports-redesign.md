# Expenses + Reports Redesign — Design Document
**Date:** 2026-03-05

## Overview

Two parallel changes:
1. New `Expense` model and `/expenses` page
2. Reports page redesign as a hub with expandable report cards

---

## 1. Database — New `Expense` Model (`database.py`)

Fields:
- `id` (int, PK)
- `date` (datetime, default today)
- `description` (str)
- `amount` (float) — pre-tax subtotal
- `tps` (float, default 0.0) — TPS amount collected
- `tvq` (float, default 0.0) — TVQ amount collected
- `total` (float) — computed: amount + tps + tvq
- `account_id` (int, FK → Account) — must be AccountType.Expense
- `notes` (str, optional)

---

## 2. New `/expenses` Page (`main.py`)

### Sidebar
Add `('/expenses', 'payments', 'Expenses')` between Accounts and Reports.

### Layout
**Header:** "Expenses" title + "Track business expenses linked to your chart of accounts"

**Add Expense form (card):**
- Row 1: Date (date picker, default today) | Description | Account dropdown (AccountType.Expense only)
- Row 2: Amount (pre-tax) | TPS checkbox (auto-calc 5%) | TVQ checkbox (auto-calc 9.975%) | Total (read-only)
- Row 3: Notes (optional) | "Add Expense" button

**Expenses table (card):**
- Date range filter chips: This Month | Last Month | This Year | All Time
- Columns: Date | Description | Account | Subtotal | TPS | TVQ | Total | Actions (edit/delete)
- Summary row: totals for subtotal, TPS, TVQ, grand total
- Empty state with icon

**Edit:** inline dialog pre-filled with row data.

---

## 3. Reports Page Redesign (`/reports`)

### Layout
- "Reports" title + global date range filter (preset chips: This Month, Last Month, This Year, Last Year, All Time, Custom)
- 3 sections, each with expandable report cards

### Card UI
Each card: header row with icon + title + description + chevron toggle. Clicking expands detail content inline.

---

### Section: Income

**Sales Summary** (existing, moved here)
- KPI cards: Total Invoiced | Collected | Outstanding | Cancelled
- Invoice table: # | Client | Date | Status | Subtotal | Taxes | Total

**Monthly Revenue Trend** (new)
- Plotly bar chart: paid revenue per month for the selected period
- Color-coded bars, x-axis = month labels

---

### Section: Taxes

**Sales Tax Report** (existing, moved here)
- KPI cards: TPS Collected | TVQ Collected | Total Taxes Due | Taxable Revenue
- Table of paid invoices with per-row TPS/TVQ breakdown

---

### Section: Customers

**Income by Customer** (new)
- Table: Customer | # Invoices | Subtotal | Taxes | Total Paid — sorted by total desc
- Donut chart: revenue share per client

**Aged Receivables** (new)
- KPI chips: Current (0–30d) | 31–60d | 61–90d | 90d+ — each showing total outstanding
- Table of unpaid (Sent/Overdue) invoices with age bucket column
- Age calculated from invoice due_date (or date if no due_date)

---

## Implementation Order

1. Add `Expense` model to `database.py`
2. Build `/expenses` page in `main.py`
3. Redesign `/reports` page: hub layout + existing reports moved into cards
4. Add Monthly Revenue Trend card
5. Add Income by Customer card
6. Add Aged Receivables card
