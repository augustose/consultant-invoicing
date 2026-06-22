import sys
from pathlib import Path
from datetime import datetime
import inspect
import textwrap

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import main  # noqa: E402
from main import (  # noqa: E402
    advance_recurrence_date,
    client_expense_can_transition,
    client_expense_needs_followup,
    client_expense_next_states,
    compute_invoice_totals,
    compute_tax_split,
    safe_client_notify,
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


def test_client_expense_add_form_is_collapsed_and_save_button_is_always_available():
    source = textwrap.dedent(inspect.getsource(main.client_expenses_page))
    assert "ui.expansion('Add Client Expense', value=False" in source
    assert source.index("def save_expense():") < source.index("if ai_ready:")
    assert source.index("ui.button('Add Expense'") > source.index("def save_expense():")


def test_duplicate_total_filter_pauses_programmatic_filter_refreshes():
    source = textwrap.dedent(inspect.getsource(main.client_expenses_page))
    assert "filter_controls_paused = {'value': False}" in source
    assert "if filter_controls_paused['value']:" in source
    helper = source[source.index("def set_filter_control_values("):source.index("def update_filter(")]
    assert "filter_controls_paused['value'] = True" in helper
    assert "filter_controls_paused['value'] = False" in helper
    duplicate_filter = source[
        source.index("def filter_by_duplicate_total(total):"):source.index("def refresh_table():")
    ]
    assert "set_filter_control_values(min_total=total, max_total=total)" in duplicate_filter
    assert duplicate_filter.index("set_filter_control_values") < duplicate_filter.index("refresh_table()")


def test_safe_client_notify_skips_deleted_client():
    class FakeOutbox:
        def __init__(self):
            self.messages = []

        def enqueue_message(self, message_type, data, target_id):
            self.messages.append((target_id, message_type, data))

    class FakeClient:
        id = "client-1"

        def __init__(self, deleted):
            self._deleted = deleted
            self.outbox = FakeOutbox()

    deleted_client = FakeClient(deleted=True)
    assert safe_client_notify(deleted_client, "Done", color="emerald-500") is False
    assert deleted_client.outbox.messages == []

    live_client = FakeClient(deleted=False)
    assert safe_client_notify(live_client, "Done", color="emerald-500", multi_line=True, timeout=8000) is True
    assert live_client.outbox.messages == [
        (
            "client-1",
            "notify",
            {
                "message": "Done",
                "position": "bottom",
                "color": "emerald-500",
                "multiLine": True,
                "timeout": 8000,
            },
        )
    ]


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
