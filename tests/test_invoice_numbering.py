import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from main import invoice_item_description, next_invoice_number  # noqa: E402


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
