# Invoice List Filters and Sort Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reset-on-page-load filters and sorting controls to the invoice list.

**Architecture:** Add pure invoice-list filter/sort helpers near the existing invoice helper functions in `app/main.py`, then wire `/invoices` controls to those helpers. Keep state local to `invoices_page`; no persistence, schema change, or route change.

**Tech Stack:** Python, NiceGUI, SQLModel, pytest.

---

## File Structure

- Modify `app/main.py`
  - Add `invoice_filter_period_bounds`, `filter_and_sort_invoice_rows`, and small constants for invoice list filter options near the existing invoice helpers.
  - Replace the static invoice table in `invoices_page` with a compact filter bar and a refreshable table container.
- Modify `tests/test_invoice_numbering.py`
  - Extend existing invoice helper tests to cover filtering, sorting, search, period bounds, and overdue display-status filtering.

---

### Task 1: Add Failing Helper Tests

**Files:**
- Modify: `tests/test_invoice_numbering.py`

- [ ] **Step 1: Update imports**

Add the new helpers to the existing import block:

```python
from main import (  # noqa: E402
    build_invoice_list_row,
    can_cancel_invoice,
    can_mark_invoice_paid,
    can_write_off_invoice,
    filter_and_sort_invoice_rows,
    invoice_display_status,
    invoice_filter_period_bounds,
    invoice_item_description,
    invoice_list_columns,
    next_invoice_number,
)
```

- [ ] **Step 2: Add reusable row fixtures**

Add this helper below the import block:

```python
def invoice_row(
    *,
    id=1,
    number="100123",
    customer_id=10,
    cname="Cafe Parvis",
    status="Paid",
    raw_status=None,
    date=None,
    total=100.0,
):
    invoice_date = date or datetime(2026, 6, 1)
    return {
        "id": id,
        "number": number,
        "customer_id": customer_id,
        "cname": cname,
        "status": status,
        "raw_status": raw_status or status,
        "date": invoice_date,
        "date_fmt": invoice_date.strftime("%Y-%m-%d"),
        "total": total,
        "total_fmt": f"${total:,.2f}",
    }
```

- [ ] **Step 3: Add filter and sort tests**

Append these tests to `tests/test_invoice_numbering.py`:

```python
def test_invoice_filter_defaults_sort_by_date_newest():
    rows = [
        invoice_row(id=1, number="100123", date=datetime(2026, 5, 1)),
        invoice_row(id=2, number="100124", date=datetime(2026, 6, 1)),
    ]

    result = filter_and_sort_invoice_rows(rows, {"sort": "Date newest"})

    assert [row["number"] for row in result] == ["100124", "100123"]


def test_invoice_filter_searches_number_and_customer_name():
    rows = [
        invoice_row(number="100123", cname="Cafe Parvis"),
        invoice_row(number="100124", cname="Northstar Labs"),
    ]

    by_number = filter_and_sort_invoice_rows(rows, {"query": "123"})
    by_customer = filter_and_sort_invoice_rows(rows, {"query": "northstar"})

    assert [row["number"] for row in by_number] == ["100123"]
    assert [row["number"] for row in by_customer] == ["100124"]


def test_invoice_filter_filters_by_display_status_including_overdue():
    rows = [
        invoice_row(number="100123", status="Overdue", raw_status="Sent"),
        invoice_row(number="100124", status="Sent", raw_status="Sent"),
        invoice_row(number="100125", status="Paid"),
    ]

    result = filter_and_sort_invoice_rows(rows, {"status": "Overdue"})

    assert [row["number"] for row in result] == ["100123"]


def test_invoice_filter_filters_by_customer_id():
    rows = [
        invoice_row(number="100123", customer_id=10),
        invoice_row(number="100124", customer_id=20),
    ]

    result = filter_and_sort_invoice_rows(rows, {"customer_id": 20})

    assert [row["number"] for row in result] == ["100124"]


def test_invoice_filter_filters_by_date_range():
    rows = [
        invoice_row(number="100123", date=datetime(2026, 1, 31)),
        invoice_row(number="100124", date=datetime(2026, 2, 15)),
        invoice_row(number="100125", date=datetime(2026, 3, 1)),
    ]

    result = filter_and_sort_invoice_rows(
        rows,
        {
            "from": datetime(2026, 2, 1),
            "to": datetime(2026, 2, 28),
        },
    )

    assert [row["number"] for row in result] == ["100124"]


def test_invoice_filter_sorts_by_total_high_and_low():
    rows = [
        invoice_row(number="100123", total=100.0),
        invoice_row(number="100124", total=300.0),
        invoice_row(number="100125", total=200.0),
    ]

    high = filter_and_sort_invoice_rows(rows, {"sort": "Total high"})
    low = filter_and_sort_invoice_rows(rows, {"sort": "Total low"})

    assert [row["number"] for row in high] == ["100124", "100125", "100123"]
    assert [row["number"] for row in low] == ["100123", "100125", "100124"]


def test_invoice_period_bounds_support_report_style_presets():
    today = datetime(2026, 6, 4)

    this_month = invoice_filter_period_bounds("This Month", today)
    last_month = invoice_filter_period_bounds("Last Month", today)
    this_year = invoice_filter_period_bounds("This Year", today)
    all_time = invoice_filter_period_bounds("All Time", today)

    assert this_month == (datetime(2026, 6, 1), today)
    assert last_month == (datetime(2026, 5, 1), datetime(2026, 5, 31))
    assert this_year == (datetime(2026, 1, 1), today)
    assert all_time == (None, None)
```

