# Bulk Receipts & Client-Expense List Enhancements — Design

**Date:** 2026-06-21
**Status:** Approved (design phase)
**Branch:** feat/client-expense-tracking

## Goal

Build on the working Ollama receipt extraction with four user-requested features:

1. **Bulk import** — drop multiple images/PDFs; each is OCR'd and auto-added to
   the client-expense list as a `pending` row.
2. **Inline customer change** — reassign the customer directly in the list row.
3. **Receipt preview** — thumbnail + enlarge dialog in the list.
4. **Duplicate flagging** — flag rows sharing the same `(date, total)`.

## Decisions (from brainstorming)

- Bulk imports **auto-create** `pending` rows (no per-receipt confirm step).
- Imports land in an **"Unassigned"** customer bucket; user reassigns in the list.
- Duplicate key = **same date + same total**, flagged **across all** expenses.
- **Zero-total** rows are **not** flagged (avoids flagging weak/empty extractions).
- Inline customer = **always-visible per-row dropdown** (fast initial triage).
- Existing single-receipt form-prefill flow is unchanged; bulk import is additive.

## Section 1 — Bulk import

- `get_or_create_unassigned_customer(session)` — idempotent helper (mirrors
  `get_or_create_reimbursable_service`); `Customer(name="Unassigned",
  email="unassigned@local")`.
- A second upload control **"📥 Import multiple receipts"** (`multiple=True`),
  shown only when `ai_ready`. Per file:
  1. `read_upload_file` → bytes + name.
  2. `normalize_to_image` → `extract_receipt`.
  3. Create `ClientExpense` (status `pending`, customer = Unassigned, extracted
     date/amount/tps/tvq/total/description/notes), log `ClientExpenseEvent`,
     save the receipt to `data/receipts/`.
- Per-file failures are isolated (skip + amber note; batch continues).
- Spinner notification while running; summary toast at the end.

## Section 2 — List enhancements

- **Inline customer:** the Customer column renders a compact `q-select` per row
  (Quasar slot) pre-set to the current customer; change emits a `reassign` event
  → `reassign_client_expense_customer(session, expense_id, customer_id)` → refresh.
  Options include "Unassigned" so unclassified rows are visible.
- **Preview:** mount `app.add_media_files('/receipts', 'data/receipts')`
  (read-only; localhost single-user app). Each row with a receipt shows a
  thumbnail; click → enlarge dialog. Image receipts shown directly; PDF receipts
  rendered to a cached `*.thumb.png` via `pdf_first_page_to_png`.
- **Duplicate flag:** `flag_duplicate_expense_ids(expenses)` returns ids whose
  `(date, total)` occurs 2+ times, ignoring `total == 0`. Flagged rows show an
  amber "possible duplicate ⚠" badge with a tooltip. Display-only; nothing is
  blocked or deleted.

## Section 3 — Testing

Pure logic (TDD, no UI/network):
- `get_or_create_unassigned_customer` idempotency.
- `flag_duplicate_expense_ids`: none / one group / multiple groups / zero-total
  ignored.
- `reassign_client_expense_customer` updates `customer_id`.

UI wiring verified by smoke-render + manual check: multi-upload, per-row
`q-select` + `reassign` event, `/receipts` media mount, thumbnail/preview dialog.

## Out of scope (deferred)

- **Extraction quality ("Problem B")** — `minicpm-v` currently returns weak values
  (total 0, mislabeled vendor/taxes). Tuned separately after these features.
- Multi-page PDFs (first page only), business `Expense` extraction.
