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
    filter_and_sort_invoice_rows,
    invoice_display_status,
    invoice_filter_period_bounds,
    invoice_item_description,
    invoice_list_columns,
    next_invoice_number,
)


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
