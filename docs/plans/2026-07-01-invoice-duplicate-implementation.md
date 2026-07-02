# Duplicate Invoice Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the user clone any existing invoice into a new, pre-filled, fully editable Draft invoice — with the date rolled to the same day next month and month+year mentions in line-item descriptions advanced accordingly.

**Architecture:** Two new pure helper functions (`shift_month_year_in_text`, `build_duplicate_invoice_prefill`) added next to the existing invoice helpers in `app/main.py`. The inline "New Invoice" dialog-building code is extracted into a `create_invoice_dialog(customers, services, prefill=None)` function so it can be invoked both from the existing "New Invoice" button and from a new "Duplicate" row action. No DB schema changes.

**Tech Stack:** Python 3.11+, NiceGUI, SQLModel, pytest.

**Design doc:** `docs/plans/2026-07-01-invoice-duplicate-design.md`

---

### Task 1: `shift_month_year_in_text` helper

**Files:**
- Modify: `app/main.py` (add near `invoice_item_description`, around line 233-238)
- Test: `tests/test_invoice_duplicate.py` (new file)

**Step 1: Write the failing tests**

Create `tests/test_invoice_duplicate.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from main import shift_month_year_in_text  # noqa: E402


def test_shift_english_month_forward():
    assert shift_month_year_in_text("Consulting - June 2026", 1) == "Consulting - July 2026"


def test_shift_french_month_forward():
    assert shift_month_year_in_text("Consultation - juin 2026", 1) == "Consultation - juillet 2026"


def test_shift_spanish_month_forward():
    assert shift_month_year_in_text("Consultoria - junio 2026", 1) == "Consultoria - julio 2026"


def test_shift_wraps_year_at_december():
    assert shift_month_year_in_text("Retainer - December 2026", 1) == "Retainer - January 2027"


def test_shift_preserves_uppercase():
    assert shift_month_year_in_text("JUNE 2026 RETAINER", 1) == "JULY 2026 RETAINER"


def test_shift_preserves_lowercase():
    assert shift_month_year_in_text("services for june 2026", 1) == "services for july 2026"


def test_shift_multiple_months_ahead():
    assert shift_month_year_in_text("January 2026", 3) == "April 2026"


def test_shift_no_match_passthrough():
    assert shift_month_year_in_text("Flat-rate onboarding fee") == "Flat-rate onboarding fee"


def test_shift_multiple_occurrences_in_one_string():
    text = "Covers June 2026, invoiced in June 2026"
    assert shift_month_year_in_text(text, 1) == "Covers July 2026, invoiced in July 2026"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_invoice_duplicate.py -v`
Expected: FAIL with `ImportError: cannot import name 'shift_month_year_in_text'`

**Step 3: Write the implementation**

Add to `app/main.py`, near `invoice_item_description` (around line 238):

```python
_MONTH_NAMES_BY_LOCALE = {
    "en": ["january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"],
    "fr": ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
           "aout", "septembre", "octobre", "novembre", "decembre"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
           "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
}
# Canonical output name per locale, index-aligned with _MONTH_NAMES_BY_LOCALE.
_MONTH_OUTPUT_BY_LOCALE = {
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"],
}

_ALL_MONTH_WORDS = sorted(
    {word for words in _MONTH_NAMES_BY_LOCALE.values() for word in words},
    key=len, reverse=True,
)
_MONTH_YEAR_RE = re.compile(
    r"\b(" + "|".join(_ALL_MONTH_WORDS) + r")\b\s+(\d{4})",
    re.IGNORECASE,
)


def _normalize_month_word(word: str) -> str:
    return word.lower().replace("é", "e").replace("û", "u").replace("è", "e")


def _month_index(word: str):
    normalized = _normalize_month_word(word)
    for locale, words in _MONTH_NAMES_BY_LOCALE.items():
        if normalized in words:
            return locale, words.index(normalized)
    return None, None


def _apply_case_style(sample: str, word: str) -> str:
    if sample.isupper():
        return word.upper()
    if sample[:1].isupper():
        return word.capitalize()
    return word.lower()


def shift_month_year_in_text(text: str, months: int = 1) -> str:
    """Advance every "<Month> <Year>" mention in text by `months`.

    Recognizes English, French, and Spanish month names (accents optional).
    Text with no recognizable month+year is returned unchanged.
    """
    def replace(match: re.Match) -> str:
        month_word, year_str = match.group(1), match.group(2)
        locale, idx = _month_index(month_word)
        if locale is None:
            return match.group(0)
        total = idx + months
        new_idx = total % 12
        new_year = int(year_str) + total // 12
        output_words = _MONTH_OUTPUT_BY_LOCALE.get(locale, _MONTH_NAMES_BY_LOCALE[locale])
        new_word = _apply_case_style(month_word, output_words[new_idx])
        return f"{new_word} {new_year}"

    return _MONTH_YEAR_RE.sub(replace, text)
```

