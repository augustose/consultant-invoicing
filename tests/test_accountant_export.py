import csv
import io
import sys
from datetime import datetime
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from database import Account, AccountType, CompanySettings, Customer, Expense, Invoice, InvoiceItem, Service  # noqa: E402
from export_utils import build_accountant_export_context, money, rows_to_csv_text  # noqa: E402


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
