import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import pytest
from sqlmodel import SQLModel, Session, create_engine, select
from database import ClientExpense, ClientExpenseEvent, Customer, Service


@pytest.fixture
def session():
    test_engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as s:
        cust = Customer(name="Cafe Parvis", email="cafe@example.com")
        s.add(cust)
        s.commit()
        s.refresh(cust)
        yield s, cust.id


def test_client_expense_can_be_created_with_defaults(session):
    s, cust_id = session
    exp = ClientExpense(
        customer_id=cust_id,
        description="Cloud hosting paid on behalf of client",
        amount=100.0,
        tps=5.0,
        tvq=9.98,
        total=114.98,
    )
    s.add(exp)
    s.commit()
    s.refresh(exp)
    assert exp.id is not None
    assert exp.status == "pending"
    assert exp.is_recurring is False
    assert exp.invoice_id is None
    assert exp.receipt_path is None


def test_client_expense_event_links_to_expense(session):
    s, cust_id = session
    exp = ClientExpense(customer_id=cust_id, description="x", amount=10.0, total=10.0)
    s.add(exp)
    s.commit()
    s.refresh(exp)

    evt = ClientExpenseEvent(client_expense_id=exp.id, status="claimed", notes="Sent claim")
    s.add(evt)
    s.commit()
    s.refresh(evt)

    assert evt.id is not None
    assert evt.client_expense_id == exp.id
    assert evt.changed_at is not None

    rows = s.exec(
        select(ClientExpenseEvent).where(ClientExpenseEvent.client_expense_id == exp.id)
    ).all()
    assert len(rows) == 1


def test_generate_due_client_expenses_creates_next_and_clears_anchor(session):
    from datetime import datetime
    from main import generate_due_client_expenses

    s, cust_id = session
    src = ClientExpense(
        customer_id=cust_id, description="Monthly hosting", amount=100.0,
        tps=5.0, tvq=9.98, total=114.98, status="reimbursed",
        is_recurring=True, recurrence_day=15,
        date=datetime(2025, 12, 15), next_due_date=datetime(2026, 1, 15),
    )
    s.add(src)
    s.commit()
    s.refresh(src)

    created = generate_due_client_expenses(s, now=datetime(2026, 2, 1))

    assert len(created) == 1
    child = created[0]
    assert child.status == "pending"
    assert child.is_recurring is True
    assert child.receipt_path is None
    assert child.date == datetime(2026, 1, 15)
    assert child.next_due_date == datetime(2026, 2, 15)

    # an event was logged for the child
    events = s.exec(
        select(ClientExpenseEvent).where(ClientExpenseEvent.client_expense_id == child.id)
    ).all()
    assert [e.status for e in events] == ["pending"]

    # source is no longer an anchor → second pass generates nothing (idempotent)
    s.refresh(src)
    assert src.next_due_date is None
    assert generate_due_client_expenses(s, now=datetime(2026, 2, 1)) == []


def test_get_or_create_reimbursable_service_is_idempotent(session):
    from database import get_or_create_reimbursable_service

    s, _ = session
    svc1 = get_or_create_reimbursable_service(s)
    svc2 = get_or_create_reimbursable_service(s)

    assert svc1.id == svc2.id
    all_named = s.exec(select(Service).where(Service.name == svc1.name)).all()
    assert len(all_named) == 1


def test_receipt_preview_url_for_image(tmp_path):
    from main import receipt_preview_url
    p = tmp_path / "5_receipt.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert receipt_preview_url(str(p)) == "/receipts/5_receipt.png"


def test_receipt_preview_url_for_pdf_generates_thumb(tmp_path):
    from io import BytesIO
    from reportlab.pdfgen import canvas
    from main import receipt_preview_url

    pdf = tmp_path / "7_invoice.pdf"
    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, "X")
    c.showPage()
    c.save()
    pdf.write_bytes(buf.getvalue())

    url = receipt_preview_url(str(pdf))
    assert url == "/receipts/7_invoice.pdf.thumb.png"
    assert (tmp_path / "7_invoice.pdf.thumb.png").exists()


