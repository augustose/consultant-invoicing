import sys
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from main import (  # noqa: E402
    build_invoice_list_row,
    can_cancel_invoice,
    can_mark_invoice_paid,
    can_write_off_invoice,
    invoice_display_status,
    invoice_item_description,
    invoice_list_columns,
    next_invoice_number,
)


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


def test_invoice_item_description_includes_service_description_when_available():
    service = SimpleNamespace(
        name="IT Consulting and Support",
        description="Monthly Subscription for Technical Support of Existing IT Infrastructure.",
    )

    assert invoice_item_description(service) == (
        "IT Consulting and Support\n"
        "Monthly Subscription for Technical Support of Existing IT Infrastructure."
    )


def test_invoice_item_description_uses_name_when_service_description_is_blank():
    service = SimpleNamespace(name="IT Consulting and Support", description="")

    assert invoice_item_description(service) == "IT Consulting and Support"


def test_invoice_list_columns_include_invoice_date():
    columns = invoice_list_columns("Customers")

    assert {
        "name": "date",
        "label": "Date",
        "field": "date_fmt",
        "align": "left",
    } in columns


def test_invoice_list_row_formats_invoice_date():
    invoice = SimpleNamespace(
        id=1,
        number="100123",
        customer_id=2,
        status="Sent",
        date=datetime(2026, 6, 3),
        due_date=None,
        total=689.85,
        model_dump=lambda: {
            "id": 1,
            "number": "100123",
            "customer_id": 2,
            "status": "Sent",
            "date": datetime(2026, 6, 3),
            "due_date": None,
            "total": 689.85,
        },
    )
    customers = [SimpleNamespace(id=2, name="Cafe Parvis")]

    row = build_invoice_list_row(invoice, customers, today=datetime(2026, 6, 4))

    assert row["date_fmt"] == "2026-06-03"


def test_only_draft_invoices_can_be_cancelled():
    assert can_cancel_invoice("Draft") is True
    assert can_cancel_invoice("Sent") is False
    assert can_cancel_invoice("Paid") is False
    assert can_cancel_invoice("Cancelled") is False


def test_sent_invoice_displays_as_overdue_after_due_date():
    invoice = SimpleNamespace(
        status="Sent",
        date=datetime(2026, 5, 1),
        due_date=datetime(2026, 5, 31),
    )

    assert invoice_display_status(invoice, today=datetime(2026, 6, 1)) == "Overdue"


def test_sent_invoice_uses_default_due_date_for_overdue_display():
    invoice = SimpleNamespace(
        status="Sent",
        date=datetime(2026, 5, 1),
        due_date=None,
    )

    assert invoice_display_status(invoice, today=datetime(2026, 5, 31)) == "Sent"
    assert invoice_display_status(invoice, today=datetime(2026, 6, 1)) == "Overdue"


def test_sent_and_overdue_invoices_can_be_paid_or_written_off():
    assert can_mark_invoice_paid("Sent") is True
    assert can_mark_invoice_paid("Overdue") is True
    assert can_write_off_invoice("Sent") is True
    assert can_write_off_invoice("Overdue") is True


def test_paid_written_off_and_cancelled_invoices_are_locked():
    for status in ["Paid", "Written Off", "Cancelled"]:
        assert can_cancel_invoice(status) is False
        assert can_mark_invoice_paid(status) is False
        assert can_write_off_invoice(status) is False
