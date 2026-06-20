# Ollama Receipt Extraction — Design

**Date:** 2026-06-20
**Status:** Approved (design phase)
**Branch:** feat/client-expense-tracking (or a follow-up branch)

## Goal

Let the user point the app at a self-hosted **Ollama** server and, when adding a
**client expense**, drop a receipt (image or PDF). A vision model reads the
receipt and **pre-fills** the client-expense form. The user reviews, edits, and
confirms before anything is saved. The feature is **optional and additive**: with
no Ollama configured, the manual flow works exactly as it does today.

## Scope

- **In scope:** `ClientExpense` only (reimbursable, customer-linked).
- **Out of scope (for now):** business `Expense` (Chart of Accounts), multi-page
  PDFs (first page only), automatic FX for anything other than the receipt total
  and subtotal.

## Key principles

- **Never blocks the existing process.** The receipt button is gated; if Ollama
  is unset/unreachable or the chosen model isn't vision-capable, the button is
  hidden and the manual form is untouched.
- **Confirm, never auto-save.** Extracted values only pre-fill the form. Nothing
  is written to the DB until the user clicks Save.
- **Never guess.** The model returns `null` for fields it can't see. We don't
  back-compute taxes or invent values.
- **Customer is never extracted.** The receipt shows the *vendor*; the *customer*
  (which of the user's clients to bill) is always chosen by the user.

## Section 1 — Settings & connection

New nullable fields on `CompanySettings` (existing DBs keep working):

- `ollama_url` — e.g. `http://192.168.1.50:11434`
- `ollama_model` — the selected model name

Settings page additions:

1. Text input for the Ollama URL.
2. **"Test connection"** button → `GET {url}/api/tags`. On success, populate a
   **model dropdown** with installed models. For each model, call `/api/show` and
   read `capabilities`; tag vision-capable models (e.g. `llava ✓ vision`) and
   show non-vision models **disabled** (they can't read receipts).
3. User selects a model → Save.

Helper `ollama_is_ready()` returns true only when `ollama_url` and a
vision-capable `ollama_model` are saved and the host is reachable. Every feature
surface is gated on this.

No new dependency here — uses the existing HTTP client (`httpx`/`requests`).

## Section 2 — Extraction flow

**Button:** at the top of the add-client-expense form, gated on
`ollama_is_ready()`: *"📄 Auto-fill from receipt"*. Accepts images
(`.jpg/.png/.heic`) and `.pdf`.

Pipeline on drop:

1. **Save the file** to `data/receipts/` (existing location) and remember the
   path → becomes `receipt_path` on save, whether or not extraction succeeds.
2. **Normalize to an image.** PDFs → render **first page** to PNG via
   **PyMuPDF (`pymupdf`)** (clean wheel, no system packages). Images pass through.
3. **Call Ollama.** `POST {url}/api/generate` with the base64 image, the selected
   model, `stream: false`, and `format` set to a **JSON schema** for structured
   output. Prompt: extract a receipt's `vendor`, `date`, `subtotal`, `tax_lines`
   (label + amount), `total`, `currency`; return `null` for anything not visible.
4. **Spinner + timeout.** Loading indicator (vision models can take 10–30s). On
   timeout/error → notification *"Couldn't read the receipt, please enter
   manually"*; form stays open and usable.

Extracted values **pre-fill** the form. User reviews/edits and saves normally.

## Section 3 — Data mapping, currency & taxes

**Field mapping** (Ollama JSON → `ClientExpense`):

| Extracted | Maps to |
|-----------|---------|
| `vendor` + short summary | `description` |
| `date` (parsed; blank if unparseable) | `date` |
| `subtotal` | `amount` (pre-tax) |
| TPS/TVQ tax lines | `tps`, `tvq` |
| `total` | `total` |
| `currency` | conversion + note (not stored as a column) |
| — | `customer_id` always chosen by the user |

**Currency conversion to CAD:**

- `currency == CAD` → no conversion.
- Otherwise fetch a rate from **frankfurter.app** (free, no API key, ECB daily,
  supports historical dates). Use the **receipt date** as the rate date (falls
  back to today if unparsed).
- `amount` and `total` stored as **CAD-converted** figures.
- `notes` preserves the original, e.g.
  *"Original: €50.00 EUR · rate 1.47 CAD/EUR @ 2026-06-18 (frankfurter.app)"*.
- **Fallback:** if the rate fetch fails, don't block — store raw amounts, note the
  currency, warn *"Couldn't fetch exchange rate — amounts are in EUR, please
  convert/enter manually."*

**Taxes:**

- Québec receipt (TPS/TVQ present) → fill `tps`/`tvq` (converted if needed).
- Foreign receipt → `tps`/`tvq` stay 0 (QC-specific); foreign tax recorded in
  `notes`, still inside the tax-inclusive `total`.
- Never back-compute or guess a split — the user confirms.

A small notice summarizes what was vs. wasn't detected so the user knows what to
check.

## Testing

Pure pieces, no live Ollama/network:

- PDF → PNG conversion.
- JSON-schema response parsing.
- Field mapping.
- Tax handling (QC / foreign / total-only / mismatch).
- FX conversion with a **mocked** rate call, including the failure-fallback path.
- `ollama_is_ready()` gating: button hidden when URL unset, model non-vision, or
  host unreachable (mocked HTTP).

One documented **manual/integration** check against the real Ollama server (not
in the automated suite).

## New dependencies / external calls

- **PyMuPDF (`pymupdf`)** — PDF first-page → PNG.
- **frankfurter.app** — external HTTP call, fires only for non-CAD receipts.
- Ollama server — user-provided, optional.