- [ ] **Step 4: Run tests and confirm failure**

Run:

```bash
uv run pytest tests/test_invoice_numbering.py -q
```

Expected: fails because `filter_and_sort_invoice_rows` and `invoice_filter_period_bounds` are not defined.

- [ ] **Step 5: Commit failing tests**

```bash
git add tests/test_invoice_numbering.py
git commit -m "Add invoice list filter tests"
```

---

### Task 2: Implement Filter and Sort Helpers

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add constants near invoice helpers**

Add below `LAST_EXTERNAL_INVOICE_NUMBER`:

```python
INVOICE_STATUS_FILTERS = ["All", "Draft", "Sent", "Overdue", "Paid", "Written Off", "Cancelled"]
INVOICE_PERIOD_FILTERS = ["All Time", "This Month", "Last Month", "This Year", "Last Year", "Custom"]
INVOICE_SORT_OPTIONS = ["Date newest", "Date oldest", "Total high", "Total low", "Customer A-Z", "Invoice #"]
```

- [ ] **Step 2: Add period helper below `invoice_display_status`**

```python
def invoice_filter_period_bounds(period: str, today=None):
    today = today or datetime.today()
    first_this_month = today.replace(day=1)
    first_this_year = today.replace(month=1, day=1)
    last_month_end = first_this_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    last_year_start = today.replace(year=today.year - 1, month=1, day=1)
    last_year_end = today.replace(year=today.year - 1, month=12, day=31)

    if period == "This Month":
        return first_this_month, today
    if period == "Last Month":
        return last_month_start, last_month_end
    if period == "This Year":
        return first_this_year, today
    if period == "Last Year":
        return last_year_start, last_year_end
    return None, None
```

- [ ] **Step 3: Add filter/sort helper below `build_invoice_list_row`**

```python
def filter_and_sort_invoice_rows(rows, filters):
    query = str(filters.get("query") or "").strip().lower()
    status = filters.get("status") or "All"
    customer_id = filters.get("customer_id")
    d_from = filters.get("from")
    d_to = filters.get("to")
    sort = filters.get("sort") or "Date newest"

    filtered = list(rows)

    if query:
        filtered = [
            row for row in filtered
            if query in str(row.get("number", "")).lower()
            or query in str(row.get("cname", "")).lower()
        ]

    if status and status != "All":
        filtered = [row for row in filtered if row.get("status") == status]

    if customer_id not in (None, "All"):
        filtered = [row for row in filtered if row.get("customer_id") == customer_id]

    if d_from is not None:
        filtered = [row for row in filtered if row.get("date") and row["date"] >= d_from]

    if d_to is not None:
        end_bound = d_to.replace(hour=23, minute=59, second=59)
        filtered = [row for row in filtered if row.get("date") and row["date"] <= end_bound]

    if sort == "Date oldest":
        return sorted(filtered, key=lambda row: row.get("date") or datetime.min)
    if sort == "Total high":
        return sorted(filtered, key=lambda row: row.get("total") or 0, reverse=True)
    if sort == "Total low":
        return sorted(filtered, key=lambda row: row.get("total") or 0)
    if sort == "Customer A-Z":
        return sorted(filtered, key=lambda row: str(row.get("cname") or "").lower())
    if sort == "Invoice #":
        return sorted(filtered, key=lambda row: str(row.get("number") or ""))
    return sorted(filtered, key=lambda row: row.get("date") or datetime.min, reverse=True)
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
uv run pytest tests/test_invoice_numbering.py -q
```