def test_receipt_preview_url_none_when_missing():
    from main import receipt_preview_url
    assert receipt_preview_url(None) is None
    assert receipt_preview_url("/no/such/file.png") is None


def test_flag_duplicates_same_date_and_total():
    from types import SimpleNamespace
    from datetime import datetime
    from main import flag_duplicate_expense_ids

    d = datetime(2026, 3, 1)
    exps = [
        SimpleNamespace(id=1, date=d, total=10.0),
        SimpleNamespace(id=2, date=datetime(2026, 3, 1, 14, 30), total=10.0),  # same day
        SimpleNamespace(id=3, date=datetime(2026, 3, 2), total=10.0),          # diff day
        SimpleNamespace(id=4, date=d, total=20.0),                             # diff total
    ]
    assert flag_duplicate_expense_ids(exps) == {1, 2}


def test_flag_duplicates_ignores_zero_total():
    from types import SimpleNamespace
    from datetime import datetime
    from main import flag_duplicate_expense_ids

    d = datetime(2026, 3, 1)
    exps = [
        SimpleNamespace(id=1, date=d, total=0.0),
        SimpleNamespace(id=2, date=d, total=0.0),
    ]
    assert flag_duplicate_expense_ids(exps) == set()


def test_flag_duplicates_none_when_all_distinct():
    from types import SimpleNamespace
    from datetime import datetime
    from main import flag_duplicate_expense_ids

    exps = [
        SimpleNamespace(id=1, date=datetime(2026, 3, 1), total=10.0),
        SimpleNamespace(id=2, date=datetime(2026, 3, 2), total=20.0),
    ]
    assert flag_duplicate_expense_ids(exps) == set()


def test_filter_client_expenses_by_any_workflow_status():
    from types import SimpleNamespace
    from main import filter_client_expenses

    exps = [
        SimpleNamespace(id=1, customer_id=1, status="pending", total=10.0),
        SimpleNamespace(id=2, customer_id=1, status="disputed", total=20.0),
        SimpleNamespace(id=3, customer_id=1, status="reimbursed", total=30.0),
    ]

    assert [e.id for e in filter_client_expenses(exps, {"status": "disputed"})] == [2]
    assert [e.id for e in filter_client_expenses(exps, {"status": "reimbursed"})] == [3]


def test_filter_client_expenses_by_total_range():
    from types import SimpleNamespace
    from main import filter_client_expenses

    exps = [
        SimpleNamespace(id=1, customer_id=1, status="pending", total=9.99),
        SimpleNamespace(id=2, customer_id=1, status="pending", total=25.0),
        SimpleNamespace(id=3, customer_id=1, status="pending", total=50.0),
    ]

    result = filter_client_expenses(exps, {"min_total": 10, "max_total": 25})

    assert [e.id for e in result] == [2]


def test_filter_client_expenses_by_duplicate_total_shortcut():
    from types import SimpleNamespace
    from main import filter_client_expenses

    exps = [
        SimpleNamespace(id=1, customer_id=1, status="pending", total=14.975),
        SimpleNamespace(id=2, customer_id=2, status="claimed", total=14.98),
        SimpleNamespace(id=3, customer_id=1, status="waiting", total=20.0),
    ]

    result = filter_client_expenses(exps, {"duplicate_total": 14.98})

    assert [e.id for e in result] == [1, 2]


def test_delete_client_expenses_removes_expense_and_events(session):
    from main import delete_client_expenses

    s, cust_id = session
    exp = ClientExpense(customer_id=cust_id, description="x", amount=10.0, total=10.0,
                        receipt_path="data/receipts/9_x.png")
    s.add(exp)
    s.commit()
    s.refresh(exp)
    s.add(ClientExpenseEvent(client_expense_id=exp.id, status="pending"))
    s.commit()
    exp_id = exp.id

    result = delete_client_expenses(s, [exp_id])

    assert result["deleted"] == 1
    assert result["skipped"] == 0
    assert "data/receipts/9_x.png" in result["deleted_paths"]
    assert s.get(ClientExpense, exp_id) is None
    remaining_events = s.exec(
        select(ClientExpenseEvent).where(ClientExpenseEvent.client_expense_id == exp_id)
    ).all()
    assert remaining_events == []


