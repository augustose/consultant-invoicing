# Design Review: Client Expense Tracking

**Reviews:** [2026-06-20-client-expenses-design.md](./2026-06-20-client-expenses-design.md)
**Date:** 2026-06-20
**Reviewer:** validation pass against current codebase

---

## Overall

Well-structured plan — clear data model, explicit status transitions, YAGNI section,
and open questions. It is genuinely a different concept from the existing `Expense`
model (that one is a *business* expense → Chart of Accounts; this is a
*client-reimbursable* expense), so a separate table is justified.

However, there are **three blockers** where the plan contradicts how the code
actually works, plus several design concerns to resolve before coding.

---

## 🔴 Blockers (will break against current code)

### 1. Invoice attachment is underspecified and will fail
Plan (lines 116–118) inserts an `InvoiceItem` with only `description` and `total`.
The actual model in `app/database.py:86` requires more:

```python
class InvoiceItem:
    service_id: int = Field(foreign_key="service.id")  # REQUIRED, not Optional
    quantity: float
    unit_price: float   # REQUIRED
    total: float
```

`service_id` and `unit_price` are mandatory.
**Decision needed:** seed a "Reimbursable Expense" / "Misc" service to point at,
or make `service_id` Optional on the model.

### 2. Double-taxation when attaching to an invoice
`ClientExpense.total` already includes TPS+TVQ. But invoices recompute tax on the
subtotal — see `app/main.py:435`: `tax_total=sub*0.14975, total=sub*1.14975`.
Pushing the tax-inclusive `total` as a line item means the client gets taxed twice.

**Decision needed:** pick the pass-through model:
- attach the **pre-tax `amount`** as the line item and let the invoice apply tax, OR
- attach `total` and exclude it from tax recomputation.

This is the crux of the feature and the plan is currently silent on it.

### 3. Attaching a line item doesn't recompute invoice totals
The plan never updates `Invoice.subtotal / tax_total / total` after inserting the
item. It also doesn't restrict attachment to **Draft** invoices — the UI text says
"draft invoice" but the rest of the app only allows editing Drafts
(`app/main.py:37`, `can_cancel_invoice` = `status == "Draft"`).
Enforce Draft-only in the business logic, not just the UI label.

---

## 🟠 Design concerns

### 4. Recurrence is coupled to reimbursement — backwards
Lines 107–113: the next month's expense is created *only when the current one is
marked `reimbursed`*. A monthly subscription recurs whether or not the client paid
back. If an expense gets stuck in `disputed`, the recurring chain silently dies.
Recurrence should be **time-based** (like the existing
`RecurringProfile.next_issue_date`, `app/database.py:97`), not status-triggered.
Consider reusing that pattern instead of inventing a second mechanism.

### 5. No terminal "rejected / written-off" state
The status flow only exits via `reimbursed`. If a `disputed` claim is ultimately
refused, there is nowhere to put it — it sits in `disputed` forever and skews any
"needs follow-up" metric. Invoices already have a `Written Off` concept
(`app/main.py:355`); mirror it.

### 6. `claimed` vs `waiting` looks redundant
"Claim filed" and "waiting for payment" are arguably the same state. Unless
`claimed` means "drafted but not sent," consider collapsing to
`pending → claimed → reimbursed` with `disputed` as a branch.
Fewer states = fewer invalid-transition bugs.

### 7. Enum vs string status — match codebase convention
The plan uses a Python `Enum`. But every status field in this codebase is a plain
`str` (`Invoice.status`, `RecurringProfile.frequency`); only `AccountType` is an
enum. SQLModel + SQLite enum migrations are finicky. Prefer `status: str` with a
validator, unless you intend to refactor all statuses to enums.

---

## 🟡 Minor / edge cases

- **Receipt filename ordering** (line 124): `{expense_id}_{filename}` — the id does
  not exist until after `commit()`. Save the row first, get the id, *then* write the
  file. Also **sanitize `original_filename`** (path traversal `../`, odd chars)
  before joining to `data/receipts/`.
- **`recurrence_day` 1–31 edge case:** "same day next month" breaks for day 29–31 in
  shorter months. Clamp to the last valid day.
- **Reuse `compute_total()`** — `app/main.py:742` already derives tps/tvq/total from
  boolean checkboxes. Don't reimplement.
- **Money as `float`** — matches the existing codebase, so fine for consistency, but
  carries the usual float-rounding risk on totals.
- **Missing from the plan:** add `/client-expenses` to the sidebar nav
  (`app/main.py:216`) and to the `TRANSLATIONS` dict (app is bilingual EN/ES).

---

## Answers to the open questions

- **Mandatory note on `disputed`?** Yes. A dispute you can't explain is useless for
  follow-up, and `ClientExpenseEvent.notes` already exists — just require it for that
  transition.
- **"Needs follow-up" highlight after 7 days in `waiting`?** Yes, and the field is
  already designed for it ("days since last change" column). Cheap, high-value. Make
  the threshold a named constant, not a magic `7`.

---

## Recommended decision order

Resolve these two before any code is written — they shape the data model:

1. **#2 — tax pass-through model**
2. **#4 — recurrence model (time-based vs status-triggered)**