Add `import re` to the top-level imports in `app/main.py` if it is not already imported (check first — `calendar` and `datetime` are already imported around the top of the file).

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_invoice_duplicate.py -v`
Expected: all 9 tests PASS

**Step 5: Commit**

```bash
git add app/main.py tests/test_invoice_duplicate.py
git commit -m "feat(invoices): add month+year text rollover helper"
```

---

### Task 2: `build_duplicate_invoice_prefill` helper

**Files:**
- Modify: `app/main.py` (add near `advance_recurrence_date` / invoice helpers, after `invoice_item_description`)
- Test: `tests/test_invoice_duplicate.py`

**Step 1: Write the failing tests**

Append to `tests/test_invoice_duplicate.py`:

```python
from datetime import datetime
from types import SimpleNamespace

from main import build_duplicate_invoice_prefill  # noqa: E402


def _invoice(date):
    return SimpleNamespace(id=1, customer_id=10, date=date)


def _item(service_id, qty, price, description):
    return SimpleNamespace(service_id=service_id, quantity=qty, unit_price=price, description=description)


def test_build_prefill_shifts_date_and_description():
    inv = _invoice(datetime(2026, 6, 15))
    items = [_item(3, 2.0, 150.0, "Consulting - June 2026")]

    prefill = build_duplicate_invoice_prefill(inv, items)

    assert prefill["customer_id"] == 10
    assert prefill["date"] == datetime(2026, 7, 15)
    assert prefill["lines"] == [
        {"service_id": 3, "qty": 2.0, "price": 150.0, "description": "Consulting - July 2026"}
    ]


def test_build_prefill_clamps_end_of_month():
    inv = _invoice(datetime(2026, 1, 31))
    items = [_item(1, 1.0, 100.0, "Flat fee")]

    prefill = build_duplicate_invoice_prefill(inv, items)

    assert prefill["date"] == datetime(2026, 2, 28)
    assert prefill["lines"][0]["description"] == "Flat fee"


def test_build_prefill_multiple_lines():
    inv = _invoice(datetime(2026, 12, 1))
    items = [
        _item(1, 1.0, 100.0, "Retainer - December 2026"),
        _item(2, 3.0, 50.0, "Extra hours"),
    ]

    prefill = build_duplicate_invoice_prefill(inv, items)

    assert prefill["date"] == datetime(2027, 1, 1)
    assert prefill["lines"][0]["description"] == "Retainer - January 2027"
    assert prefill["lines"][1]["description"] == "Extra hours"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_invoice_duplicate.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_duplicate_invoice_prefill'`

**Step 3: Write the implementation**

Add to `app/main.py`, after `shift_month_year_in_text`:

```python
def build_duplicate_invoice_prefill(invoice, items) -> dict:
    """Prefill data for a new Draft invoice cloned from `invoice`/`items`.

    Date rolls to the same day next month (clamped to month-end).
    Each line's description has any Month+Year mention advanced by one month;
    everything else about the line (service, qty, price) is copied verbatim.
    """
    new_date = advance_recurrence_date(invoice.date, invoice.date.day)
    lines = [
        {
            "service_id": item.service_id,
            "qty": item.quantity,
            "price": item.unit_price,
            "description": shift_month_year_in_text(item.description, 1),
        }
        for item in items
    ]
    return {"customer_id": invoice.customer_id, "date": new_date, "lines": lines}
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_invoice_duplicate.py -v`
Expected: all 12 tests PASS

**Step 5: Commit**

```bash
git add app/main.py tests/test_invoice_duplicate.py
git commit -m "feat(invoices): add duplicate-invoice prefill builder"
```

---

### Task 3: Extract `create_invoice_dialog` and wire up the "Duplicate" row action

This task touches NiceGUI UI code directly, so it isn't covered by the pytest
suite — verify it by running the app (`uv run python app/main.py`) and
exercising both "New Invoice" and "Duplicate" in the browser afterward
(Task 4 covers that manual verification explicitly).

**Files:**
- Modify: `app/main.py:579-758` (the `invoices_page` function)

**Step 1: Extract the dialog body into a function**

In `app/main.py`, replace the block from `with ui.dialog() as dialog, ui.card()...`
(line 593) through the line that defines `save()` and the Discard/Save button
row (through line 656) with a standalone function defined just above
`invoices_page`, e.g. right after `open_invoice_preview`:

