# Design Review #2 (revised plan): Client Expense Tracking

**Reviews:** [2026-06-20-client-expenses-design.md](./2026-06-20-client-expenses-design.md) (revised after review #1)
**Supersedes context of:** [2026-06-20-client-expenses-design-review.md](./2026-06-20-client-expenses-design-review.md)
**Date:** 2026-06-20
**Verdict:** ✅ Implementable. All review #1 findings resolved. Two minor notes + one standing risk.

---

## Verification of the revision against the codebase

Every claim the revised plan makes was checked against the actual code:

| Claim in plan | Status |
|---|---|
| Invoice taxes all lines uniformly at two sites | ✅ `update_totals()` `app/main.py:397-399` and `save()` `app/main.py:435`, both `sub * 0.14975` |
| `tax_rate_id` exists but is ignored by the math | ✅ Optional on `app/database.py:94`, never read in the tax calc |
| `service_id` is required on `InvoiceItem` | ✅ `app/database.py:90` |
| A recurring-generation pattern exists to model on | ✅ `check_recurring()` `app/main.py:1991` — queries `next_issue_date <= now`, generates a Draft, advances the date |
| `compute_total()` available for reuse | ✅ `app/main.py:742`, used by the expense form |

---

## Review #1 findings — resolution status

| # | Finding (review #1) | Resolution in revised plan |
|---|---|---|
| 1 | 🔴 Invoice-item required fields (`service_id`, `unit_price`) | ✅ Seed a "Reimbursable Expense" service; line item shape spelled out (lines 167–172) |
| 2 | 🔴 Double-taxation on attach | ✅ Non-taxable pass-through; tax engine changed to tax only taxable lines (lines 150–165) |
| 3 | 🔴 Totals not recomputed / Draft-only not enforced | ✅ Recompute+persist totals; attachment Draft-gated (lines 174–181) |
| 4 | 🟠 Recurrence coupled to reimbursement | ✅ Time-based via `next_due_date`, independent of status (lines 135–148) |
| 5 | 🟠 No terminal rejected/written-off state | ✅ `written_off` terminal state added from `disputed` (lines 80, 85–87) |
| 6 | 🟠 `claimed` vs `waiting` redundant | ✅ Kept, with rationale (steps 4 and 5) (lines 82–83) — accepted as deliberate |
| 7 | 🟠 enum vs string status | ✅ Switched to plain `str` to match codebase (lines 48, 60–63) |
| — | Minor: filename ordering, sanitization | ✅ Commit-before-write + sanitize (lines 183–188) |
| — | Minor: day-of-month clamp | ✅ Clamp 29–31 to last valid day (lines 147–148) |
| — | Minor: nav + i18n | ✅ Sidebar + `TRANSLATIONS` noted (lines 107–108) |
| — | Minor: reuse `compute_total()` | ✅ Called out (lines 118–119) |

All blockers and concerns from review #1 are closed.

---

## New notes on the revised plan (minor — not blockers)

### A. Recurrence date math — do NOT copy `check_recurring()` literally
The existing pass advances with `p.next_issue_date += timedelta(days=30)`
(`app/main.py:1999`) — a crude 30-day step that drifts off calendar months. The
revised plan correctly wants true monthly cadence + day clamping (lines 147–148),
which is *better* than the existing behavior. The implementer must use real month
arithmetic (e.g. `dateutil.relativedelta`, or manual month rollover), **not** the
`timedelta(days=30)` shortcut copied from existing code.

### B. Confirm where the generation pass is actually triggered
The plan says recurrence runs "on app start / page load, same pattern as recurring
invoices" (lines 140–141). Verify how `check_recurring()` is currently wired
(startup hook vs. page visit) and reuse that same trigger so client-expense
recurrence fires on one cadence — don't introduce a second scheduler/trigger point.

---

## Standing risk (already flagged in the plan — reaffirmed)

**The invoice tax-engine change is the single highest-risk item** (plan lines
150–165, 222–225). It edits shared, existing invoice code used by every invoice.

Mitigation before/while implementing:
- Snapshot `subtotal`, `tax_total`, `total` for a few existing **all-taxable**
  invoices first.
- After the change, assert those totals are **byte-identical** (no regression for
  the common case).
- Apply the change in **both** `update_totals()` (live UI) and `save()`
  (persistence) so the displayed total and the stored total never diverge.

---

## Bottom line

The design is sound, internally consistent, and aligned with existing conventions.
Cleared to implement. Sequence the work so the tax-engine change lands behind its
regression check, and keep recurrence on the existing trigger with correct calendar
math.
