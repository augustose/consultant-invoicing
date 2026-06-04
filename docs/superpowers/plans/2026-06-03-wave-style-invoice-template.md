# Wave-Style Invoice Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install a Wave-style custom invoice template, update Augusto/Cafe Parvis business data, and generate the next invoice as `100123`.

**Architecture:** Keep the existing Jinja template rendering path. Add a small invoice-number helper in `app/main.py` and update the invoice save flow to use it. Apply private database data updates directly to `data/accounting.db`.

**Tech Stack:** Python, NiceGUI, SQLModel, SQLite, Jinja2, pytest.

---

## File Structure

- `app/main.py`: add numeric invoice-number helper and use it when saving new invoices.
- `app/template_utils.py`: pass GST/QST numbers into the Jinja render context.
- `data/invoice_template_custom.html`: replace with the active Wave-style custom template.
- `data/accounting.db`: update existing company/customer/service records.
- `tests/test_invoice_numbering.py`: add focused tests for next-number generation.

### Task 1: Add Sequential Invoice Numbering

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_invoice_numbering.py`

- [ ] **Step 1: Write the failing tests**

```python
from types import SimpleNamespace

from app.main import next_invoice_number


def test_next_invoice_number_uses_external_wave_baseline_when_database_has_no_numeric_numbers():
    invoices = [
        SimpleNamespace(number="INV-2026-001"),
        SimpleNamespace(number="INV-03042057"),
    ]

    assert next_invoice_number(invoices) == "100123"


def test_next_invoice_number_continues_after_highest_numeric_database_number():
    invoices = [
        SimpleNamespace(number="100123"),
        SimpleNamespace(number="INV-03042057"),
        SimpleNamespace(number="100125"),
    ]

    assert next_invoice_number(invoices) == "100126"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_invoice_numbering.py -q`

Expected: import error or assertion failure because `next_invoice_number` does not exist yet.

- [ ] **Step 3: Implement the helper**

Add this near the invoice actions in `app/main.py`:

```python
LAST_EXTERNAL_INVOICE_NUMBER = 100122


def next_invoice_number(invoices) -> str:
    numeric_numbers = []
    for invoice in invoices:
        number = str(getattr(invoice, "number", "")).strip()
        if number.isdigit():
            numeric_numbers.append(int(number))
    return str(max(numeric_numbers + [LAST_EXTERNAL_INVOICE_NUMBER]) + 1)
```

- [ ] **Step 4: Use helper in invoice save flow**

Replace:

```python
inv = Invoice(number=f"INV-{datetime.now().strftime('%m%d%H%M')}", customer_id=c_sel.value, date=datetime.strptime(i_date.value, '%Y-%m-%d'), subtotal=sub, tax_total=sub*0.14975, total=sub*1.14975, status='Draft')
```

With:

```python
existing_invoices = s.exec(select(Invoice)).all()
inv = Invoice(number=next_invoice_number(existing_invoices), customer_id=c_sel.value, date=datetime.strptime(i_date.value, '%Y-%m-%d'), subtotal=sub, tax_total=sub*0.14975, total=sub*1.14975, status='Draft')
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_invoice_numbering.py -q`

Expected: pass.

### Task 2: Add Tax Numbers to Template Context

**Files:**
- Modify: `app/template_utils.py`
- Test: render smoke check in Task 5

- [ ] **Step 1: Add context variables**

In `TemplateManager.render_invoice`, add these keys:

```python
"gst_number": vendor_settings.tps_number if vendor_settings and vendor_settings.tps_number else "",
"qst_number": vendor_settings.tvq_number if vendor_settings and vendor_settings.tvq_number else "",
```

### Task 3: Replace Custom Template

**Files:**
- Modify: `data/invoice_template_custom.html`

- [ ] **Step 1: Replace the HTML template**

Create a letter-size HTML template that uses existing variables:

- `invoice_number`
- `balance_due`
- `currency`
- `client_entity`
- `client_contact`
- `client_address`
- `client_phone`
- `client_email`
- `issue_date`
- `due_date`
- `line_items`
- `subtotal`
- `gst`
- `qst`
- `total`
- `notes`
- `vendor_entity`
- `vendor_address`
- `vendor_phone`
- `gst_number`
- `qst_number`

The template must not contain the words `Powered by Wave`.

### Task 4: Update Private Database Data

**Files:**
- Modify: `data/accounting.db`

- [ ] **Step 1: Update company settings**

Set:

```text
legal_name = Augusto Sosa Escalada (Mac)
address = 1464, Fronenac St. App.#1
          Montreal, Quebec H2K 2Y7
          Canada
phone = 5148853146
tps_number = 717569891 RT 0001
tvq_number = 4023119175 TQ 0002
currency = CAD
```

- [ ] **Step 2: Update Cafe Parvis in place**

Set:

```text
name = Cafe Parvis
contact = Alejandra Ponce
email = alejandraponce@hotmail.com
phone = 514 775 5234
address = 433 Rue Mayor
          Montréal, Quebec H3A 1N9
          Canada
currency = CAD
```

- [ ] **Step 3: Update or create service**

Set:

```text
name = IT Consulting and Support
description = Monthly Subscription for Technical Support of Existing IT Infrastructure.
unit_price = 600.00
is_active = 1
```

### Task 5: Verify

**Files:**
- Check: `data/invoice_template_custom.html`
- Check: `data/accounting.db`
- Test: `tests/test_invoice_numbering.py`

- [ ] **Step 1: Run focused tests**

Run: `uv run pytest tests/test_invoice_numbering.py -q`

Expected: pass.

- [ ] **Step 2: Confirm database records**

Run:

```bash
sqlite3 data/accounting.db "select legal_name, address, phone, tps_number, tvq_number, currency from companysettings;"
sqlite3 data/accounting.db "select name, contact, email, phone, address, currency from customer where name='Cafe Parvis';"
sqlite3 data/accounting.db "select name, description, unit_price, is_active from service where name='IT Consulting and Support';"
```

Expected: values match the approved spec.

- [ ] **Step 3: Confirm no Wave branding**

Run: `rg -n "Powered by Wave|wave" data/invoice_template_custom.html`

Expected: no matches.

- [ ] **Step 4: Render a smoke preview**

Run a small Python snippet that loads one invoice, renders it through `TemplateManager.render_invoice`, and confirms the output contains `INVOICE`, `Augusto Sosa Escalada (Mac)`, `Cafe Parvis`, and not `Powered by Wave`.
