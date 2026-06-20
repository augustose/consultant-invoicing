# Change Request: Client Expense Tracking

**Date:** 2026-06-20
**Status:** Design approved (revised after review)
**Author:** augusto
**Review:** [2026-06-20-client-expenses-design-review.md](./2026-06-20-client-expenses-design-review.md)

---

## Problem

When making purchases on behalf of a client, there is no structured way to:
- Record the expense with its receipt
- Track reimbursement status over time
- Follow up with the client
- Handle recurring expenses (monthly subscriptions)

This is distinct from the existing `Expense` model (`app/database.py:109`), which
tracks *business* expenses against the Chart of Accounts. This feature tracks
*client-reimbursable* expenses, so it gets its own table.

---

## Workflow

1. Make a purchase and pay for it
2. Obtain the receipt (comprobante / factura)
3. File a reimbursement claim with the client
4. **Track status** — wait, validate, follow up
5. Mark as reimbursed with date (or written off if refused)

---

## Data Model

### New table: `ClientExpense`

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `customer_id` | int FK → Customer | required |
| `description` | str | |
| `date` | datetime | date of purchase |
| `amount` | float | pre-tax subtotal |
| `tps` | float | 5% if applicable |
| `tvq` | float | 9.975% if applicable |
| `total` | float | amount + tps + tvq |
| `status` | str | plain string, see below (matches codebase convention) |
| `receipt_path` | str? | `data/receipts/{id}_{sanitized_filename}` |
| `claim_date` | datetime? | when claim was sent to client |
| `reimbursed_date` | datetime? | when client paid back |
| `invoice_id` | int? FK → Invoice | optional, if attached to a bill |
| `is_recurring` | bool | default False |
| `recurrence_day` | int? | day of month (1–31) |
| `next_due_date` | datetime? | drives time-based recurrence (see below) |
| `notes` | str? | |
| `created_at` | datetime | |
| `updated_at` | datetime | |

**Status convention:** plain `str` field, NOT a Python enum — matches
`Invoice.status` and `RecurringProfile.frequency`. Valid values are validated in a
helper, not enforced at the DB level. (Avoids finicky SQLModel/SQLite enum
migrations; only `AccountType` in the codebase is an enum.)

### Status flow

```
pending → claimed → waiting → reimbursed
                       ↓
                   disputed → reimbursed
                            → written_off   (terminal)
```

Valid transitions:
- `pending` → `claimed`
- `claimed` → `waiting`
- `waiting` → `disputed`
- `waiting` → `reimbursed`
- `disputed` → `reimbursed`
- `disputed` → `written_off` (terminal — claim refused / abandoned)

`claimed` = claim just filed/sent. `waiting` = active follow-up period
("Seguimiento"). Both retained — they map to workflow steps 4 and 5.

`written_off` exits the follow-up pipeline so refused claims don't pollute the
"needs follow-up" metric. Mirrors the invoice `Written Off` concept
(`app/main.py:355`).

### New table: `ClientExpenseEvent`

Append-only audit log of every status change.

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `client_expense_id` | int FK → ClientExpense | |
| `status` | str | the new status |
| `changed_at` | datetime | |
| `notes` | str? | optional comment (not mandatory, even for `disputed`) |

---

## UI

### Page: `/client-expenses`

Add to sidebar nav (`app/main.py:216`) and to the `TRANSLATIONS` dict (app is
bilingual EN/ES).

**List view**
- Table: date, customer, description, total, status badge, days since last change
- Filters: by customer, by status, by date range
- Per-row actions: advance status, view receipt, open detail
- **Follow-up highlight:** rows in `waiting` for more than `FOLLOWUP_THRESHOLD_DAYS`
  (named constant = 30) are visually flagged (warning color)

**Detail / Edit view**
- Customer selector, date picker, description, amounts (TPS/TVQ auto-calculated —
  reuse `compute_total()` at `app/main.py:742`, do not reimplement)
- File upload → stored in `data/receipts/`
- Status transition buttons (only valid next states shown)
- Claim section: claim date + optional invoice picker (Draft invoices only)
- Reimbursed section: reimbursement date input
- Recurring toggle: day-of-month selector + computed `next_due_date` when enabled
- Status history timeline (from `ClientExpenseEvent`)

---

## Business Logic

### Status transitions
Only the transitions listed above are valid. UI shows only valid next-state buttons;
the transition helper also validates server-side.

### Recurrence — time-based (DECISION)
Modeled on `RecurringProfile.next_issue_date` (`app/database.py:97`), **not**
status-triggered.

- A recurring `ClientExpense` stores `next_due_date`.
- A generation pass creates the next `ClientExpense` when `next_due_date` is reached,
  **independent of reimbursement status**. A stuck/disputed expense no longer kills
  the recurring chain.
- New entry: same `customer_id`, `description`, amounts, `is_recurring`,
  `recurrence_day`; `status = pending`; `receipt_path = None` (receipt obtained
  fresh each cycle); `next_due_date` advanced one month.
- **Day clamp:** `recurrence_day` 29–31 clamps to the last valid day of shorter
  months (e.g. day 31 → Feb 28/29).

