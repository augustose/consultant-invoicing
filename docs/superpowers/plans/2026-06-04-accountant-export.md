# Accountant Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an accountant export flow that downloads a date-scoped CSV ZIP with an HTML summary report, plus an optional structured Audit XML export.

**Architecture:** Put testable export logic in a new `app/export_utils.py` module that accepts an explicit SQLModel session and returns generated files under `data/exports/`. Keep `app/main.py` responsible only for the Reports-page dialog and download action. Use standard-library `csv`, `json`, `zipfile`, `html`, and `xml.etree.ElementTree`; no new dependencies.

**Tech Stack:** Python 3.11, NiceGUI, SQLModel, SQLite, pytest, standard-library ZIP/XML/CSV helpers.

---

## File Structure

- Create `app/export_utils.py`: accountant export data gathering, CSV row formatting, HTML report rendering, Audit XML rendering, and ZIP/file generation.
- Modify `app/main.py`: import export helpers and add an "Export for Accountant" dialog to `/reports`.
- Create `tests/test_accountant_export.py`: in-memory SQLModel tests for dataset filtering, CSV ZIP contents, optional invoice items, empty period exports, and Audit XML shape.

## Task 1: Export Dataset and Summary

**Files:**
- Create: `tests/test_accountant_export.py`
- Create: `app/export_utils.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_accountant_export.py` with:

```python
import csv
import io
import sys
from datetime import datetime
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from database import Account, AccountType, CompanySettings, Customer, Expense, Invoice, InvoiceItem, Service  # noqa: E402
from export_utils import build_accountant_export_context, rows_to_csv_text  # noqa: E402


def make_session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)

    settings = CompanySettings(
        legal_name="Augusto Sosa Escalada (Mac)",
        address="1464 Frontenac\nMontreal, QC",
        phone="5148853146",
        email="augustose@example.com",
        neq="NEQ-123",
        tps_number="717569891 RT 0001",
        tvq_number="4023119175 TQ 0002",
        currency="CAD",
    )
    income_account = Account(code="4000", name="Consulting Revenue", type=AccountType.INCOME, is_system=True)
    expense_account = Account(code="5000", name="Software & Subscriptions", type=AccountType.EXPENSE)
    inactive_account = Account(code="5100", name="Inactive Travel", type=AccountType.EXPENSE, is_active=False)
    customer = Customer(
        name="Cafe Parvis",
        contact="Alejandra Ponce",
        email="alejandra@example.com",
        phone="514 775 5234",
        address="433 Rue Mayor",
        currency="CAD",
    )
    outside_customer = Customer(name="Outside Client", email="outside@example.com", currency="CAD")
    service = Service(name="IT Consulting", description="Monthly support", unit_price=600.0)
    session.add_all([settings, income_account, expense_account, inactive_account, customer, outside_customer, service])
    session.commit()
    for obj in [expense_account, customer, outside_customer, service]:
        session.refresh(obj)

    paid_invoice = Invoice(
        number="100123",
        date=datetime(2026, 1, 15),
        due_date=datetime(2026, 1, 31),
        customer_id=customer.id,
        status="Paid",
        subtotal=600.0,
        tax_total=89.85,
        total=689.85,
        notes="January support",
    )
    sent_invoice = Invoice(
        number="100124",
        date=datetime(2026, 2, 10),
        customer_id=customer.id,
        status="Sent",
        subtotal=400.0,
        tax_total=59.9,
        total=459.9,
    )
    outside_invoice = Invoice(
        number="100099",
        date=datetime(2025, 12, 20),
        customer_id=outside_customer.id,
        status="Paid",
        subtotal=999.0,
        tax_total=149.6,
        total=1148.6,
    )
    expense = Expense(
        date=datetime(2026, 1, 20),
        description="Accounting software",
        amount=100.0,
        tps=5.0,
        tvq=9.98,
        total=114.98,
        account_id=expense_account.id,
        notes="Monthly subscription",
    )
    outside_expense = Expense(
        date=datetime(2025, 12, 1),
        description="Old expense",
        amount=200.0,
        total=200.0,
        account_id=expense_account.id,
    )
    session.add_all([paid_invoice, sent_invoice, outside_invoice, expense, outside_expense])
    session.commit()
    for obj in [paid_invoice, sent_invoice, service]:
        session.refresh(obj)

    session.add(
        InvoiceItem(
            invoice_id=paid_invoice.id,
            service_id=service.id,
            description="IT Consulting\nMonthly support",
            quantity=1,
            unit_price=600.0,
            total=600.0,
        )
    )
    session.commit()
    return session


def parse_csv(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_build_context_filters_invoices_expenses_and_customers_by_period():
    session = make_session()

    context = build_accountant_export_context(
        session=session,
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
        include_invoice_items=False,
    )

    assert [row["invoice_number"] for row in context.invoices] == ["100123"]
    assert [row["description"] for row in context.expenses] == ["Accounting software"]
    assert [row["name"] for row in context.customers] == ["Cafe Parvis"]
    assert [row["code"] for row in context.accounts] == ["4000", "5000", "5100"]
    assert context.invoice_items == []
    assert context.summary["invoice_count"] == "1"
    assert context.summary["paid_invoice_count"] == "1"
    assert context.summary["paid_total"] == "689.85"
    assert context.summary["expense_total"] == "114.98"
    assert context.summary["net_before_taxes"] == "500.00"


def test_context_includes_invoice_items_only_when_requested():
    session = make_session()

    without_items = build_accountant_export_context(
        session=session,
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
        include_invoice_items=False,
    )
    with_items = build_accountant_export_context(
        session=session,
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
        include_invoice_items=True,
    )

    assert without_items.invoice_items == []
    assert with_items.invoice_items == [
        {
            "invoice_number": "100123",
            "invoice_date": "2026-01-15",
            "customer_name": "Cafe Parvis",
            "service_id": "1",
            "description": "IT Consulting\nMonthly support",
            "quantity": "1.00",
            "unit_price": "600.00",
            "line_total": "600.00",
        }
    ]


def test_rows_to_csv_text_writes_headers_and_decimal_strings():
    csv_text = rows_to_csv_text(
        ["invoice_number", "total"],
        [{"invoice_number": "100123", "total": "689.85"}],
    )

    assert parse_csv(csv_text) == [{"invoice_number": "100123", "total": "689.85"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_accountant_export.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'export_utils'`.

