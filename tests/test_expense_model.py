import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import pytest
from sqlmodel import SQLModel, Session, create_engine, select
from database import Expense, Account, AccountType

@pytest.fixture
def engine_and_session():
    test_engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        acc = Account(code="5999", name="Test Expense", type=AccountType.EXPENSE)
        session.add(acc)
        session.commit()
        session.refresh(acc)
        yield test_engine, session, acc.id

def test_expense_can_be_created(engine_and_session):
    _, session, acc_id = engine_and_session
    exp = Expense(
        description="Phone bill",
        amount=80.0,
        tps=4.0,
        tvq=7.98,
        total=91.98,
        account_id=acc_id,
    )
    session.add(exp)
    session.commit()
    session.refresh(exp)
    assert exp.id is not None
    assert exp.description == "Phone bill"
    assert exp.total == 91.98

def test_expense_total_fields(engine_and_session):
    _, session, acc_id = engine_and_session
    exp = Expense(description="No tax", amount=100.0, total=100.0, account_id=acc_id)
    session.add(exp)
    session.commit()
    session.refresh(exp)
    assert exp.tps == 0.0
    assert exp.tvq == 0.0