def test_delete_client_expenses_skips_invoice_attached(session):
    from main import delete_client_expenses

    s, cust_id = session
    exp = ClientExpense(customer_id=cust_id, description="x", amount=10.0, total=10.0,
                        invoice_id=123)
    s.add(exp)
    s.commit()
    s.refresh(exp)
    exp_id = exp.id

    result = delete_client_expenses(s, [exp_id])

    assert result["deleted"] == 0
    assert result["skipped"] == 1
    assert s.get(ClientExpense, exp_id) is not None  # still there


def test_reassign_client_expense_customer_updates_customer(session):
    from main import reassign_client_expense_customer

    s, cust_id = session
    other = Customer(name="Other Co", email="other@example.com")
    s.add(other)
    s.commit()
    s.refresh(other)
    exp = ClientExpense(customer_id=cust_id, description="x", amount=10.0, total=10.0)
    s.add(exp)
    s.commit()
    s.refresh(exp)

    updated = reassign_client_expense_customer(s, exp.id, other.id)
    assert updated.customer_id == other.id

    s.refresh(exp)
    assert exp.customer_id == other.id


def test_reassign_client_expense_customer_rejects_missing(session):
    import pytest
    from main import reassign_client_expense_customer

    s, _ = session
    with pytest.raises(ValueError):
        reassign_client_expense_customer(s, 9999, 1)


def test_client_expense_external_ref_defaults_to_none(session):
    s, cust_id = session
    exp = ClientExpense(customer_id=cust_id, description="x", amount=10.0, total=10.0)
    s.add(exp)
    s.commit()
    s.refresh(exp)
    assert exp.external_ref is None


def test_set_external_ref_updates_value(session):
    from main import set_client_expense_external_ref

    s, cust_id = session
    exp = ClientExpense(customer_id=cust_id, description="x", amount=10.0, total=10.0)
    s.add(exp)
    s.commit()
    s.refresh(exp)

    updated = set_client_expense_external_ref(s, exp.id, "  REF-001  ")
    assert updated.external_ref == "REF-001"  # trimmed
    s.refresh(exp)
    assert exp.external_ref == "REF-001"


def test_set_external_ref_allows_same_value_on_multiple_expenses(session):
    from main import set_client_expense_external_ref

    s, cust_id = session
    a = ClientExpense(customer_id=cust_id, description="a", amount=10.0, total=10.0)
    b = ClientExpense(customer_id=cust_id, description="b", amount=20.0, total=20.0)
    s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)

    set_client_expense_external_ref(s, a.id, "BATCH-42")
    set_client_expense_external_ref(s, b.id, "BATCH-42")
    s.refresh(a); s.refresh(b)
    assert a.external_ref == "BATCH-42"
    assert b.external_ref == "BATCH-42"


def test_set_external_ref_blank_clears_to_none(session):
    from main import set_client_expense_external_ref

    s, cust_id = session
    exp = ClientExpense(customer_id=cust_id, description="x", amount=10.0, total=10.0,
                        external_ref="OLD")
    s.add(exp)
    s.commit()
    s.refresh(exp)

    set_client_expense_external_ref(s, exp.id, "   ")
    s.refresh(exp)
    assert exp.external_ref is None


def test_set_external_ref_rejects_missing(session):
    import pytest
    from main import set_client_expense_external_ref

    s, _ = session
    with pytest.raises(ValueError):
        set_client_expense_external_ref(s, 9999, "REF")


def test_get_or_create_unassigned_customer_is_idempotent(session):
    from database import get_or_create_unassigned_customer

    s, _ = session
    c1 = get_or_create_unassigned_customer(s)
    c2 = get_or_create_unassigned_customer(s)

    assert c1.id == c2.id
    assert c1.name == "Unassigned"
    all_named = s.exec(select(Customer).where(Customer.name == "Unassigned")).all()
    assert len(all_named) == 1