- [ ] **Step 3: Create the minimal export dataset implementation**

Create `app/export_utils.py` with:

```python
from dataclasses import dataclass
from datetime import datetime
import csv
import io
from typing import Iterable

from sqlmodel import Session, select

from database import Account, CompanySettings, Customer, Expense, Invoice, InvoiceItem

TPS_RATE = 0.05
TVQ_RATE = 0.09975


@dataclass
class AccountantExportContext:
    start_date: datetime
    end_date: datetime
    generated_at: datetime
    company: dict[str, str]
    summary: dict[str, str]
    invoices: list[dict[str, str]]
    expenses: list[dict[str, str]]
    tax_report: list[dict[str, str]]
    customers: list[dict[str, str]]
    accounts: list[dict[str, str]]
    invoice_items: list[dict[str, str]]
    include_invoice_items: bool


def money(value: float | int | None) -> str:
    return f"{float(value or 0):.2f}"


def text(value) -> str:
    return "" if value is None else str(value)


def day(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def rows_to_csv_text(headers: list[str], rows: Iterable[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def inclusive_end(end_date: datetime) -> datetime:
    return end_date.replace(hour=23, minute=59, second=59, microsecond=999999)


def company_dict(settings: CompanySettings | None) -> dict[str, str]:
    if not settings:
        return {
            "legal_name": "",
            "address": "",
            "phone": "",
            "email": "",
            "neq": "",
            "tps_number": "",
            "tvq_number": "",
            "currency": "CAD",
        }
    return {
        "legal_name": text(settings.legal_name),
        "address": text(settings.address),
        "phone": text(settings.phone),
        "email": text(settings.email),
        "neq": text(settings.neq),
        "tps_number": text(settings.tps_number),
        "tvq_number": text(settings.tvq_number),
        "currency": text(settings.currency or "CAD"),
    }


def build_accountant_export_context(
    session: Session,
    start_date: datetime,
    end_date: datetime,
    include_invoice_items: bool = False,
    generated_at: datetime | None = None,
) -> AccountantExportContext:
    generated_at = generated_at or datetime.utcnow()
    end_bound = inclusive_end(end_date)
    settings = session.exec(select(CompanySettings)).first()
    company = company_dict(settings)

    invoices = session.exec(
        select(Invoice).where(Invoice.date >= start_date, Invoice.date <= end_bound).order_by(Invoice.date, Invoice.number)
    ).all()
    expenses = session.exec(
        select(Expense).where(Expense.date >= start_date, Expense.date <= end_bound).order_by(Expense.date, Expense.id)
    ).all()
    customers = session.exec(select(Customer).order_by(Customer.name)).all()
    accounts = session.exec(select(Account).order_by(Account.code)).all()
    invoice_ids = [invoice.id for invoice in invoices if invoice.id is not None]
    customer_ids = {invoice.customer_id for invoice in invoices}
    customer_map = {customer.id: customer for customer in customers}
    account_map = {account.id: account for account in accounts}

    paid_invoices = [invoice for invoice in invoices if invoice.status == "Paid"]
    tps_collected = sum(invoice.subtotal * TPS_RATE for invoice in paid_invoices)
    tvq_collected = sum(invoice.subtotal * TVQ_RATE for invoice in paid_invoices)
    expense_tps = sum(expense.tps for expense in expenses)
    expense_tvq = sum(expense.tvq for expense in expenses)

    invoice_rows = []
    for invoice in invoices:
        customer = customer_map.get(invoice.customer_id)
        invoice_rows.append(
            {
                "invoice_number": text(invoice.number),
                "invoice_date": day(invoice.date),
                "due_date": day(invoice.due_date),
                "customer_name": text(customer.name if customer else ""),
                "customer_email": text(customer.email if customer else ""),
                "status": text(invoice.status),
                "subtotal": money(invoice.subtotal),
                "tps": money(invoice.subtotal * TPS_RATE),
                "tvq": money(invoice.subtotal * TVQ_RATE),
                "tax_total": money(invoice.tax_total),
                "total": money(invoice.total),
                "notes": text(invoice.notes),
            }
        )

    expense_rows = []
    for expense in expenses:
        account = account_map.get(expense.account_id)
        expense_rows.append(
            {
                "date": day(expense.date),
                "description": text(expense.description),
                "account_code": text(account.code if account else ""),
                "account_name": text(account.name if account else ""),
                "subtotal": money(expense.amount),
                "tps": money(expense.tps),
                "tvq": money(expense.tvq),
                "total": money(expense.total),
                "notes": text(expense.notes),
            }
        )

    used_customers = [customer for customer in customers if customer.id in customer_ids]
    customer_rows = [
        {
            "name": text(customer.name),
            "contact": text(customer.contact),
            "email": text(customer.email),
            "phone": text(customer.phone),
            "address": text(customer.address),
            "currency": text(customer.currency),
        }
        for customer in used_customers
    ]
    account_rows = [
        {
            "code": text(account.code),
            "name": text(account.name),
            "type": text(account.type.value if hasattr(account.type, "value") else account.type),
            "description": text(account.description),
            "is_active": "true" if account.is_active else "false",
            "is_system": "true" if account.is_system else "false",
        }
        for account in accounts
    ]

    item_rows: list[dict[str, str]] = []
    if include_invoice_items and invoice_ids:
        items = session.exec(select(InvoiceItem).where(InvoiceItem.invoice_id.in_(invoice_ids)).order_by(InvoiceItem.invoice_id, InvoiceItem.id)).all()
        invoice_map = {invoice.id: invoice for invoice in invoices}
        for item in items:
            invoice = invoice_map.get(item.invoice_id)
            customer = customer_map.get(invoice.customer_id) if invoice else None
            item_rows.append(
                {
                    "invoice_number": text(invoice.number if invoice else ""),
                    "invoice_date": day(invoice.date if invoice else None),
                    "customer_name": text(customer.name if customer else ""),
                    "service_id": text(item.service_id),
                    "description": text(item.description),
                    "quantity": money(item.quantity),
                    "unit_price": money(item.unit_price),
                    "line_total": money(item.total),
                }
            )

    summary = {
        "period_start": day(start_date),
        "period_end": day(end_date),
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "currency": company["currency"] or "CAD",
        "invoice_count": str(len(invoices)),
        "paid_invoice_count": str(len(paid_invoices)),
        "sent_invoice_count": str(len([invoice for invoice in invoices if invoice.status == "Sent"])),
        "cancelled_invoice_count": str(len([invoice for invoice in invoices if invoice.status == "Cancelled"])),
        "expense_count": str(len(expenses)),
        "invoiced_subtotal": money(sum(invoice.subtotal for invoice in invoices)),
        "invoiced_tax_total": money(sum(invoice.tax_total for invoice in invoices)),
        "invoiced_total": money(sum(invoice.total for invoice in invoices)),
        "paid_subtotal": money(sum(invoice.subtotal for invoice in paid_invoices)),
        "paid_tax_total": money(sum(invoice.tax_total for invoice in paid_invoices)),
        "paid_total": money(sum(invoice.total for invoice in paid_invoices)),
        "expense_subtotal": money(sum(expense.amount for expense in expenses)),
        "expense_tps": money(expense_tps),
        "expense_tvq": money(expense_tvq),
        "expense_total": money(sum(expense.total for expense in expenses)),
        "net_before_taxes": money(sum(invoice.subtotal for invoice in paid_invoices) - sum(expense.amount for expense in expenses)),
    }
    tax_report = [
        {"metric": "TPS collected from paid invoices", "amount": money(tps_collected)},
        {"metric": "TVQ collected from paid invoices", "amount": money(tvq_collected)},
        {"metric": "TPS recorded on expenses", "amount": money(expense_tps)},
        {"metric": "TVQ recorded on expenses", "amount": money(expense_tvq)},
        {"metric": "Net TPS payable estimate", "amount": money(tps_collected - expense_tps)},
        {"metric": "Net TVQ payable estimate", "amount": money(tvq_collected - expense_tvq)},
    ]
    return AccountantExportContext(
        start_date=start_date,
        end_date=end_date,
        generated_at=generated_at,
        company=company,
        summary=summary,
        invoices=invoice_rows,
        expenses=expense_rows,
        tax_report=tax_report,
        customers=customer_rows,
        accounts=account_rows,
        invoice_items=item_rows,
        include_invoice_items=include_invoice_items,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_accountant_export.py -q
```

