import sys
from pathlib import Path
from datetime import datetime

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from main import (  # noqa: E402
    advance_recurrence_date,
    client_expense_can_transition,
    client_expense_needs_followup,
    client_expense_next_states,
    compute_invoice_totals,
    compute_tax_split,
    sanitize_receipt_filename,
)


# --- tax_breakdown (splits stored tax_total into TPS/TVQ for display) ---

def test_tax_breakdown_matches_legacy_for_normal_invoice():
    from database import tax_breakdown
    # legacy display: gst = subtotal*0.05, qst = subtotal*0.09975
    tps, tvq = tax_breakdown(100.0 * 0.14975)
    assert tps == pytest.approx(100.0 * 0.05)
    assert tvq == pytest.approx(100.0 * 0.09975)


def test_tax_breakdown_components_sum_to_tax_total():
    from database import tax_breakdown
    tps, tvq = tax_breakdown(22.46)
    assert tps + tvq == pytest.approx(22.46)


def test_tax_breakdown_zero():
    from database import tax_breakdown
    assert tax_breakdown(0.0) == (0.0, 0.0)


# --- compute_tax_split (extracted from expenses_page closure) ---

def test_compute_tax_split_no_tax():
    assert compute_tax_split(100.0, False, False) == (0.0, 0.0, 100.0)


def test_compute_tax_split_tps_only():
    assert compute_tax_split(100.0, True, False) == (5.0, 0.0, 105.0)


def test_compute_tax_split_tvq_only():
    assert compute_tax_split(100.0, False, True) == (0.0, 9.98, 109.98)


def test_compute_tax_split_both_taxes():
    tps, tvq, total = compute_tax_split(100.0, True, True)
    assert tps == 5.0
    assert tvq == 9.98
    assert total == 114.98


# --- compute_invoice_totals (the tax-engine change) ---

def test_compute_invoice_totals_all_taxable_matches_legacy():
    # Must be byte-identical to legacy: tax = subtotal * 0.14975, total = subtotal * 1.14975
    items = [(100.0, True), (50.0, True)]
    subtotal, tax_total, total = compute_invoice_totals(items)
    assert subtotal == 150.0
    assert tax_total == 150.0 * 0.14975
    assert total == 150.0 * 1.14975


def test_compute_invoice_totals_excludes_non_taxable_lines_from_tax():
    # one taxable service + one non-taxable reimbursement
    items = [(100.0, True), (57.49, False)]
    subtotal, tax_total, total = compute_invoice_totals(items)
    assert subtotal == pytest.approx(157.49)
    assert tax_total == pytest.approx(100.0 * 0.14975)
    assert total == pytest.approx(157.49 + 100.0 * 0.14975)


def test_compute_invoice_totals_empty():
    assert compute_invoice_totals([]) == (0.0, 0.0, 0.0)


# --- status transitions ---

def test_next_states_for_each_status():
    assert client_expense_next_states("pending") == ("claimed",)
    assert client_expense_next_states("claimed") == ("waiting",)
    assert set(client_expense_next_states("waiting")) == {"disputed", "reimbursed"}
    assert set(client_expense_next_states("disputed")) == {"reimbursed", "written_off"}
    assert client_expense_next_states("reimbursed") == ()
    assert client_expense_next_states("written_off") == ()


def test_can_transition_valid_edges():
    assert client_expense_can_transition("pending", "claimed") is True
    assert client_expense_can_transition("waiting", "reimbursed") is True
    assert client_expense_can_transition("disputed", "written_off") is True


def test_can_transition_invalid_edges():
    assert client_expense_can_transition("pending", "reimbursed") is False
    assert client_expense_can_transition("reimbursed", "claimed") is False
    assert client_expense_can_transition("written_off", "reimbursed") is False
    assert client_expense_can_transition("waiting", "pending") is False


# --- recurrence date math (stdlib calendar, no dateutil) ---

def test_advance_recurrence_keeps_same_day():
    assert advance_recurrence_date(datetime(2026, 1, 15), 15) == datetime(2026, 2, 15)


def test_advance_recurrence_clamps_day_31_to_february():
    assert advance_recurrence_date(datetime(2026, 1, 31), 31) == datetime(2026, 2, 28)


def test_advance_recurrence_clamps_to_leap_february():
    assert advance_recurrence_date(datetime(2024, 1, 31), 31) == datetime(2024, 2, 29)


def test_advance_recurrence_rolls_over_year():
    assert advance_recurrence_date(datetime(2026, 12, 10), 10) == datetime(2027, 1, 10)


# --- follow-up highlight ---

def test_needs_followup_waiting_beyond_threshold():
    last = datetime(2026, 5, 1)
    assert client_expense_needs_followup("waiting", last, datetime(2026, 6, 1)) is True


def test_needs_followup_waiting_within_threshold():
    last = datetime(2026, 5, 25)
    assert client_expense_needs_followup("waiting", last, datetime(2026, 6, 1)) is False


def test_needs_followup_false_for_non_waiting_status():
    last = datetime(2026, 1, 1)
    assert client_expense_needs_followup("reimbursed", last, datetime(2026, 6, 1)) is False
    assert client_expense_needs_followup("pending", last, datetime(2026, 6, 1)) is False


# --- receipt filename sanitization ---

def test_sanitize_strips_path_traversal():
    assert sanitize_receipt_filename("../../etc/passwd") == "passwd"


def test_sanitize_strips_directory_separators():
    assert sanitize_receipt_filename("/var/tmp/receipt.pdf") == "receipt.pdf"


def test_sanitize_keeps_extension_and_collapses_odd_chars():
    assert sanitize_receipt_filename("My Receipt #4!.PDF") == "My_Receipt_4.PDF"


def test_sanitize_empty_falls_back():
    assert sanitize_receipt_filename("") == "receipt"
    assert sanitize_receipt_filename("///") == "receipt"