**Trigger — reuse the existing timer (review #2, note B):** recurring invoices run
via a 60-second `ui.timer` registered at startup:
`app.on_startup(lambda: ui.timer(60.0, check_recurring))` (`app/main.py:2058`),
calling `check_recurring()` (`app/main.py:1991`). Hook client-expense generation into
that **same cadence** — call it from within / alongside `check_recurring()`. Do NOT
introduce a second scheduler or trigger point.

**Date math — do NOT copy the existing shortcut (review #2, note A):**
`check_recurring()` advances with `p.next_issue_date += timedelta(days=30)`
(`app/main.py:1999`), a crude 30-day step that drifts off calendar months. The new
feature requires true monthly cadence with day clamping — use real month arithmetic
(`dateutil.relativedelta` or manual month rollover), **not** `timedelta(days=30)`.

### Invoice attachment — non-taxable pass-through (DECISION + KEY RISK)
`ClientExpense.total` already includes TPS+TVQ. The client is reimbursed the exact
out-of-pocket cost, so the attached line item must NOT be taxed again.

**⚠️ Requires changing the core invoice tax engine.** Today the invoice taxes all
lines uniformly: `tax = sub * 0.14975` (`app/main.py:399` and `:435`). The per-line
`InvoiceItem.tax_rate_id` exists but is ignored by the math. To support a
non-taxable reimbursement line, the invoice tax calc must be changed to compute tax
only over taxable lines:

- Treat `tax_rate_id IS NULL` (or an explicit non-taxable marker) as non-taxable.
- Update both `update_totals()` (live UI) and `save()` (persistence) to sum the tax
  base over taxable lines only, then `subtotal = all lines`, `tax_total = taxable
  lines × 0.14975`, `total = subtotal + tax_total`.
- This is a shared change to the invoice flow — regression-test existing
  all-taxable invoices produce identical numbers.

**Line item shape for a reimbursement:**
- `service_id` → a seeded **"Reimbursable Expense"** service (since `service_id` is
  required, `app/database.py:90`). Preferred over making the shared `InvoiceItem`
  model nullable.
- `unit_price` = `ClientExpense.total`, `quantity` = 1, `total` = `ClientExpense.total`
- `tax_rate_id` = None (non-taxable marker)

### Invoice attachment — integrity rules
- **Draft-only:** attachment allowed only when `invoice.status == "Draft"`. Enforce
  in business logic, not just the UI label (`can_cancel_invoice`, `app/main.py:37`,
  is Draft-gated; mirror it).
- After inserting the line item, **recompute and persist** `Invoice.subtotal`,
  `tax_total`, `total`. The original plan omitted this.
- Store `invoice_id` on the `ClientExpense`; show a link to the invoice in detail
  view.

### Receipt storage
- Directory: `data/receipts/` (already gitignored under `data/`)
- **Order:** save the `ClientExpense` row first, `commit()` to get the `id`, *then*
  write the file as `{id}_{sanitized_filename}`. The id does not exist before commit.
- **Sanitize** `original_filename` (strip `../`, path separators, odd chars) before
  joining to the directory — prevent path traversal.
- Detail view shows a download/open link.
- On recurring auto-generation, receipt is NOT carried over — uploaded fresh each
  cycle.

### Money type
`float` throughout, matching the existing codebase (accepted float-rounding risk for
consistency).

---

## Out of Scope (YAGNI)

- Email notifications to client
- PDF export of the expense claim
- Multi-receipt per expense (one receipt per expense)
- Bulk status updates

---

## Decisions (resolved)

| # | Topic | Decision |
|---|---|---|
| Tax | Invoice attachment tax | **Pass tax-inclusive `total` as a non-taxable line item**; modify invoice tax engine to honor non-taxable lines |
| Recurrence | Next-entry generation | **Time-based** via `next_due_date`, independent of payment status |
| Terminal state | Refused claims | **Add `written_off`** terminal state from `disputed` |
| States | claimed vs waiting | **Keep both** — map to workflow steps 4 (claim filed) and 5 (follow-up) |
| Note on disputed | Mandatory? | **No** — notes optional on all transitions |
| Follow-up highlight | Threshold | **30 days** in `waiting`, as a named constant |
| service_id | Required FK | **Seed a "Reimbursable Expense" service** rather than nulling the shared model |

---

## Implementation Risk Summary

1. **Invoice tax-engine change** is the highest-risk item — it touches shared,
   existing invoice code used by every invoice. Mitigation:
   - Snapshot `subtotal`/`tax_total`/`total` of a few existing **all-taxable**
     invoices first; after the change assert they are **byte-identical**.
   - Apply the change in **both** `update_totals()` (live UI, `app/main.py:397`) and
     `save()` (persistence, `app/main.py:435`) so displayed and stored totals never
     diverge.
2. Recurrence: reuse the existing 60-second `ui.timer` / `check_recurring()` trigger
   (`app/main.py:2058`, `:1991`) — don't add a second scheduler. Use real calendar
   month arithmetic, NOT the `timedelta(days=30)` shortcut at `app/main.py:1999`.
3. Filename handling: commit-before-write + sanitize.

---

## Review trail

- Review #1: [2026-06-20-client-expenses-design-review.md](./2026-06-20-client-expenses-design-review.md)
  — 3 blockers + 7 concerns, all resolved.
- Review #2: [2026-06-20-client-expenses-design-review-2.md](./2026-06-20-client-expenses-design-review-2.md)
  — ✅ cleared to implement; notes A/B folded into the Recurrence section above.