Expected: PASS for the three tests in this task.

- [ ] **Step 5: Commit**

```bash
git add app/export_utils.py tests/test_accountant_export.py
git commit -m "Add accountant export dataset builder"
```

## Task 2: CSV ZIP and HTML Report

**Files:**
- Modify: `tests/test_accountant_export.py`
- Modify: `app/export_utils.py`

- [ ] **Step 1: Write failing ZIP tests**

Append these imports and tests to `tests/test_accountant_export.py`:

```python
import json
import zipfile

from export_utils import create_accountant_csv_zip  # noqa: E402


def test_create_csv_zip_contains_report_manifest_and_core_csv_files(tmp_path):
    session = make_session()

    zip_path = create_accountant_csv_zip(
        session=session,
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
        include_invoice_items=False,
        export_dir=tmp_path,
    )

    assert zip_path.name == "accountant_export_2026-01-01_to_2026-01-31.zip"
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(archive.namelist())
        assert names == [
            "accountant_report.html",
            "chart_of_accounts.csv",
            "customers.csv",
            "expenses.csv",
            "invoices.csv",
            "manifest.json",
            "summary.csv",
            "tax_report.csv",
        ]
        html = archive.read("accountant_report.html").decode("utf-8")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        invoices = parse_csv(archive.read("invoices.csv").decode("utf-8"))

    assert "https://cdn.tailwindcss.com" in html
    assert "Augusto Sosa Escalada (Mac)" in html
    assert "2026-01-01 to 2026-01-31" in html
    assert "Files included" in html
    assert manifest["format"] == "csv_zip"
    assert manifest["include_invoice_items"] is False
    assert manifest["files"] == [
        "accountant_report.html",
        "summary.csv",
        "invoices.csv",
        "expenses.csv",
        "tax_report.csv",
        "customers.csv",
        "chart_of_accounts.csv",
        "manifest.json",
    ]
    assert invoices[0]["invoice_number"] == "100123"


def test_csv_zip_includes_invoice_items_when_requested(tmp_path):
    session = make_session()

    zip_path = create_accountant_csv_zip(
        session=session,
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
        include_invoice_items=True,
        export_dir=tmp_path,
    )

    with zipfile.ZipFile(zip_path) as archive:
        assert "invoice_items.csv" in archive.namelist()
        invoice_items = parse_csv(archive.read("invoice_items.csv").decode("utf-8"))
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert invoice_items[0]["description"] == "IT Consulting\nMonthly support"
    assert manifest["include_invoice_items"] is True
    assert "invoice_items.csv" in manifest["files"]


def test_empty_csv_zip_still_contains_report_and_headers(tmp_path):
    session = make_session()

    zip_path = create_accountant_csv_zip(
        session=session,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 31),
        include_invoice_items=False,
        export_dir=tmp_path,
    )

    with zipfile.ZipFile(zip_path) as archive:
        html = archive.read("accountant_report.html").decode("utf-8")
        invoices_csv = archive.read("invoices.csv").decode("utf-8")

    assert "No invoices or expenses were found for this period." in html
    assert invoices_csv.startswith("invoice_number,invoice_date,due_date")
```

