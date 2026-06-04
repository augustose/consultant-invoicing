import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from template_utils import TemplateManager  # noqa: E402


def test_render_invoice_formats_multiline_item_description():
    invoice = SimpleNamespace(
        id=1,
        number="100123",
        status="Draft",
        date=datetime(2026, 5, 31),
        due_date=datetime(2026, 5, 31),
        subtotal=600.0,
        total=689.85,
        notes="Monthly support",
    )
    customer = SimpleNamespace(
        name="Cafe Parvis",
        contact="Alejandra Ponce",
        address="433 Rue Mayor",
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
        address="1464, Fronenac St. App.#1",
        phone="5148853146",
        email="augustose@gmail.com",
        currency="CAD",
        tps_number="717569891 RT 0001",
        tvq_number="4023119175 TQ 0002",
    )

    html = TemplateManager.render_invoice(invoice, customer, [item], vendor)

    assert "IT Consulting and Support" in html
    assert (
        '<div class="item-detail">Monthly Subscription for Technical Support of '
        "Existing IT Infrastructure.</div>"
    ) in html
    assert "717569891 RT 0001" in html
    assert "4023119175 TQ 0002" in html


def test_render_invoice_includes_vendor_email():
    invoice = SimpleNamespace(
        id=1,
        number="100123",
        status="Draft",
        date=datetime(2026, 5, 31),
        due_date=datetime(2026, 5, 31),
        subtotal=600.0,
        total=689.85,
        notes="Monthly support",
    )
    customer = SimpleNamespace(
        name="Cafe Parvis",
        contact="Alejandra Ponce",
        address="433 Rue Mayor",
        email="alejandraponce@hotmail.com",
        phone="514 775 5234",
    )
    item = SimpleNamespace(
        description="IT Consulting and Support",
        quantity=1,
        unit_price=600.0,
        total=600.0,
    )
    vendor = SimpleNamespace(
        legal_name="Augusto Sosa Escalada (Mac)",
        address="1464, Fronenac St. App.#1",
        phone="5148853146",
        email="augustose@gmail.com",
        currency="CAD",
        tps_number="717569891 RT 0001",
        tvq_number="4023119175 TQ 0002",
    )

    html = TemplateManager.render_invoice(invoice, customer, [item], vendor)

    assert "augustose@gmail.com" in html
