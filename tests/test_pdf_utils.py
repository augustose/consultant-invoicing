import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from pdf_utils import _due_date_text, _quantity, build_invoice_pdf  # noqa: E402


def test_build_invoice_pdf_contains_invoice_content(tmp_path):
    invoice = SimpleNamespace(
        number="100123",
        date=datetime(2026, 6, 3),
        due_date=datetime(2026, 7, 3),
        subtotal=600.0,
        total=689.85,
        status="Draft",
        notes="Thank you for your business.",
    )
    customer = SimpleNamespace(
        name="Cafe Parvis",
        contact="Alejandra Ponce",
        address="433 Rue Mayor\nMontréal, Quebec H3A 1N9\nCanada",
        email="alejandraponce@hotmail.com",
        phone="514 775 5234",
    )
    item = SimpleNamespace(
        description=(
            "IT Consulting and Support\n"
            "Monthly Subscription for Technical Support of Existing IT Infrastructure."
        ),
        quantity=1,
        unit_price=600.0,
        total=600.0,
    )
    vendor = SimpleNamespace(
        legal_name="Augusto Sosa Escalada (Mac)",
        address="1464, Fronenac St. App.#1\nMontreal, Quebec H2K 2Y7\nCanada",
        phone="5148853146",
        email="augustose@gmail.com",
        currency="CAD",
        tps_number="717569891 RT 0001",
        tvq_number="4023119175 TQ 0002",
    )

    pdf_bytes = build_invoice_pdf(invoice, customer, [item], vendor)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000


def test_due_date_text_defaults_to_thirty_days_after_invoice_date():
    invoice = SimpleNamespace(date=datetime(2026, 6, 3), due_date=None)

    assert _due_date_text(invoice) == "2026-07-03"


def test_quantity_omits_decimal_for_whole_numbers():
    assert _quantity(1.0) == "1"
    assert _quantity(1.5) == "1.5"