- [ ] **Step 2: Run ZIP tests to verify they fail**

Run:

```bash
uv run pytest tests/test_accountant_export.py::test_create_csv_zip_contains_report_manifest_and_core_csv_files tests/test_accountant_export.py::test_csv_zip_includes_invoice_items_when_requested tests/test_accountant_export.py::test_empty_csv_zip_still_contains_report_and_headers -q
```

Expected: FAIL with `ImportError` or `AttributeError` because `create_accountant_csv_zip` does not exist.

- [ ] **Step 3: Implement CSV ZIP generation and HTML report**

Add this to `app/export_utils.py`:

```python
import html
import json
from pathlib import Path
import zipfile

SUMMARY_HEADERS = [
    "period_start", "period_end", "generated_at", "currency",
    "invoice_count", "paid_invoice_count", "sent_invoice_count", "cancelled_invoice_count",
    "expense_count", "invoiced_subtotal", "invoiced_tax_total", "invoiced_total",
    "paid_subtotal", "paid_tax_total", "paid_total",
    "expense_subtotal", "expense_tps", "expense_tvq", "expense_total", "net_before_taxes",
]
INVOICE_HEADERS = ["invoice_number", "invoice_date", "due_date", "customer_name", "customer_email", "status", "subtotal", "tps", "tvq", "tax_total", "total", "notes"]
EXPENSE_HEADERS = ["date", "description", "account_code", "account_name", "subtotal", "tps", "tvq", "total", "notes"]
TAX_HEADERS = ["metric", "amount"]
CUSTOMER_HEADERS = ["name", "contact", "email", "phone", "address", "currency"]
ACCOUNT_HEADERS = ["code", "name", "type", "description", "is_active", "is_system"]
INVOICE_ITEM_HEADERS = ["invoice_number", "invoice_date", "customer_name", "service_id", "description", "quantity", "unit_price", "line_total"]


def export_filename(prefix: str, start_date: datetime, end_date: datetime, suffix: str) -> str:
    return f"{prefix}_{day(start_date)}_to_{day(end_date)}.{suffix}"


def render_accountant_html_report(context: AccountantExportContext, files: list[str]) -> str:
    summary = context.summary
    no_activity = summary["invoice_count"] == "0" and summary["expense_count"] == "0"
    file_rows = "\n".join(
        f"<tr><td class='px-3 py-2 font-mono text-xs'>{html.escape(name)}</td><td class='px-3 py-2'>{html.escape(file_description(name))}</td></tr>"
        for name in files
    )
    empty_note = (
        "<p class='rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800'>"
        "No invoices or expenses were found for this period.</p>"
        if no_activity else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>
  <title>Accountant Export Report</title>
</head>
<body class="bg-slate-50 text-slate-900">
  <main class="mx-auto max-w-5xl px-8 py-10">
    <section class="mb-8">
      <p class="text-xs font-bold uppercase tracking-widest text-indigo-600">Accountant Export</p>
      <h1 class="mt-2 text-3xl font-black">{html.escape(context.company["legal_name"] or "Business")}</h1>
      <p class="mt-2 text-sm text-slate-500">{html.escape(summary["period_start"])} to {html.escape(summary["period_end"])} · Generated {html.escape(summary["generated_at"])}</p>
    </section>
    {empty_note}
    <section class="grid grid-cols-2 gap-4 md:grid-cols-4">
      {metric_card("Paid Revenue", summary["paid_total"], summary["currency"])}
      {metric_card("Expenses", summary["expense_total"], summary["currency"])}
      {metric_card("Net Before Taxes", summary["net_before_taxes"], summary["currency"])}
      {metric_card("Invoices", summary["invoice_count"], "")}
    </section>
    <section class="mt-8 grid gap-4 md:grid-cols-3">
      {metric_card("TPS on Paid Invoices", context.tax_report[0]["amount"], summary["currency"])}
      {metric_card("TVQ on Paid Invoices", context.tax_report[1]["amount"], summary["currency"])}
      {metric_card("Expense Count", summary["expense_count"], "")}
    </section>
    <section class="mt-10 rounded-lg bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <h2 class="text-lg font-bold">Files included</h2>
      <table class="mt-4 w-full text-left text-sm">
        <tbody class="divide-y divide-slate-100">{file_rows}</tbody>
      </table>
      <p class="mt-5 text-xs text-slate-500">CSV files are the primary accountant-friendly interchange format. They may be imported or reviewed manually depending on the accountant's software.</p>
    </section>
  </main>
</body>
</html>
"""


def metric_card(label: str, value: str, currency: str) -> str:
    display = f"{currency} {value}" if currency else value
    return f"<div class='rounded-lg bg-white p-5 shadow-sm ring-1 ring-slate-200'><p class='text-xs font-bold uppercase tracking-widest text-slate-400'>{html.escape(label)}</p><p class='mt-2 text-2xl font-black'>{html.escape(display)}</p></div>"


def file_description(name: str) -> str:
    descriptions = {
        "accountant_report.html": "Human-readable summary and index for this export.",
        "summary.csv": "One-row period summary with income, expense, net, and count totals.",
        "invoices.csv": "Invoice-level rows for the selected period.",
        "expenses.csv": "Expense rows with account and tax details.",
        "tax_report.csv": "TPS and TVQ collected, recorded, and estimated payable values.",
        "customers.csv": "Customers referenced by exported invoices.",
        "chart_of_accounts.csv": "Full chart of accounts for accountant mapping.",
        "invoice_items.csv": "Optional line-item detail for exported invoices.",
        "manifest.json": "Machine-readable metadata about files and export settings.",
    }
    return descriptions.get(name, "Exported data file.")


def build_csv_files(context: AccountantExportContext) -> dict[str, str]:
    files = {
        "summary.csv": rows_to_csv_text(SUMMARY_HEADERS, [context.summary]),
        "invoices.csv": rows_to_csv_text(INVOICE_HEADERS, context.invoices),
        "expenses.csv": rows_to_csv_text(EXPENSE_HEADERS, context.expenses),
        "tax_report.csv": rows_to_csv_text(TAX_HEADERS, context.tax_report),
        "customers.csv": rows_to_csv_text(CUSTOMER_HEADERS, context.customers),
        "chart_of_accounts.csv": rows_to_csv_text(ACCOUNT_HEADERS, context.accounts),
    }
    if context.include_invoice_items:
        files["invoice_items.csv"] = rows_to_csv_text(INVOICE_ITEM_HEADERS, context.invoice_items)
    return files


def create_accountant_csv_zip(
    session: Session,
    start_date: datetime,
    end_date: datetime,
    include_invoice_items: bool = False,
    export_dir: str | Path = "data/exports",
) -> Path:
    context = build_accountant_export_context(session, start_date, end_date, include_invoice_items)
    csv_files = build_csv_files(context)
    file_order = ["accountant_report.html", *csv_files.keys(), "manifest.json"]
    manifest = {
        "format": "csv_zip",
        "period_start": context.summary["period_start"],
        "period_end": context.summary["period_end"],
        "generated_at": context.summary["generated_at"],
        "currency": context.summary["currency"],
        "include_invoice_items": include_invoice_items,
        "files": file_order,
        "counts": {
            "invoices": len(context.invoices),
            "expenses": len(context.expenses),
            "customers": len(context.customers),
            "accounts": len(context.accounts),
            "invoice_items": len(context.invoice_items),
        },
    }
    report = render_accountant_html_report(context, file_order)
    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)
    zip_path = export_path / export_filename("accountant_export", start_date, end_date, "zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("accountant_report.html", report)
        for filename, content in csv_files.items():
            archive.writestr(filename, content)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    return zip_path
```