Expected: all tests in this file pass.

- [ ] **Step 5: Commit helper implementation**

```bash
git add app/main.py
git commit -m "Add invoice list filter helpers"
```

---

### Task 3: Wire Controls Into the Invoice Page

**Files:**
- Modify: `app/main.py:307-391`

- [ ] **Step 1: Replace static table block with filter state and helpers**

Inside `invoices_page`, after the New Invoice button and before the table rendering area, add:

```python
        today = datetime.today()
        filter_state = {
            "query": "",
            "status": "All",
            "customer_id": "All",
            "period": "All Time",
            "from": None,
            "to": None,
            "sort": "Date newest",
        }
        table_container = ui.column().classes("w-full")
        custom_date_row = None
        custom_from_input = None
        custom_to_input = None
```

Then add these local functions:

```python
        def parse_custom_invoice_dates():
            try:
                d_from = datetime.strptime(custom_from_input.value, "%Y-%m-%d")
                d_to = datetime.strptime(custom_to_input.value, "%Y-%m-%d")
            except (TypeError, ValueError):
                ui.notify("Invalid date format. Use YYYY-MM-DD", color="red-500")
                return None
            if d_to < d_from:
                ui.notify("End date must be on or after start date", color="red-500")
                return None
            return d_from, d_to

        def refresh_invoice_table():
            table_container.clear()
            rows = [build_invoice_list_row(inv, customers) for inv in invoices]
            visible_rows = filter_and_sort_invoice_rows(rows, filter_state)
            with table_container:
                if not visible_rows:
                    with ui.card().classes("w-full p-10 premium-card items-center justify-center"):
                        ui.icon("search_off", size="40px", color="slate-300")
                        ui.label("No invoices match these filters").classes("text-slate-400 text-sm mt-2")
                    return
                with ui.card().classes("w-full p-0 overflow-hidden premium-card"):
                    cols = invoice_list_columns(_("customers"))
                    table = ui.table(columns=cols, rows=visible_rows, row_key="id").classes("w-full border-none shadow-none")
                    table.add_slot("body-cell-status", '''<q-td :props="props"><q-badge :color="props.row.status === 'Paid' ? 'emerald-500' : (props.row.status === 'Sent' ? 'indigo-500' : (props.row.status === 'Overdue' ? 'orange-500' : (props.row.status === 'Written Off' ? 'slate-500' : (props.row.status === 'Cancelled' ? 'red-500' : 'amber-500'))))" :style="{padding:'8px 16px',borderRadius:'100px',fontWeight:'700',fontSize:'10px'}">{{ props.row.status }}</q-badge></q-td>''')
                    table.add_slot("body-cell-actions", '''<q-td :props="props"><q-btn flat round icon="visibility" title="Preview" @click="$parent.$emit('preview', props.row.id)" /><q-btn flat round color="indigo-600" icon="file_download" title="Download PDF" @click="$parent.$emit('download', props.row.id)" /><q-btn v-if="props.row.can_send" flat round color="indigo-400" icon="send" title="Mark as Sent" @click="$parent.$emit('sent', props.row.id)" /><q-btn v-if="props.row.can_mark_paid" flat round color="emerald-500" icon="check" title="Mark as Paid" @click="$parent.$emit('paid', props.row.id)" /><q-btn v-if="props.row.can_write_off" flat round color="amber-600" icon="money_off" title="Write off invoice" @click="$parent.$emit('writeoff', props.row.id)" /><q-btn v-if="props.row.can_cancel" flat round color="red-300" icon="cancel" title="Cancel draft invoice" @click="$parent.$emit('cancel', props.row.id)" /></q-td>''')
                    table.on("preview", lambda e: open_invoice_preview(e.args))
                    table.on("sent", lambda e: mark_invoice_as_sent_action(e.args))
                    table.on("paid", lambda e: mark_invoice_as_paid_action(e.args))
                    table.on("cancel", lambda e: mark_invoice_as_cancelled_action(e.args))
                    table.on("writeoff", lambda e: mark_invoice_as_written_off_action(e.args))
                    table.on("download", lambda e: ui.run_javascript(f'window.open("/download/{e.args}", "_blank")'))
```

- [ ] **Step 2: Add filter controls before `table_container`**

Add this control card after the local functions:

```python
        def on_period_change(e):
            filter_state["period"] = e.value
            if e.value == "Custom":
                custom_date_row.set_visibility(True)
                parsed = parse_custom_invoice_dates()
                if parsed is None:
                    return
                filter_state["from"], filter_state["to"] = parsed
            else:
                custom_date_row.set_visibility(False)
                filter_state["from"], filter_state["to"] = invoice_filter_period_bounds(e.value, today)
            refresh_invoice_table()

        def apply_custom_period():
            parsed = parse_custom_invoice_dates()
            if parsed is None:
                return
            filter_state["from"], filter_state["to"] = parsed
            refresh_invoice_table()

        def clear_invoice_filters():
            filter_state.update({
                "query": "",
                "status": "All",
                "customer_id": "All",
                "period": "All Time",
                "from": None,
                "to": None,
                "sort": "Date newest",
            })
            search_input.set_value("")
            status_select.set_value("All")
            customer_select.set_value("All")
            period_select.set_value("All Time")
            sort_select.set_value("Date newest")
            custom_date_row.set_visibility(False)
            refresh_invoice_table()

        with ui.card().classes("w-full p-4 premium-card mb-4"):
            with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                search_input = ui.input("Search", placeholder="Invoice # or customer").props("dense outlined clearable").classes("w-64")
                search_input.on_value_change(lambda e: (filter_state.update({"query": e.value or ""}), refresh_invoice_table()))

                status_select = ui.select(INVOICE_STATUS_FILTERS, value="All", label="Status").props("dense outlined").classes("w-40")
                status_select.on_value_change(lambda e: (filter_state.update({"status": e.value or "All"}), refresh_invoice_table()))

                customer_options = {"All": "All customers", **{c.id: c.name for c in customers}}
                customer_select = ui.select(customer_options, value="All", label="Customer").props("dense outlined").classes("w-56")
                customer_select.on_value_change(lambda e: (filter_state.update({"customer_id": e.value or "All"}), refresh_invoice_table()))

                period_select = ui.select(INVOICE_PERIOD_FILTERS, value="All Time", label="Period").props("dense outlined").classes("w-40")
                period_select.on_value_change(on_period_change)

                sort_select = ui.select(INVOICE_SORT_OPTIONS, value="Date newest", label="Sort").props("dense outlined").classes("w-44")
                sort_select.on_value_change(lambda e: (filter_state.update({"sort": e.value or "Date newest"}), refresh_invoice_table()))

                ui.button("Clear", icon="clear", on_click=clear_invoice_filters).props("flat").classes("h-10 rounded-lg px-4 text-sm text-slate-500")

            with ui.row().classes("items-end gap-3 mt-3") as custom_date_row:
                custom_date_row.set_visibility(False)
                custom_from_input = ui.input("From", value=today.replace(day=1).strftime("%Y-%m-%d")).props("dense outlined").classes("w-40")
                custom_to_input = ui.input("To", value=today.strftime("%Y-%m-%d")).props("dense outlined").classes("w-40")
                ui.button("Apply", on_click=apply_custom_period).classes("btn-primary h-9 rounded-lg px-5 text-sm")

        refresh_invoice_table()
```

- [ ] **Step 3: Remove old static table block**

Delete the previous block that directly created `cols`, `rows`, `table`, added slots, and attached table events outside `refresh_invoice_table`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_invoice_numbering.py -q
```

Expected: pass.

- [ ] **Step 5: Commit UI wiring**

```bash
git add app/main.py
git commit -m "Add invoice list filters and sorting"
```

---

### Task 4: Full Verification and Browser Smoke

**Files:**
- No source edits expected.

- [ ] **Step 1: Run full test suite**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass. Existing datetime deprecation warnings may appear.

- [ ] **Step 2: Start local app**

Run:

```bash
NICEGUI_SHOW_BROWSER=false uv run python app/main.py
```

Expected: NiceGUI starts and prints a local URL, usually `http://localhost:8080`.

- [ ] **Step 3: Smoke-test `/invoices` in the in-app browser**

Open `http://localhost:8080/invoices` and verify:

- Search filters by invoice number.
- Search filters by customer name.
- Status filter changes visible rows.
- Customer filter changes visible rows.
- Period filter hides/shows custom dates correctly.
- Invalid custom dates show red notifications.
- Sort changes row order.
- Clear resets all controls to defaults.
- Existing row actions remain visible for matching invoices.

- [ ] **Step 4: Stop the local app**

Stop the running server process from the terminal session.

- [ ] **Step 5: Final status check**

Run:

```bash
git status --short --branch
```

Expected: clean working tree on the current feature branch.
