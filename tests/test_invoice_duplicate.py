import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from main import build_duplicate_invoice_prefill, shift_month_year_in_text  # noqa: E402


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


def test_shift_french_month_accented_input():
    assert shift_month_year_in_text("février 2026", 1) == "mars 2026"


def test_shift_month_word_boundary_may_vs_mayo():
    assert shift_month_year_in_text("May 2026", 1) == "June 2026"
    assert shift_month_year_in_text("mayo 2026", 1) == "junio 2026"


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
