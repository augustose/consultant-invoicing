# Expenses + Reports Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an Expenses tracking page linked to Chart of Accounts and redesign the Reports page as a hub with expandable cards including new Income by Customer, Aged Receivables, and Monthly Revenue Trend reports.

**Architecture:** New `Expense` SQLModel in `database.py` with FK to `Account`; new `/expenses` NiceGUI page in `main.py`; existing `/reports` page refactored into an expandable-card hub with 3 sections (Income, Taxes, Customers).

**Tech Stack:** Python 3.11+, NiceGUI, SQLModel, SQLite, Plotly (already installed)

---

## Context

- **All code lives in `app/main.py`** (1083 lines) and `app/database.py`
- Run app: `uv run python app/main.py` from project root (port 8081)
- DB auto-initializes on startup — adding a new model requires adding it to `SQLModel.metadata.create_all(engine)` call (already handled by `create_db_and_tables()` since it uses `SQLModel.metadata`)
- `AccountType.EXPENSE = "Expense"` already exists in `database.py`
- Existing expense accounts in seed data: codes 5000, 5100, 5200
- Sidebar pages list is at `app/main.py:76-85` inside `create_menu()`
- Reports page: `app/main.py:377-565`
- TPS = 5%, TVQ = 9.975% (hardcoded constants in reports page)
- No test suite exists — create `tests/test_expense_model.py` for model validation

---

## Task 1: Add Expense Model to Database

**Files:**
- Modify: `app/database.py`
- Create: `tests/test_expense_model.py`

**Step 1: Add the Expense model class to `app/database.py`**

Add after the `RecurringProfile` class (line 106), before the `# --- Database Engine ---` comment:

```python
class Expense(SQLModel, table=True):
    """Business expenses linked to Chart of Accounts."""
    id: Optional[int] = Field(default=None, primary_key=True)
    date: datetime = Field(default_factory=datetime.utcnow)
    description: str
    amount: float = Field(default=0.0)  # pre-tax subtotal
    tps: float = Field(default=0.0)     # TPS amount (5% of amount if applicable)
    tvq: float = Field(default=0.0)     # TVQ amount (9.975% of amount if applicable)
    total: float = Field(default=0.0)   # amount + tps + tvq
    account_id: int = Field(foreign_key="account.id")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 2: Update the import in `app/main.py`**

Find line 5:
```python
from database import engine, Account, TaxRate, AccountType, Customer, Service, Invoice, InvoiceItem, RecurringProfile, CompanySettings
```

Replace with:
```python
from database import engine, Account, TaxRate, AccountType, Customer, Service, Invoice, InvoiceItem, RecurringProfile, CompanySettings, Expense
```

**Step 3: Create `tests/test_expense_model.py`**

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import pytest
from sqlmodel import SQLModel, Session, create_engine, select
from database import Expense, Account, AccountType

@pytest.fixture
def engine_and_session():
    test_engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        acc = Account(code="5999", name="Test Expense", type=AccountType.EXPENSE)
        session.add(acc)
        session.commit()
        session.refresh(acc)
        yield test_engine, session, acc.id

def test_expense_can_be_created(engine_and_session):
    eng, session, acc_id = engine_and_session
    exp = Expense(
        description="Phone bill",
        amount=80.0,
        tps=4.0,
        tvq=7.98,
        total=91.98,
        account_id=acc_id,
    )
    session.add(exp)
    session.commit()
    session.refresh(exp)
    assert exp.id is not None
    assert exp.description == "Phone bill"
    assert exp.total == 91.98

def test_expense_total_fields(engine_and_session):
    eng, session, acc_id = engine_and_session
    exp = Expense(description="No tax", amount=100.0, total=100.0, account_id=acc_id)
    session.add(exp)
    session.commit()
    session.refresh(exp)
    assert exp.tps == 0.0
    assert exp.tvq == 0.0
```

**Step 4: Run the tests**

```bash
cd /Users/augustose/DEV/accounting-ai
uv run pytest tests/test_expense_model.py -v
```

Expected: 2 PASSED

**Step 5: Commit**

```bash
git add app/database.py app/main.py tests/test_expense_model.py
git commit -m "feat: add Expense model linked to Chart of Accounts"
```

---

## Task 2: Build the /expenses Page

**Files:**
- Modify: `app/main.py`

**Step 1: Add Expenses to sidebar**

In `create_menu()`, find the pages list at line ~76:
```python
('/accounts', 'account_balance_wallet', 'Accounts'),
('/reports', 'bar_chart', 'Reports'),
```