- [ ] **Step 4: Run ZIP tests to verify they pass**

Run:

```bash
uv run pytest tests/test_accountant_export.py -q
```

Expected: PASS for dataset and ZIP tests.

- [ ] **Step 5: Commit**

```bash
git add app/export_utils.py tests/test_accountant_export.py
git commit -m "Add accountant CSV ZIP export"
```

## Task 3: Audit XML Export

**Files:**
- Modify: `tests/test_accountant_export.py`
- Modify: `app/export_utils.py`

- [ ] **Step 1: Write failing XML tests**

Append this import and test to `tests/test_accountant_export.py`:

```python
import xml.etree.ElementTree as ET

from export_utils import create_accountant_audit_xml  # noqa: E402


def test_create_audit_xml_exports_structured_period_data(tmp_path):
    session = make_session()

    xml_path = create_accountant_audit_xml(
        session=session,
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
        include_invoice_items=True,
        export_dir=tmp_path,
    )

    assert xml_path.name == "accountant_audit_2026-01-01_to_2026-01-31.xml"
    root = ET.parse(xml_path).getroot()

    assert root.tag == "accountant_export"
    assert root.findtext("metadata/format") == "audit_xml"
    assert root.findtext("company/legal_name") == "Augusto Sosa Escalada (Mac)"
    assert root.findtext("period/start_date") == "2026-01-01"
    assert root.findtext("invoices/invoice/invoice_number") == "100123"
    assert root.findtext("invoice_items/invoice_item/line_total") == "600.00"
    assert root.findtext("expenses/expense/description") == "Accounting software"
    assert root.findtext("tax_summary/tax/metric") == "TPS collected from paid invoices"
```

