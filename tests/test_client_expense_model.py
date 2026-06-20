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