Replace with:
```python
('/accounts', 'account_balance_wallet', 'Accounts'),
('/expenses', 'payments', 'Expenses'),
('/reports', 'bar_chart', 'Reports'),
```

**Step 2: Add i18n key for expenses**

In the `TRANSLATIONS` dict (line ~14), in the `'en'` dict add:
```python
'expenses': 'Expenses',
```
In the `'es'` dict add:
```python
'expenses': 'Gastos',
```

**Step 3: Add the /expenses page function**

Insert this new page function just before the `@ui.page('/reports')` decorator (line ~377):

```python
@ui.page('/expenses')
def expenses_page():
    inject_premium_styles(); create_menu('/expenses')

    TPS_RATE = 0.05
    TVQ_RATE = 0.09975

    today = datetime.today()
    first_this_month = today.replace(day=1)
    first_this_year  = today.replace(month=1, day=1)

    PRESETS = {
        'This Month': (first_this_month, today),
        'This Year':  (first_this_year,  today),
        'All Time':   (datetime(2000, 1, 1), today),
    }

    state = {'preset': 'This Month', 'from': first_this_month, 'to': today}

    with Session(engine) as s:
        expense_accounts = s.exec(
            select(Account).where(Account.type == AccountType.EXPENSE, Account.is_active == True)
            .order_by(Account.code)
        ).all()

    account_options = {acc.id: f"{acc.code} — {acc.name}" for acc in expense_accounts}

    # ── Form state ──
    form = {
        'date': today.strftime('%Y-%m-%d'),
        'description': '',
        'amount': 0.0,
        'apply_tps': False,
        'apply_tvq': False,
        'account_id': expense_accounts[0].id if expense_accounts else None,
        'notes': '',
    }

    def compute_total(amount, apply_tps, apply_tvq):
        tps = round(amount * TPS_RATE, 2) if apply_tps else 0.0
        tvq = round(amount * TVQ_RATE, 2) if apply_tvq else 0.0
        return tps, tvq, round(amount + tps + tvq, 2)

    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        ui.label('Expenses').classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-2')
        ui.label('Track business expenses linked to your chart of accounts').classes('text-slate-400 text-base mb-8')

        # ── Add Expense Form ──
        with ui.card().classes('w-full p-6 premium-card mb-6'):
            ui.label('Add Expense').classes('text-sm font-black text-slate-400 uppercase tracking-widest mb-4')

            with ui.row().classes('w-full gap-4 flex-wrap'):
                date_input = ui.input('Date', value=form['date']).props('dense outlined').classes('w-40')
                desc_input = ui.input('Description').props('dense outlined').classes('flex-1 min-w-48')
                acct_select = ui.select(account_options, value=form['account_id'], label='Account').props('dense outlined').classes('w-72')

            with ui.row().classes('w-full items-center gap-4 mt-3 flex-wrap'):
                amount_input = ui.number('Amount (pre-tax)', value=0.0, format='%.2f').props('dense outlined prefix=$').classes('w-44')
                tps_check = ui.checkbox('TPS (5%)', value=False)
                tvq_check = ui.checkbox('TVQ (9.975%)', value=False)
                total_label = ui.label('Total: $0.00').classes('text-lg font-bold text-indigo-600 ml-4')

            def update_total():
                tps, tvq, total = compute_total(amount_input.value or 0, tps_check.value, tvq_check.value)
                total_label.set_text(f'Total: ${total:,.2f}')

            amount_input.on_value_change(lambda _: update_total())
            tps_check.on_value_change(lambda _: update_total())
            tvq_check.on_value_change(lambda _: update_total())

            with ui.row().classes('w-full gap-4 mt-3'):
                notes_input = ui.input('Notes (optional)').props('dense outlined').classes('flex-1')

                def save_expense():
                    if not desc_input.value.strip():
                        ui.notify('Description is required', color='red-500'); return
                    if not acct_select.value:
                        ui.notify('Select an account', color='red-500'); return
                    try:
                        exp_date = datetime.strptime(date_input.value, '%Y-%m-%d')
                    except ValueError:
                        ui.notify('Invalid date format. Use YYYY-MM-DD', color='red-500'); return

                    amt = float(amount_input.value or 0)
                    tps, tvq, total = compute_total(amt, tps_check.value, tvq_check.value)

                    with Session(engine) as s:
                        exp = Expense(
                            date=exp_date,
                            description=desc_input.value.strip(),
                            amount=amt,
                            tps=tps,
                            tvq=tvq,
                            total=total,
                            account_id=acct_select.value,
                            notes=notes_input.value.strip() or None,
                        )
                        s.add(exp); s.commit()

                    ui.notify('Expense saved!', color='emerald-500')
                    desc_input.value = ''
                    amount_input.value = 0.0
                    tps_check.value = False
                    tvq_check.value = False
                    notes_input.value = ''
                    update_total()
                    refresh_table()

                ui.button('Add Expense', icon='add', on_click=save_expense).classes('btn-primary h-10 px-6')

        # ── Period Filter ──
        filter_state = {'from': first_this_month, 'to': today}
        preset_btns = {}

        def set_expense_preset(name):
            for n, btn in preset_btns.items():
                btn.classes(replace='btn-primary h-9 rounded-lg px-4 text-sm' if n == name
                            else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300')
            d_from, d_to = PRESETS[name]
            filter_state['from'] = d_from
            filter_state['to'] = d_to
            refresh_table()

        with ui.card().classes('w-full p-4 premium-card mb-4'):
            with ui.row().classes('items-center gap-3 flex-wrap'):
                ui.label('Period:').classes('text-sm font-semibold text-slate-500 mr-2')
                for name in PRESETS:
                    is_active = name == 'This Month'
                    cls = 'btn-primary h-9 rounded-lg px-4 text-sm' if is_active else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                    btn = ui.button(name, on_click=lambda n=name: set_expense_preset(n)).classes(cls)
                    preset_btns[name] = btn

        # ── Expenses Table ──
        table_container = ui.column().classes('w-full')

        acc_name_map = {acc.id: f"{acc.code} — {acc.name}" for acc in expense_accounts}

        def refresh_table():
            table_container.clear()
            d_from = filter_state['from']
            d_to   = filter_state['to'].replace(hour=23, minute=59, second=59)
            with Session(engine) as s:
                expenses = s.exec(
                    select(Expense).where(Expense.date >= d_from, Expense.date <= d_to)
                    .order_by(Expense.date.desc())
                ).all()

            with table_container:
                if not expenses:
                    with ui.card().classes('w-full p-10 premium-card items-center justify-center'):
                        ui.icon('receipt_long', size='40px', color='slate-300')
                        ui.label('No expenses in this period').classes('text-slate-400 text-sm mt-2')
                    return

                cols = [
                    {'name': 'date',    'label': 'Date',        'field': 'date_fmt',  'align': 'left'},
                    {'name': 'desc',    'label': 'Description', 'field': 'description','align': 'left'},
                    {'name': 'account', 'label': 'Account',     'field': 'acct_name', 'align': 'left'},
                    {'name': 'amount',  'label': 'Subtotal',    'field': 'amount_fmt','align': 'right'},
                    {'name': 'tps',     'label': 'TPS',         'field': 'tps_fmt',   'align': 'right'},
                    {'name': 'tvq',     'label': 'TVQ',         'field': 'tvq_fmt',   'align': 'right'},
                    {'name': 'total',   'label': 'Total',       'field': 'total_fmt', 'align': 'right'},
                ]
                rows = [{
                    **exp.model_dump(),
                    'date_fmt':   exp.date.strftime('%Y-%m-%d'),
                    'acct_name':  acc_name_map.get(exp.account_id, '?'),
                    'amount_fmt': f'${exp.amount:,.2f}',
                    'tps_fmt':    f'${exp.tps:,.2f}',
                    'tvq_fmt':    f'${exp.tvq:,.2f}',
                    'total_fmt':  f'${exp.total:,.2f}',
                } for exp in expenses]

                with ui.card().classes('w-full p-0 premium-card overflow-hidden'):
                    tbl = ui.table(columns=cols, rows=rows, row_key='id').classes('w-full border-none shadow-none')
                    tbl.add_slot('body-cell-total', '''<q-td :props="props"><span class="font-bold text-indigo-600">{{ props.row.total_fmt }}</span></q-td>''')

                # Summary row
                tot_amount = sum(e.amount for e in expenses)
                tot_tps    = sum(e.tps    for e in expenses)
                tot_tvq    = sum(e.tvq    for e in expenses)
                tot_total  = sum(e.total  for e in expenses)
                with ui.card().classes('w-full px-6 py-4 premium-card mt-2'):
                    with ui.row().classes('w-full justify-end gap-8 items-center'):
                        for label, val in [('Subtotal', tot_amount), ('TPS', tot_tps), ('TVQ', tot_tvq)]:
                            with ui.column().classes('items-end'):
                                ui.label(label).classes('text-[10px] font-black text-slate-400 uppercase tracking-widest')
                                ui.label(f'${val:,.2f}').classes('text-sm font-semibold text-slate-600')
                        with ui.column().classes('items-end'):
                            ui.label('Grand Total').classes('text-[10px] font-black text-slate-400 uppercase tracking-widest')
                            ui.label(f'${tot_total:,.2f}').classes('text-xl font-black text-indigo-600')

        refresh_table()
```