```python
def create_invoice_dialog(customers, services, prefill=None):
    """Build and open a NiceGUI dialog for creating a new Draft invoice.

    When `prefill` is given (see build_duplicate_invoice_prefill), the form
    starts populated with that customer/date/line-items instead of blank
    defaults, and the dialog is labeled as a duplicate of its source.
    """
    title = _('new_invoice')
    if prefill is not None:
        title = f"Duplicate Invoice"

    with ui.dialog() as dialog, ui.card().classes('p-10 w-[950px] premium-card h-auto'):
        dialog.on('hide', dialog.delete)
        ui.label(title).classes('text-3xl font-extrabold mb-10 text-slate-900 dark:text-slate-100')
        with ui.row().classes('w-full gap-8 mb-10'):
            c_sel = ui.select({c.id: c.name for c in customers}, label=_('customers')).classes('flex-1').props('outlined rounded')
            default_date = prefill['date'] if prefill else datetime.today()
            i_date = ui.input('Invoice Date', value=default_date.strftime('%Y-%m-%d')).classes('w-48').props('outlined rounded append-icon=calendar_today')
        if prefill is not None:
            c_sel.set_value(prefill['customer_id'])
        line_items = []
        it_cont = ui.column().classes('w-full gap-3 mb-8')
        totals_labels = {}

        def update_totals():
            items = [((i['q'].value or 0) * (i['p'].value or 0), True) for i in line_items if i['s'].value]
            sub, tax, tot = compute_invoice_totals(items)
            if 'sub' in totals_labels: totals_labels['sub'].text = f'${sub:,.2f}'
            if 'tax' in totals_labels: totals_labels['tax'].text = f'${tax:,.2f}'
            if 'tot' in totals_labels: totals_labels['tot'].text = f'${tot:,.2f}'

        def add_row(line=None):
            with it_cont:
                with ui.row().classes('w-full items-center gap-4 p-5 bg-slate-50 rounded-2xl border border-slate-100 dark:bg-slate-800 dark:border-slate-700'):
                    s_sel = ui.select({s.id: s.name for s in services}, label=_('services')).classes('flex-grow').props('flat borderless')
                    iqty = ui.number('Qty', value=(line['qty'] if line else 1.0)).classes('w-24').props('borderless')
                    iprc = ui.number('Price', value=(line['price'] if line else None)).classes('w-32').props('borderless prefix=$')
                    idesc = ui.input('Description', value=(line['description'] if line else '')).classes('flex-grow').props('borderless dense')
                    def s_ch(e):
                        p = next((s.unit_price for s in services if s.id == e.value), 0.0)
                        iprc.set_value(p); update_totals()
                    s_sel.on_value_change(s_ch); iqty.on_value_change(update_totals); iprc.on_value_change(update_totals)
                    if line is not None:
                        s_sel.set_value(line['service_id'])
                    line_items.append({'s': s_sel, 'q': iqty, 'p': iprc, 'd': idesc})

        if prefill and prefill['lines']:
            for line in prefill['lines']:
                add_row(line)
        else:
            add_row()
        ui.button('Add Line Item', icon='add', on_click=lambda: add_row()).props('flat no-caps text-color=indigo-600').classes('mt-2 h-12 rounded-xl')
        with ui.row().classes('w-full justify-end mt-12 py-8 border-t border-slate-100 dark:border-slate-800'):
            with ui.column().classes('w-80 gap-3 text-right'):
                with ui.row().classes('w-full justify-between'):
                    ui.label(_('subtotal')).classes('text-slate-500 font-medium')
                    totals_labels['sub'] = ui.label('$0.00').classes('text-2xl font-bold')
                with ui.row().classes('w-full justify-between'):
                    ui.label(_('tax')).classes('text-slate-500 font-medium')
                    totals_labels['tax'] = ui.label('$0.00').classes('text-slate-500')
                with ui.row().classes('w-full justify-between pt-4 mt-2 border-t-2 border-slate-900 dark:border-slate-200'):
                    ui.label(_('total')).classes('text-xl font-bold')
                    totals_labels['tot'] = ui.label('$0.00').classes('text-3xl font-black text-indigo-600')
                update_totals()

        def save():
            if not c_sel.value: return ui.notify('Pick a client!', color='red-500')
            try:
                with Session(engine) as s:
                    items = [(i['q'].value * i['p'].value, True) for i in line_items if i['s'].value]
                    sub, tax, tot = compute_invoice_totals(items)
                    existing_invoices = s.exec(select(Invoice)).all()
                    inv = Invoice(number=next_invoice_number(existing_invoices), customer_id=c_sel.value, date=datetime.strptime(i_date.value, '%Y-%m-%d'), subtotal=sub, tax_total=tax, total=tot, status='Draft')
                    s.add(inv); s.commit(); s.refresh(inv)
                    for i in line_items:
                        if i['s'].value:
                            service = next(ser for ser in services if ser.id == i['s'].value)
                            description = i['d'].value.strip() or invoice_item_description(service)
                            s.add(InvoiceItem(invoice_id=inv.id, service_id=i['s'].value, description=description, quantity=i['q'].value, unit_price=i['p'].value, total=i['q'].value*i['p'].value))
                    s.commit()
                    logger.info(f"Nueva factura creada: #{inv.number}, total=${inv.total:,.2f}, cliente_id={inv.customer_id}")
                    ui.notify('Invoice Saved!'); dialog.close(); ui.navigate.to('/invoices')
            except Exception as e:
                logger.exception("Error al guardar nueva factura")
                ui.notify(f'Error al guardar: {e}', color='red-500')

        with ui.row().classes('w-full justify-end gap-4 mt-8'):
            ui.button('Discard', on_click=dialog.close).props('flat no-caps').classes('text-slate-400')
            ui.button('Save Invoice', on_click=save).classes('btn-primary px-10 h-14 rounded-2xl')

    dialog.open()
```