def test_transition_updates_status_logs_event_and_sets_dates(session):
    from datetime import datetime
    from main import transition_client_expense

    s, cust_id = session
    exp = ClientExpense(customer_id=cust_id, description="x", amount=10.0, total=10.0)
    s.add(exp)
    s.commit()
    s.refresh(exp)

    transition_client_expense(s, exp.id, "claimed", notes="sent", now=datetime(2026, 6, 1))
    s.refresh(exp)
    assert exp.status == "claimed"
    assert exp.claim_date == datetime(2026, 6, 1)

    transition_client_expense(s, exp.id, "waiting")
    transition_client_expense(s, exp.id, "reimbursed", now=datetime(2026, 6, 20))
    s.refresh(exp)
    assert exp.status == "reimbursed"
    assert exp.reimbursed_date == datetime(2026, 6, 20)

    events = s.exec(
        select(ClientExpenseEvent).where(ClientExpenseEvent.client_expense_id == exp.id)
    ).all()
    assert [e.status for e in events] == ["claimed", "waiting", "reimbursed"]


def test_transition_rejects_invalid_edge(session):
    import pytest
    from main import transition_client_expense

    s, cust_id = session
    exp = ClientExpense(customer_id=cust_id, description="x", amount=10.0, total=10.0)
    s.add(exp)
    s.commit()
    s.refresh(exp)

    with pytest.raises(ValueError):
        transition_client_expense(s, exp.id, "reimbursed")  # pending -> reimbursed invalid
    s.refresh(exp)
    assert exp.status == "pending"


def _draft_invoice_with_taxable_line(s, cust_id):
    from database import Invoice, InvoiceItem
    svc = Service(name="Consulting", unit_price=100.0)
    s.add(svc)
    s.commit()
    s.refresh(svc)
    inv = Invoice(number="100200", customer_id=cust_id, subtotal=100.0,
                  tax_total=100.0 * 0.14975, total=100.0 * 1.14975, status="Draft")
    s.add(inv)
    s.commit()
    s.refresh(inv)
    s.add(InvoiceItem(invoice_id=inv.id, service_id=svc.id, description="Consulting",
                      quantity=1.0, unit_price=100.0, total=100.0))
    s.commit()
    return inv


def test_attach_adds_non_taxable_line_and_recomputes_totals(session):
    from database import InvoiceItem, get_or_create_reimbursable_service
    from main import attach_client_expense_to_invoice

    s, cust_id = session
    inv = _draft_invoice_with_taxable_line(s, cust_id)
    exp = ClientExpense(customer_id=cust_id, description="Cloud hosting",
                        amount=100.0, tps=5.0, tvq=9.98, total=114.98)
    s.add(exp)
    s.commit()
    s.refresh(exp)

    updated = attach_client_expense_to_invoice(s, exp.id, inv.id)

    # reimbursement is added to subtotal but NOT taxed; service line still taxed
    assert updated.subtotal == pytest.approx(214.98)
    assert updated.tax_total == pytest.approx(100.0 * 0.14975)
    assert updated.total == pytest.approx(214.98 + 100.0 * 0.14975)

    s.refresh(exp)
    assert exp.invoice_id == inv.id

    reimb_svc = get_or_create_reimbursable_service(s)
    lines = s.exec(select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id)).all()
    reimb_lines = [l for l in lines if l.service_id == reimb_svc.id]
    assert len(reimb_lines) == 1
    assert reimb_lines[0].total == pytest.approx(114.98)


def test_attach_rejects_non_draft_invoice(session):
    from main import attach_client_expense_to_invoice

    s, cust_id = session
    inv = _draft_invoice_with_taxable_line(s, cust_id)
    inv.status = "Sent"
    s.add(inv)
    s.commit()
    exp = ClientExpense(customer_id=cust_id, description="x", amount=10.0, total=10.0)
    s.add(exp)
    s.commit()
    s.refresh(exp)

    with pytest.raises(ValueError):
        attach_client_expense_to_invoice(s, exp.id, inv.id)

    s.refresh(exp)
    assert exp.invoice_id is None