**Step 4: Verify manually**

Start app: `uv run python app/main.py`
- Check "Expenses" appears in sidebar
- Add an expense with TPS + TVQ checked → verify total computes correctly
- Add an expense with no taxes → verify TPS/TVQ show $0.00
- Check summary row totals match

**Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat: add /expenses page with account-linked expense tracking"
```

---

## Task 3: Redesign Reports Page — Hub Layout with Expandable Cards

**Files:**
- Modify: `app/main.py` (replace `reports_page()` function, lines ~377-565)

**Step 1: Replace the `reports_page()` function**

Delete the entire `reports_page()` function (lines 377–565) and replace with the new hub layout below.

Key changes:
- Wrap existing Sales Summary and Tax Report content inside expandable card helpers
- Add three new report cards (Monthly Revenue Trend, Income by Customer, Aged Receivables)
- Keep the same date-range filter at the top

```python
@ui.page('/reports')
def reports_page():
    inject_premium_styles(); create_menu('/reports')

    TPS_RATE = 0.05
    TVQ_RATE = 0.09975

    today = datetime.today()
    first_this_month = today.replace(day=1)
    first_this_year  = today.replace(month=1, day=1)
    last_month_end   = first_this_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    last_year_start  = today.replace(year=today.year - 1, month=1, day=1)
    last_year_end    = today.replace(year=today.year - 1, month=12, day=31)

    PRESETS = {
        'This Month': (first_this_month, today),
        'Last Month': (last_month_start, last_month_end),
        'This Year':  (first_this_year,  today),
        'Last Year':  (last_year_start,  last_year_end),
        'All Time':   (datetime(2000, 1, 1), today),
        'Custom':     None,
    }

    state = {'preset': 'This Month', 'from': first_this_month, 'to': today}

    with Session(engine) as s:
        all_invoices  = s.exec(select(Invoice).order_by(Invoice.date.desc())).all()
        all_customers = s.exec(select(Customer)).all()
    cust_map = {c.id: c.name for c in all_customers}

    # ── Helper: expandable report card ──
    def report_card(icon, title, description, color='indigo-600'):
        """Returns (card_container, content_area, toggle_fn)."""
        expanded = {'open': False}
        with ui.card().classes('w-full p-0 premium-card overflow-hidden') as card:
            with ui.row().classes('w-full items-center gap-4 p-5 cursor-pointer') as header:
                ui.icon(icon, color=color, size='24px')
                with ui.column().classes('flex-1'):
                    ui.label(title).classes('text-base font-bold text-slate-800 dark:text-slate-200')
                    ui.label(description).classes('text-xs text-slate-400')
                chevron = ui.icon('expand_more', size='24px', color='slate-400')
            content = ui.column().classes('w-full px-5 pb-5 gap-4')
            content.set_visibility(False)

        def toggle():
            expanded['open'] = not expanded['open']
            content.set_visibility(expanded['open'])
            chevron.name = 'expand_less' if expanded['open'] else 'expand_more'

        header.on('click', toggle)
        return content

    # ── Section header helper ──
    def section_header(title):
        ui.label(title).classes('text-xs font-black text-slate-400 uppercase tracking-widest mt-4 mb-1 px-1')

    # ── Report renderers ──
    def render_sales_summary(container, invoices):
        container.clear()
        paid_invs = [i for i in invoices if i.status == 'Paid']
        sent_invs = [i for i in invoices if i.status == 'Sent']
        canc_invs = [i for i in invoices if i.status == 'Cancelled']
        total_invoiced    = sum(i.total for i in invoices if i.status != 'Cancelled')
        total_paid        = sum(i.total for i in paid_invs)
        total_outstanding = sum(i.total for i in sent_invs)

        with container:
            with ui.row().classes('w-full gap-4'):
                for label, val, color, icon in [
                    ('Total Invoiced', total_invoiced,    'indigo-600',  'calculate'),
                    ('Collected',      total_paid,        'emerald-600', 'check_circle'),
                    ('Outstanding',    total_outstanding, 'amber-600',   'hourglass_top'),
                    ('Cancelled',      sum(i.total for i in canc_invs), 'red-400', 'cancel'),
                ]:
                    with ui.card().classes('flex-1 p-5 bg-slate-50 dark:bg-slate-800 rounded-xl'):
                        with ui.row().classes('items-center gap-2 mb-1'):
                            ui.icon(icon, color=color, size='16px')
                            ui.label(label).classes('text-[10px] font-black text-slate-400 uppercase tracking-widest')
                        ui.label(f'${val:,.2f}').classes('text-2xl font-black text-slate-900 dark:text-slate-100')

            cols = [
                {'name': 'num',      'label': '#',        'field': 'number',    'align': 'left'},
                {'name': 'cust',     'label': 'Client',   'field': 'cname',     'align': 'left'},
                {'name': 'date',     'label': 'Date',     'field': 'date_fmt',  'align': 'left'},
                {'name': 'status',   'label': 'Status',   'field': 'status',    'align': 'center'},
                {'name': 'subtotal', 'label': 'Subtotal', 'field': 'sub_fmt',   'align': 'right'},
                {'name': 'taxes',    'label': 'Taxes',    'field': 'tax_fmt',   'align': 'right'},
                {'name': 'total',    'label': 'Total',    'field': 'total_fmt', 'align': 'right'},
            ]
            rows = [{
                **i.model_dump(),
                'cname':     cust_map.get(i.customer_id, '?'),
                'date_fmt':  i.date.strftime('%Y-%m-%d'),
                'sub_fmt':   f'${i.subtotal:,.2f}',
                'tax_fmt':   f'${i.tax_total:,.2f}',
                'total_fmt': f'${i.total:,.2f}',
            } for i in invoices]
            if rows:
                t = ui.table(columns=cols, rows=rows, row_key='id').classes('w-full border-none shadow-none')
                t.add_slot('body-cell-status', '''<q-td :props="props"><q-badge :color="props.row.status === 'Paid' ? 'green' : (props.row.status === 'Sent' ? 'indigo' : (props.row.status === 'Cancelled' ? 'red' : 'amber'))" :style="{padding:'4px 12px',borderRadius:'999px',fontWeight:'700',fontSize:'10px'}">{{ props.row.status }}</q-badge></q-td>''')
            else:
                with ui.column().classes('w-full items-center p-8'):
                    ui.icon('search_off', size='40px', color='slate-300')
                    ui.label('No invoices in this period').classes('text-slate-400 text-sm mt-2')

    def render_revenue_trend(container, invoices):
        container.clear()
        paid = [i for i in invoices if i.status == 'Paid']
        monthly = defaultdict(float)
        for inv in paid:
            key = inv.date.strftime('%b %Y')
            monthly[key] += inv.total
        # Sort by date
        sorted_months = sorted(monthly.keys(), key=lambda m: datetime.strptime(m, '%b %Y'))
        vals = [monthly[m] for m in sorted_months]

        with container:
            if not sorted_months:
                with ui.column().classes('w-full items-center p-8'):
                    ui.icon('bar_chart', size='40px', color='slate-300')
                    ui.label('No paid invoices in this period').classes('text-slate-400 text-sm mt-2')
                return
            fig = go.Figure(go.Bar(
                x=sorted_months,
                y=vals,
                marker_color='#4f46e5',
                text=[f'${v:,.0f}' for v in vals],
                textposition='outside',
            ))
            fig.update_layout(
                margin=dict(t=20, b=20, l=20, r=20),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=False, tickfont=dict(size=11)),
                yaxis=dict(showgrid=True, gridcolor='#e2e8f0', tickprefix='$', tickfont=dict(size=11)),
                height=280,
            )
            ui.plotly(fig).classes('w-full')

    def render_tax_report(container, invoices):
        container.clear()
        paid_invs = [i for i in invoices if i.status == 'Paid']
        paid_subtotal   = sum(i.subtotal for i in paid_invs)
        tps_collected   = paid_subtotal * TPS_RATE
        tvq_collected   = paid_subtotal * TVQ_RATE

        with container:
            with ui.row().classes('w-full gap-4'):
                for label, val, sub, color in [
                    ('TPS Collected',   tps_collected,  f'5% on ${paid_subtotal:,.2f}',    'blue-600'),
                    ('TVQ Collected',   tvq_collected,  f'9.975% on ${paid_subtotal:,.2f}', 'purple-600'),
                    ('Total Taxes Due', tps_collected + tvq_collected, 'TPS + TVQ',         'emerald-600'),
                    ('Taxable Revenue', paid_subtotal,  f'{len(paid_invs)} paid invoices',  'indigo-600'),
                ]:
                    with ui.card().classes('flex-1 p-5 bg-slate-50 dark:bg-slate-800 rounded-xl'):
                        ui.label(label).classes('text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1')
                        ui.label(f'${val:,.2f}').classes('text-2xl font-black text-slate-900 dark:text-slate-100')
                        ui.label(sub).classes('text-xs text-slate-400 mt-1')

            tax_cols = [
                {'name': 'num',      'label': '#',            'field': 'number',   'align': 'left'},
                {'name': 'cust',     'label': 'Client',       'field': 'cname',    'align': 'left'},
                {'name': 'date',     'label': 'Date',         'field': 'date_fmt', 'align': 'left'},
                {'name': 'subtotal', 'label': 'Subtotal',     'field': 'sub_fmt',  'align': 'right'},
                {'name': 'tps',      'label': 'TPS (5%)',     'field': 'tps_fmt',  'align': 'right'},
                {'name': 'tvq',      'label': 'TVQ (9.975%)', 'field': 'tvq_fmt',  'align': 'right'},
                {'name': 'total',    'label': 'Total',        'field': 'total_fmt','align': 'right'},
            ]
            tax_rows = [{
                **i.model_dump(),
                'cname':     cust_map.get(i.customer_id, '?'),
                'date_fmt':  i.date.strftime('%Y-%m-%d'),
                'sub_fmt':   f'${i.subtotal:,.2f}',
                'tps_fmt':   f'${i.subtotal * TPS_RATE:,.2f}',
                'tvq_fmt':   f'${i.subtotal * TVQ_RATE:,.2f}',
                'total_fmt': f'${i.total:,.2f}',
            } for i in paid_invs]
            if tax_rows:
                ui.table(columns=tax_cols, rows=tax_rows, row_key='id').classes('w-full border-none shadow-none')
            else:
                with ui.column().classes('w-full items-center p-8'):
                    ui.icon('receipt_long', size='40px', color='slate-300')
                    ui.label('No paid invoices in this period').classes('text-slate-400 text-sm mt-2')

    def render_income_by_customer(container, invoices):
        container.clear()
        paid_invs = [i for i in invoices if i.status == 'Paid']
        by_cust = defaultdict(lambda: {'count': 0, 'subtotal': 0.0, 'taxes': 0.0, 'total': 0.0})
        for inv in paid_invs:
            cname = cust_map.get(inv.customer_id, 'Unknown')
            by_cust[cname]['count']    += 1
            by_cust[cname]['subtotal'] += inv.subtotal
            by_cust[cname]['taxes']    += inv.tax_total
            by_cust[cname]['total']    += inv.total

        with container:
            if not by_cust:
                with ui.column().classes('w-full items-center p-8'):
                    ui.icon('group', size='40px', color='slate-300')
                    ui.label('No paid invoices in this period').classes('text-slate-400 text-sm mt-2')
                return

            sorted_custs = sorted(by_cust.items(), key=lambda x: x[1]['total'], reverse=True)

            with ui.row().classes('w-full gap-6 items-start'):
                # Table
                with ui.column().classes('flex-1'):
                    cols = [
                        {'name': 'cust',     'label': 'Customer',    'field': 'cust',        'align': 'left'},
                        {'name': 'count',    'label': '# Invoices',  'field': 'count',       'align': 'center'},
                        {'name': 'subtotal', 'label': 'Subtotal',    'field': 'sub_fmt',     'align': 'right'},
                        {'name': 'taxes',    'label': 'Taxes',       'field': 'tax_fmt',     'align': 'right'},
                        {'name': 'total',    'label': 'Total Paid',  'field': 'total_fmt',   'align': 'right'},
                    ]
                    rows = [{
                        'cust':      name,
                        'count':     data['count'],
                        'sub_fmt':   f'${data["subtotal"]:,.2f}',
                        'tax_fmt':   f'${data["taxes"]:,.2f}',
                        'total_fmt': f'${data["total"]:,.2f}',
                    } for name, data in sorted_custs]
                    tbl = ui.table(columns=cols, rows=rows, row_key='cust').classes('w-full border-none shadow-none')
                    tbl.add_slot('body-cell-total', '''<q-td :props="props"><span class="font-bold text-indigo-600">{{ props.row.total_fmt }}</span></q-td>''')

                # Donut chart
                with ui.column().classes('w-72 shrink-0'):
                    labels = [name for name, _ in sorted_custs]
                    values = [data['total'] for _, data in sorted_custs]
                    fig = go.Figure(go.Pie(
                        labels=labels, values=values,
                        hole=0.55,
                        marker_colors=['#4f46e5', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
                        textinfo='percent',
                        hovertemplate='%{label}: $%{value:,.2f}<extra></extra>',
                    ))
                    fig.update_layout(
                        margin=dict(t=10, b=10, l=10, r=10),
                        paper_bgcolor='rgba(0,0,0,0)',
                        showlegend=True,
                        legend=dict(font=dict(size=11)),
                        height=240,
                    )
                    ui.plotly(fig).classes('w-full')

    def render_aged_receivables(container, invoices):
        container.clear()
        unpaid = [i for i in invoices if i.status in ('Sent', 'Overdue')]

        buckets = {'Current (0–30d)': [], '31–60d': [], '61–90d': [], '90d+': []}

        for inv in unpaid:
            ref_date = inv.due_date or inv.date
            age = (today - ref_date).days
            if age <= 30:
                buckets['Current (0–30d)'].append(inv)
            elif age <= 60:
                buckets['31–60d'].append(inv)
            elif age <= 90:
                buckets['61–90d'].append(inv)
            else:
                buckets['90d+'].append(inv)

        bucket_colors = {
            'Current (0–30d)': 'emerald-600',
            '31–60d':          'amber-500',
            '61–90d':          'orange-500',
            '90d+':            'red-600',
        }

        with container:
            # KPI chips
            with ui.row().classes('w-full gap-4 mb-4'):
                for bucket, invs in buckets.items():
                    total = sum(i.total for i in invs)
                    color = bucket_colors[bucket]
                    with ui.card().classes('flex-1 p-4 bg-slate-50 dark:bg-slate-800 rounded-xl'):
                        ui.label(bucket).classes(f'text-[10px] font-black text-{color} uppercase tracking-widest mb-1')
                        ui.label(f'${total:,.2f}').classes('text-xl font-black text-slate-900 dark:text-slate-100')
                        ui.label(f'{len(invs)} invoice{"s" if len(invs) != 1 else ""}').classes('text-xs text-slate-400')

            if not unpaid:
                with ui.column().classes('w-full items-center p-8'):
                    ui.icon('check_circle', size='40px', color='emerald-400')
                    ui.label('No outstanding invoices').classes('text-slate-400 text-sm mt-2')
                return

            # Flat table with all unpaid invoices + age bucket column
            all_rows = []
            for bucket, invs in buckets.items():
                for inv in invs:
                    ref_date = inv.due_date or inv.date
                    age = (today - ref_date).days
                    all_rows.append({
                        **inv.model_dump(),
                        'cname':      cust_map.get(inv.customer_id, '?'),
                        'date_fmt':   inv.date.strftime('%Y-%m-%d'),
                        'due_fmt':    inv.due_date.strftime('%Y-%m-%d') if inv.due_date else '—',
                        'age_days':   age,
                        'bucket':     bucket,
                        'total_fmt':  f'${inv.total:,.2f}',
                    })

            cols = [
                {'name': 'num',    'label': '#',          'field': 'number',   'align': 'left'},
                {'name': 'cust',   'label': 'Client',     'field': 'cname',    'align': 'left'},
                {'name': 'date',   'label': 'Invoice Date','field': 'date_fmt','align': 'left'},
                {'name': 'due',    'label': 'Due Date',   'field': 'due_fmt',  'align': 'left'},
                {'name': 'age',    'label': 'Days Old',   'field': 'age_days', 'align': 'center'},
                {'name': 'bucket', 'label': 'Bucket',     'field': 'bucket',   'align': 'center'},
                {'name': 'total',  'label': 'Total Due',  'field': 'total_fmt','align': 'right'},
            ]
            tbl = ui.table(columns=cols, rows=all_rows, row_key='id').classes('w-full border-none shadow-none')
            tbl.add_slot('body-cell-bucket', '''
                <q-td :props="props">
                  <q-badge
                    :color="props.row.bucket === 'Current (0–30d)' ? 'green' : (props.row.bucket === '31–60d' ? 'amber' : (props.row.bucket === '61–90d' ? 'orange' : 'red'))"
                    :style="{padding:'3px 10px',borderRadius:'999px',fontWeight:'700',fontSize:'10px'}">
                    {{ props.row.bucket }}
                  </q-badge>
                </q-td>''')

    # ── Page layout ──
    def apply_filter():
        d_from = state['from']
        d_to   = state['to'].replace(hour=23, minute=59, second=59)
        filtered = [i for i in all_invoices if d_from <= i.date <= d_to]

        # Re-populate all report content areas
        render_sales_summary(sales_content, filtered)
        render_revenue_trend(trend_content, filtered)
        render_tax_report(tax_content, filtered)
        render_income_by_customer(cust_content, filtered)
        render_aged_receivables(aged_content, all_invoices)  # aged uses full list

    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        ui.label('Reports').classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-2')
        ui.label('Financial reports for any period').classes('text-slate-400 text-base mb-6')

        # ── Date filter ──
        preset_btns = {}

        with ui.card().classes('w-full p-6 premium-card mb-6'):
            def set_preset(name):
                state['preset'] = name
                for n, btn in preset_btns.items():
                    btn.classes(replace='btn-primary h-9 rounded-lg px-4 text-sm' if n == name
                                else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300')
                if name != 'Custom':
                    d_from, d_to = PRESETS[name]
                    state['from'] = d_from
                    state['to']   = d_to
                    custom_row.set_visibility(False)
                    apply_filter()
                else:
                    custom_row.set_visibility(True)

            with ui.row().classes('items-center gap-3 flex-wrap'):
                ui.label('Period:').classes('text-sm font-semibold text-slate-500 mr-2')
                for name in PRESETS:
                    is_active = name == state['preset']
                    cls = 'btn-primary h-9 rounded-lg px-4 text-sm' if is_active else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                    btn = ui.button(name, on_click=lambda n=name: set_preset(n)).classes(cls)
                    preset_btns[name] = btn

            with ui.row().classes('items-center gap-4 mt-3') as custom_row:
                custom_row.set_visibility(False)
                from_input = ui.input('From', value=state['from'].strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                to_input   = ui.input('To',   value=state['to'].strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                def apply_custom():
                    try:
                        state['from'] = datetime.strptime(from_input.value, '%Y-%m-%d')
                        state['to']   = datetime.strptime(to_input.value,   '%Y-%m-%d')
                        apply_filter()
                    except ValueError:
                        ui.notify('Invalid date format. Use YYYY-MM-DD', color='red-500')
                ui.button('Apply', on_click=apply_custom).classes('btn-primary h-9 rounded-lg px-5 text-sm')

        # ── SECTION: Income ──
        section_header('Income')
        sales_content  = report_card('receipt_long',  'Sales Summary',          'Total invoiced, collected, and outstanding for the period')
        trend_content  = report_card('bar_chart',     'Monthly Revenue Trend',  'Paid revenue per month — bar chart', color='emerald-600')

        # ── SECTION: Taxes ──
        section_header('Taxes')
        tax_content    = report_card('account_balance', 'Sales Tax Report (TPS/TVQ)', 'TPS & TVQ collected on paid invoices', color='blue-600')

        # ── SECTION: Customers ──
        section_header('Customers')
        cust_content   = report_card('group',        'Income by Customer',  'Revenue breakdown per client', color='purple-600')
        aged_content   = report_card('hourglass_top','Aged Receivables',    'Unpaid invoices grouped by age (30/60/90 days)', color='amber-600')

        # Initial render
        apply_filter()
```

**Step 4: Verify manually**

- Reports page loads showing 5 collapsed cards in 3 sections
- Clicking each card expands/collapses it
- Sales Summary matches previous behavior
- Changing date preset re-renders all expanded cards
- Aged Receivables shows correct bucket totals

**Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat: redesign reports page as hub with expandable cards and 3 new reports"
```

---

## Task 4: Final Verification

**Step 1: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: all pass

**Step 2: Smoke test the app**

```bash
uv run python app/main.py
```

Check:
- [ ] Sidebar shows: Dashboard, Invoices, Subscription, Customers, Services, Accounts, **Expenses**, Reports, Settings
- [ ] `/expenses` — add an expense, verify TPS/TVQ auto-calculate, verify it appears in table
- [ ] `/expenses` — switch period filter, verify table updates
- [ ] `/reports` — all 5 cards expand/collapse
- [ ] `/reports` — Sales Summary KPIs and table render
- [ ] `/reports` — Monthly Revenue Trend shows a bar chart (with seed data)
- [ ] `/reports` — Sales Tax Report KPIs render
- [ ] `/reports` — Income by Customer shows table + donut chart
- [ ] `/reports` — Aged Receivables shows bucket KPIs + table

**Step 3: Final commit**

```bash
git add .
git commit -m "feat: expenses tracking + reports hub complete"
```
