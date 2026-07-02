import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from main import shift_month_year_in_text  # noqa: E402


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