Note this adds a `Description` input per line (previously descriptions were
only auto-generated from the service at save time — `invoice_item_description(service)`).
This is required so a duplicated line's rolled-forward description ("July
2026") is visible and further editable. For brand-new invoices the field
starts empty and falls back to the auto-generated description on save, so
existing behavior for the plain "New Invoice" flow is unchanged.

**Step 2: Replace the call site**

In `invoices_page`, replace the whole extracted block and the trailing
`ui.button(_('new_invoice'), icon='add_circle', on_click=dialog.open)...` line
with:

```python
ui.button(_('new_invoice'), icon='add_circle', on_click=lambda: create_invoice_dialog(customers, services)).classes('btn-primary px-8 h-14 rounded-2xl shadow-xl')
```

(Drop the now-unused `with ui.dialog() as dialog, ui.card()...` wrapper
entirely from `invoices_page` — it lives inside `create_invoice_dialog` now.)

**Step 3: Add the "Duplicate" action to the row actions template**

In the `body-cell-actions` slot ([app/main.py:697](../../app/main.py)), add a
button before the closing `</q-td>`:

```html
<q-btn flat round color="slate-500" icon="content_copy" title="Duplicate" @click="$parent.$emit('duplicate', props.row.id)" />
```

Wire the event just below the existing `table.on(...)` calls:

```python
table.on('duplicate', lambda e: duplicate_invoice_action(e.args, customers, services))
```

**Step 4: Add the `duplicate_invoice_action` handler**

Add near `mark_invoice_as_cancelled_action` (around line 562):

```python
def duplicate_invoice_action(inv_id, customers, services):
    with Session(engine) as s:
        inv = s.get(Invoice, inv_id)
        if inv is None:
            return ui.notify('Invoice not found', color='red-500')
        items = s.exec(select(InvoiceItem).where(InvoiceItem.invoice_id == inv_id)).all()
        prefill = build_duplicate_invoice_prefill(inv, items)
    create_invoice_dialog(customers, services, prefill=prefill)
```

**Step 5: Manual smoke test**

Run: `uv run python app/main.py`, open `http://localhost:8081/invoices`,
click the new copy icon on any invoice row, confirm the dialog opens titled
"Duplicate Invoice" with the same customer, next-month date, and each line's
description showing the rolled-forward month. Edit a field, save, confirm a
new Draft invoice appears in the list with a fresh invoice number. Also
re-check the plain "New Invoice" button still works unchanged.

**Step 6: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests PASS (no regressions)

**Step 7: Commit**

```bash
git add app/main.py
git commit -m "feat(invoices): add duplicate-invoice row action and dialog prefill"
```

---

### Task 4: Update docs

**Files:**
- Modify: `docs/funcionalidades.md` (add a line describing the duplicate-invoice feature, following the existing list format in that file)
- Modify: `docs/decisiones.md` (log the decision: date shift = same-day-next-month; description rollover = month+year regex EN/FR/ES; no DB lineage field)

**Step 1:** Read both files first to match existing formatting/section
placement before editing (`Read docs/funcionalidades.md`,
`Read docs/decisiones.md`).

**Step 2:** Add entries, following each file's existing style (bullet list /
dated decision log entry — inspect the file to confirm the exact convention
before writing).

**Step 3: Commit**

```bash
git add docs/funcionalidades.md docs/decisiones.md
git commit -m "docs: document duplicate-invoice feature and design decisions"
```