- [ ] **Step 2: Run XML test to verify it fails**

Run:

```bash
uv run pytest tests/test_accountant_export.py::test_create_audit_xml_exports_structured_period_data -q
```

Expected: FAIL with `ImportError` or `AttributeError` because `create_accountant_audit_xml` does not exist.

- [ ] **Step 3: Implement Audit XML generation**

Add this to `app/export_utils.py`:

```python
import xml.etree.ElementTree as ET


def add_mapping(parent: ET.Element, tag: str, values: dict[str, str]) -> ET.Element:
    element = ET.SubElement(parent, tag)
    for key, value in values.items():
        child = ET.SubElement(element, key)
        child.text = text(value)
    return element


def render_audit_xml(context: AccountantExportContext) -> bytes:
    root = ET.Element("accountant_export")
    metadata = ET.SubElement(root, "metadata")
    add_text(metadata, "format", "audit_xml")
    add_text(metadata, "generated_at", context.summary["generated_at"])
    add_text(metadata, "currency", context.summary["currency"])
    add_text(metadata, "include_invoice_items", "true" if context.include_invoice_items else "false")

    company = ET.SubElement(root, "company")
    for key, value in context.company.items():
        add_text(company, key, value)

    period = ET.SubElement(root, "period")
    add_text(period, "start_date", context.summary["period_start"])
    add_text(period, "end_date", context.summary["period_end"])

    add_mapping(root, "summary", context.summary)
    accounts = ET.SubElement(root, "chart_of_accounts")
    for account in context.accounts:
        add_mapping(accounts, "account", account)
    customers = ET.SubElement(root, "customers")
    for customer in context.customers:
        add_mapping(customers, "customer", customer)
    invoices = ET.SubElement(root, "invoices")
    for invoice in context.invoices:
        add_mapping(invoices, "invoice", invoice)
    invoice_items = ET.SubElement(root, "invoice_items")
    for item in context.invoice_items:
        add_mapping(invoice_items, "invoice_item", item)
    expenses = ET.SubElement(root, "expenses")
    for expense in context.expenses:
        add_mapping(expenses, "expense", expense)
    tax_summary = ET.SubElement(root, "tax_summary")
    for tax in context.tax_report:
        add_mapping(tax_summary, "tax", tax)

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def add_text(parent: ET.Element, tag: str, value: str) -> ET.Element:
    child = ET.SubElement(parent, tag)
    child.text = text(value)
    return child


def create_accountant_audit_xml(
    session: Session,
    start_date: datetime,
    end_date: datetime,
    include_invoice_items: bool = False,
    export_dir: str | Path = "data/exports",
) -> Path:
    context = build_accountant_export_context(session, start_date, end_date, include_invoice_items)
    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)
    xml_path = export_path / export_filename("accountant_audit", start_date, end_date, "xml")
    xml_path.write_bytes(render_audit_xml(context))
    return xml_path
```

- [ ] **Step 4: Run all export tests**

Run:

```bash
uv run pytest tests/test_accountant_export.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/export_utils.py tests/test_accountant_export.py
git commit -m "Add accountant audit XML export"
```

