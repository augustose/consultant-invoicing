import csv
import io
import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from database import Account, AccountType, CompanySettings, Customer, Expense, Invoice, InvoiceItem, Service  # noqa: E402
from export_utils import (  # noqa: E402
    build_accountant_export_context,
    create_accountant_audit_xml,
    create_accountant_csv_zip,
    money,
    rows_to_csv_text,
)


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
    boundary_invoice = Invoice(
        number="100125",
        date=datetime(2026, 1, 31, 23, 59, 59),
        customer_id=customer.id,
        status="Paid",
        subtotal=50.0,
        tax_total=7.49,
        total=57.49,
    )
    after_period_invoice = Invoice(
        number="100126",
        date=datetime(2026, 2, 1, 0, 0, 0),
        customer_id=customer.id,
        status="Paid",
        subtotal=80.0,
        tax_total=11.98,
        total=91.98,
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
    boundary_expense = Expense(
        date=datetime(2026, 1, 31, 23, 59, 59),
        description="Boundary expense",
        amount=25.0,
        tps=1.25,
        tvq=2.49,
        total=28.74,
        account_id=expense_account.id,
    )
    after_period_expense = Expense(
        date=datetime(2026, 2, 1, 0, 0, 0),
        description="Future expense",
        amount=30.0,
        total=30.0,
        account_id=expense_account.id,
    )
    outside_expense = Expense(
        date=datetime(2025, 12, 1),
        description="Old expense",
        amount=200.0,
        total=200.0,
        account_id=expense_account.id,
    )
    session.add_all(
        [
            paid_invoice,
            boundary_invoice,
            after_period_invoice,
            sent_invoice,
            outside_invoice,
            expense,
            boundary_expense,
            after_period_expense,
            outside_expense,
        ]
    )
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

    assert [row["invoice_number"] for row in context.invoices] == ["100123", "100125"]
    assert [row["description"] for row in context.expenses] == ["Accounting software", "Boundary expense"]
    assert [row["name"] for row in context.customers] == ["Cafe Parvis"]
    assert [row["code"] for row in context.accounts] == ["4000", "5000", "5100"]
    assert [row["type"] for row in context.accounts] == ["Income", "Expense", "Expense"]
    assert context.invoice_items == []
    assert context.summary["invoice_count"] == "2"
    assert context.summary["paid_invoice_count"] == "2"
    assert context.summary["paid_total"] == "747.34"
    assert context.summary["expense_total"] == "143.72"
    assert context.summary["net_before_taxes"] == "525.00"


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


def test_money_uses_half_up_cent_rounding():
    assert money(2.675) == "2.68"


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
        assert archive.namelist() == manifest["files"]

    assert names == sorted(manifest["files"])
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


def test_csv_zip_neutralizes_formula_like_text_cells(tmp_path):
    session = make_session()
    customer = session.exec(select(Customer).where(Customer.name == "Cafe Parvis")).one()
    invoice = session.exec(select(Invoice).where(Invoice.number == "100123")).one()
    expense = session.exec(select(Expense).where(Expense.description == "Accounting software")).one()
    account = session.exec(select(Account).where(Account.code == "5000")).one()
    invoice_item = session.exec(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)).one()

    customer.name = '=HYPERLINK("http://bad")'
    customer.contact = "+SUM(1,2)"
    customer.email = " @evil@example.com"
    customer.address = "\t-danger street"
    invoice.number = "=100123"
    invoice.notes = "@cmd"
    expense.description = "+SUM(1,2)"
    expense.notes = " -expense note"
    account.name = "@Software Account"
    account.description = "-danger"
    invoice_item.description = " =line item"
    session.add_all([customer, invoice, expense, account, invoice_item])
    session.commit()

    zip_path = create_accountant_csv_zip(
        session=session,
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
        include_invoice_items=True,
        export_dir=tmp_path,
    )

    with zipfile.ZipFile(zip_path) as archive:
        invoices = parse_csv(archive.read("invoices.csv").decode("utf-8"))
        expenses = parse_csv(archive.read("expenses.csv").decode("utf-8"))
        customers = parse_csv(archive.read("customers.csv").decode("utf-8"))
        accounts = parse_csv(archive.read("chart_of_accounts.csv").decode("utf-8"))
        invoice_items = parse_csv(archive.read("invoice_items.csv").decode("utf-8"))

    account_by_code = {row["code"]: row for row in accounts}
    assert invoices[0]["invoice_number"] == "'=100123"
    assert invoices[0]["customer_name"] == '\'=HYPERLINK("http://bad")'
    assert invoices[0]["customer_email"] == "' @evil@example.com"
    assert invoices[0]["notes"] == "'@cmd"
    assert invoices[0]["invoice_date"] == "2026-01-15"
    assert invoices[0]["subtotal"] == "600.00"
    assert expenses[0]["description"] == "'+SUM(1,2)"
    assert expenses[0]["account_name"] == "'@Software Account"
    assert expenses[0]["notes"] == "' -expense note"
    assert expenses[0]["date"] == "2026-01-20"
    assert expenses[0]["subtotal"] == "100.00"
    assert customers[0]["name"] == '\'=HYPERLINK("http://bad")'
    assert customers[0]["contact"] == "'+SUM(1,2)"
    assert customers[0]["email"] == "' @evil@example.com"
    assert customers[0]["address"] == "'\t-danger street"
    assert account_by_code["5000"]["name"] == "'@Software Account"
    assert account_by_code["5000"]["description"] == "'-danger"
    assert invoice_items[0]["invoice_number"] == "'=100123"
    assert invoice_items[0]["customer_name"] == '\'=HYPERLINK("http://bad")'
    assert invoice_items[0]["description"] == "' =line item"
    assert invoice_items[0]["invoice_date"] == "2026-01-15"
    assert invoice_items[0]["line_total"] == "600.00"


def test_csv_zip_report_escapes_company_name_html(tmp_path):
    session = make_session()
    settings = session.exec(select(CompanySettings)).one()
    settings.legal_name = '<script>alert("x")</script> & Co'
    session.add(settings)
    session.commit()

    zip_path = create_accountant_csv_zip(
        session=session,
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
        include_invoice_items=False,
        export_dir=tmp_path,
    )

    with zipfile.ZipFile(zip_path) as archive:
        html = archive.read("accountant_report.html").decode("utf-8")

    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; Co" in html
    assert '<script>alert("x")</script> & Co' not in html