## Task 4: Reports UI Dialog

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_accountant_export.py`

- [ ] **Step 1: Add a small validation test**

Append this import and test to `tests/test_accountant_export.py`:

```python
import pytest

from export_utils import validate_export_range  # noqa: E402


def test_validate_export_range_rejects_end_before_start():
    with pytest.raises(ValueError, match="End date must be on or after start date"):
        validate_export_range(datetime(2026, 2, 1), datetime(2026, 1, 31))
```

- [ ] **Step 2: Run validation test to verify it fails**

Run:

```bash
uv run pytest tests/test_accountant_export.py::test_validate_export_range_rejects_end_before_start -q
```

Expected: FAIL because `validate_export_range` does not exist.

- [ ] **Step 3: Add validation helper**

Add this to `app/export_utils.py`:

```python
def validate_export_range(start_date: datetime, end_date: datetime) -> None:
    if end_date < start_date:
        raise ValueError("End date must be on or after start date")
```

- [ ] **Step 4: Import export helpers in `app/main.py`**

Change the imports near the top of `app/main.py` from:

```python
from template_utils import TemplateManager
```

To:

```python
from template_utils import TemplateManager
from export_utils import create_accountant_audit_xml, create_accountant_csv_zip, validate_export_range
```

- [ ] **Step 5: Add the export dialog helper inside `reports_page`**

Inside `reports_page`, after `section_header` and before the page layout, add:

```python
    def open_accountant_export_dialog():
        export_state = {
            'preset': state['preset'],
            'from': state['from'],
            'to': state['to'],
        }
        export_preset_btns = {}

        with ui.dialog() as export_dialog, ui.card().classes('p-8 w-[720px] premium-card'):
            ui.label('Export for Accountant').classes('text-2xl font-extrabold text-slate-900 dark:text-slate-100')
            ui.label('Package invoices, expenses, taxes, customers, and accounts for a selected period.').classes('text-sm text-slate-400 mb-5')

            export_range_label = ui.label(
                f"{export_state['from'].strftime('%b %d, %Y')} — {export_state['to'].strftime('%b %d, %Y')}"
            ).classes('text-sm font-semibold text-slate-500 mt-4')

            custom_export_row = ui.row().classes('items-center gap-3 mt-3')
            custom_export_row.set_visibility(export_state['preset'] == 'Custom')

            def set_export_preset(name):
                export_state['preset'] = name
                for preset_name, button in export_preset_btns.items():
                    button.classes(replace='btn-primary h-9 rounded-lg px-4 text-sm' if preset_name == name
                                   else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300')
                if name != 'Custom':
                    start, end = PRESETS[name]
                    export_state['from'] = start
                    export_state['to'] = end
                    custom_export_row.set_visibility(False)
                    export_range_label.set_text(f"{start.strftime('%b %d, %Y')} — {end.strftime('%b %d, %Y')}")
                else:
                    custom_export_row.set_visibility(True)

            with ui.row().classes('w-full items-center gap-3 flex-wrap mt-5'):
                ui.label('Period:').classes('text-sm font-semibold text-slate-500 mr-1')
                for preset_name in PRESETS:
                    active = preset_name == export_state['preset']
                    button = ui.button(preset_name, on_click=lambda name=preset_name: set_export_preset(name)).classes(
                        'btn-primary h-9 rounded-lg px-4 text-sm' if active
                        else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                    )
                    export_preset_btns[preset_name] = button

            with custom_export_row:
                export_from_input = ui.input('From', value=export_state['from'].strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                export_to_input = ui.input('To', value=export_state['to'].strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')

                def apply_export_custom():
                    try:
                        start = datetime.strptime(export_from_input.value, '%Y-%m-%d')
                        end = datetime.strptime(export_to_input.value, '%Y-%m-%d')
                        validate_export_range(start, end)
                    except ValueError as exc:
                        message = 'Invalid date format. Use YYYY-MM-DD' if 'does not match format' in str(exc) else str(exc)
                        ui.notify(message, color='red-500')
                        return
                    export_state['from'] = start
                    export_state['to'] = end
                    export_range_label.set_text(f"{start.strftime('%b %d, %Y')} — {end.strftime('%b %d, %Y')}")

                ui.button('Apply', on_click=apply_export_custom).classes('btn-primary h-9 rounded-lg px-5 text-sm')

            format_select = ui.select(
                {'csv_zip': 'CSV ZIP (recommended)', 'audit_xml': 'Audit XML'},
                value='csv_zip',
                label='Format',
            ).props('outlined dense').classes('w-full mt-6')
            include_items = ui.checkbox('Include invoice line-item details', value=False).classes('mt-2')

            with ui.row().classes('w-full justify-end gap-3 mt-8'):
                ui.button('Cancel', on_click=export_dialog.close).props('flat no-caps').classes('text-slate-400')

                def do_export():
                    try:
                        start = export_state['from']
                        end = export_state['to']
                        validate_export_range(start, end)
                        with Session(engine) as session:
                            if format_select.value == 'audit_xml':
                                path = create_accountant_audit_xml(session, start, end, include_items.value)
                            else:
                                path = create_accountant_csv_zip(session, start, end, include_items.value)
                        ui.download(str(path))
                        ui.notify(f'Accountant export ready: {start.strftime("%Y-%m-%d")} to {end.strftime("%Y-%m-%d")}', color='emerald-500')
                        export_dialog.close()
                    except ValueError as exc:
                        ui.notify(str(exc), color='red-500')
                    except Exception as exc:
                        logger.exception("Error generating accountant export")
                        ui.notify(f'Error generating export: {exc}', color='red-500')

                ui.button('Export', icon='download', on_click=do_export).classes('btn-primary h-11 rounded-xl px-7')

        export_dialog.open()
```

- [ ] **Step 6: Add the Reports-page button**

Change the Reports page header from:

```python
        ui.label('Reports').classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-2')
        ui.label('Financial reports for any period').classes('text-slate-400 text-base mb-6')
```

To:

```python
        with ui.row().classes('w-full justify-between items-end mb-6'):
            with ui.column():
                ui.label('Reports').classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-2')
                ui.label('Financial reports for any period').classes('text-slate-400 text-base')
            ui.button('Export for Accountant', icon='folder_zip', on_click=open_accountant_export_dialog).classes('btn-primary h-12 rounded-xl px-6')
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run pytest tests/test_accountant_export.py -q
```

Expected: PASS.

- [ ] **Step 8: Run existing related tests**

Run:

```bash
uv run pytest tests/test_invoice_numbering.py tests/test_expense_model.py tests/test_template_rendering.py tests/test_accountant_export.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/main.py app/export_utils.py tests/test_accountant_export.py
git commit -m "Add accountant export dialog"
```

## Task 5: Manual Export Smoke Check

**Files:**
- Check: `app/main.py`
- Check: `app/export_utils.py`
- Check: `data/exports/`

- [ ] **Step 1: Run the full current test suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 2: Generate sample files without launching the UI**

Run:

```bash
uv run python -c "from datetime import datetime; from sqlmodel import Session; from database import engine; from export_utils import create_accountant_csv_zip, create_accountant_audit_xml; s=Session(engine); print(create_accountant_csv_zip(s, datetime(2026,1,1), datetime(2026,12,31), False)); print(create_accountant_audit_xml(s, datetime(2026,1,1), datetime(2026,12,31), True)); s.close()"
```

Expected: prints paths like:

```text
data/exports/accountant_export_2026-01-01_to_2026-12-31.zip
data/exports/accountant_audit_2026-01-01_to_2026-12-31.xml
```

- [ ] **Step 3: Inspect ZIP contents**

Run:

```bash
unzip -l data/exports/accountant_export_2026-01-01_to_2026-12-31.zip
```

Expected: list includes `accountant_report.html`, `summary.csv`, `invoices.csv`, `expenses.csv`, `tax_report.csv`, `customers.csv`, `chart_of_accounts.csv`, and `manifest.json`, and does not include `invoice_items.csv`.

- [ ] **Step 4: Inspect HTML report**

Run:

```bash
unzip -p data/exports/accountant_export_2026-01-01_to_2026-12-31.zip accountant_report.html | rg -n "tailwindcss|Files included|Accountant Export"
```

Expected: output includes matching lines for Tailwind CDN, `Files included`, and `Accountant Export`.

- [ ] **Step 5: Inspect Audit XML**

Run:

```bash
rg -n "accountant_export|audit_xml|chart_of_accounts|tax_summary" data/exports/accountant_audit_2026-01-01_to_2026-12-31.xml
```

Expected: output includes all four terms.

- [ ] **Step 6: Start the app for UI smoke testing**

Run:

```bash
NICEGUI_SHOW_BROWSER=false uv run python app/main.py
```

Expected: app starts on the configured local port without import errors.

- [ ] **Step 7: Open Reports and generate export manually**

Open the app, go to `/reports`, click `Export for Accountant`, keep `CSV ZIP (recommended)`, leave invoice line items unchecked, and click `Export`.

Expected: browser downloads the ZIP and shows an emerald success notification.

- [ ] **Step 8: Commit any final polish**

Only if a manual smoke check required code changes:

```bash
git add app/main.py app/export_utils.py tests/test_accountant_export.py
git commit -m "Polish accountant export smoke issues"
```

If no changes were needed, do not create an empty commit.

## Self-Review

- Spec coverage: Task 1 covers period filtering, customers, accounts, summaries, and optional invoice items. Task 2 covers CSV ZIP, manifest, and Tailwind HTML report. Task 3 covers structured Audit XML. Task 4 covers Reports UI, date range selection, default CSV ZIP, optional invoice items, and user notifications. Task 5 covers verification and manual smoke checks.
- Placeholder scan: no `TBD`, `TODO`, "implement later", or "similar to" instructions remain.
- Type consistency: all helper names used in tests are defined in later steps: `build_accountant_export_context`, `rows_to_csv_text`, `create_accountant_csv_zip`, `create_accountant_audit_xml`, and `validate_export_range`.
