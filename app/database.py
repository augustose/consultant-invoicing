from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from sqlmodel import Field, Relationship, SQLModel, Session, create_engine, select


def utc_now() -> datetime:
    """Naive UTC timestamp (drop-in for the deprecated datetime.utcnow()).

    Returns a naive datetime so it stays comparable with the naive local
    datetimes used elsewhere in the app (filters, recurrence, aging math).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

# --- Quebec tax constants (TPS 5% + TVQ 9.975%) ---
TPS_RATE = 0.05
TVQ_RATE = 0.09975
COMBINED_TAX_RATE = TPS_RATE + TVQ_RATE  # 0.14975


def tax_breakdown(tax_total):
    """Split a stored invoice `tax_total` into its (TPS, TVQ) components.

    Derives the split from the actual tax charged rather than from the subtotal,
    so it stays correct when an invoice contains non-taxable (reimbursement)
    lines. For an all-taxable invoice this equals subtotal*0.05 / subtotal*0.09975.
    """
    if COMBINED_TAX_RATE == 0:
        return 0.0, 0.0
    return tax_total * TPS_RATE / COMBINED_TAX_RATE, tax_total * TVQ_RATE / COMBINED_TAX_RATE


# --- Enums for Accounting Standards ---

class AccountType(str, Enum):
    ASSET = "Asset"
    LIABILITY = "Liability"
    EQUITY = "Equity"
    INCOME = "Income"
    EXPENSE = "Expense"

# --- Models ---

class Account(SQLModel, table=True):
    """Chart of Accounts - The backbone of the system."""
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True) # e.g., "1000", "2000"
    name: str = Field(index=True) # e.g., "Cash", "Sales", "TPS Payable"
    description: Optional[str] = None
    type: AccountType
    is_system: bool = Field(default=False) # Accounts that cannot be deleted
    is_active: bool = Field(default=True)

    # Relationships (Future use for transactions)
    # transactions: List["Transaction"] = Relationship(back_populates="account")

class CompanySettings(SQLModel, table=True):
    """Legal and regional settings."""
    id: Optional[int] = Field(default=None, primary_key=True)
    legal_name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    neq: Optional[str] = None # Numéro d'entreprise du Québec
    tps_number: Optional[str] = None
    tvq_number: Optional[str] = None
    currency: str = Field(default="CAD")
    language: str = Field(default="en") # en/es
    custom_template_path: Optional[str] = None
    # Optional self-hosted Ollama for receipt extraction (see ollama_utils.py).
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None

class TaxRate(SQLModel, table=True):
    """Tax configuration (e.g., TPS, TVQ)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str # e.g., "TPS"
    rate: float # e.g., 0.05
    description: Optional[str] = None
    is_active: bool = Field(default=True)

class Customer(SQLModel, table=True):
    """Client profiles."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    contact: Optional[str] = None
    email: str = Field(index=True, unique=True)
    phone: Optional[str] = None
    address: Optional[str] = None
    currency: str = Field(default="CAD")
    created_at: datetime = Field(default_factory=utc_now)

class Service(SQLModel, table=True):
    """Catalog of services/products."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    unit_price: float = Field(default=0.0)
    # Default tax category could be linked here
    is_active: bool = Field(default=True)

class Invoice(SQLModel, table=True):
    """Invoices issued to customers."""
    id: Optional[int] = Field(default=None, primary_key=True)
    number: str = Field(index=True, unique=True) # e.g., INV-1001
    date: datetime = Field(default_factory=utc_now)
    due_date: Optional[datetime] = None
    customer_id: int = Field(foreign_key="customer.id")
    status: str = Field(default="Draft") # Draft, Sent, Paid, Cancelled
    subtotal: float = Field(default=0.0)
    tax_total: float = Field(default=0.0)
    total: float = Field(default=0.0)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)

class InvoiceItem(SQLModel, table=True):
    """Lines of detail in an invoice."""
    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoice.id")
    service_id: int = Field(foreign_key="service.id")
    description: str
    quantity: float = Field(default=1.0)
    unit_price: float
    tax_rate_id: Optional[int] = Field(default=None, foreign_key="taxrate.id")
    total: float

class RecurringProfile(SQLModel, table=True):
    """Configuration for recurring billing."""
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id")
    service_id: int = Field(foreign_key="service.id")
    frequency: str = Field(default="monthly") # monthly, weekly, custom
    amount: float
    is_active: bool = Field(default=True)
    next_issue_date: datetime
    auto_send: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)

class Expense(SQLModel, table=True):
    """Business expenses linked to Chart of Accounts."""
    id: Optional[int] = Field(default=None, primary_key=True)
    date: datetime = Field(default_factory=utc_now)
    description: str
    amount: float = Field(default=0.0)  # pre-tax subtotal
    tps: float = Field(default=0.0)     # TPS amount (5% of amount if applicable)
    tvq: float = Field(default=0.0)     # TVQ amount (9.975% of amount if applicable)
    total: float = Field(default=0.0)   # amount + tps + tvq
    account_id: int = Field(foreign_key="account.id")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)

class ClientExpense(SQLModel, table=True):
    """An expense paid on behalf of a client, tracked through reimbursement.

    Distinct from `Expense` (business expense → Chart of Accounts). The amounts
    are tax-inclusive out-of-pocket costs to be reimbursed by the client.
    `status` is a plain string (validated in app helpers, not at the DB level),
    matching the convention used by `Invoice.status`.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id")
    description: str
    date: datetime = Field(default_factory=utc_now)
    amount: float = Field(default=0.0)  # pre-tax subtotal
    tps: float = Field(default=0.0)
    tvq: float = Field(default=0.0)
    total: float = Field(default=0.0)   # amount + tps + tvq (tax-inclusive)
    status: str = Field(default="pending")
    receipt_path: Optional[str] = None
    claim_date: Optional[datetime] = None
    reimbursed_date: Optional[datetime] = None
    invoice_id: Optional[int] = Field(default=None, foreign_key="invoice.id")
    is_recurring: bool = Field(default=False)
    recurrence_day: Optional[int] = None
    next_due_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

class ClientExpenseEvent(SQLModel, table=True):
    """Append-only audit log of every client-expense status change."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_expense_id: int = Field(foreign_key="clientexpense.id")
    status: str
    changed_at: datetime = Field(default_factory=utc_now)
    notes: Optional[str] = None

REIMBURSABLE_SERVICE_NAME = "Reimbursable Expense"

def get_or_create_reimbursable_service(session: Session) -> Service:
    """The catalog service used for client-expense reimbursement invoice lines.

    `InvoiceItem.service_id` is required, so reimbursement lines point at this
    single shared service rather than nulling the column.
    """
    existing = session.exec(
        select(Service).where(Service.name == REIMBURSABLE_SERVICE_NAME)
    ).first()
    if existing:
        return existing
    svc = Service(
        name=REIMBURSABLE_SERVICE_NAME,
        description="Pass-through reimbursement of a client expense (tax-inclusive).",
        unit_price=0.0,
    )
    session.add(svc)
    session.commit()
    session.refresh(svc)
    return svc

# --- Database Engine ---

sqlite_file_name = "data/accounting.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=False)

def add_missing_columns(target_engine, table: str, columns: dict) -> list:
    """Idempotently add absent columns to an existing SQLite table.

    `create_all` creates new tables but never ALTERs existing ones, so columns
    added to a model after a DB already exists need this lightweight migration.
    `columns` maps column name → SQL type. Returns the names actually added.
    """
    from sqlalchemy import text

    with target_engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).all()}
        added = []
        for name, sql_type in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
                added.append(name)
        conn.commit()
    return added


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    # Backfill columns added to existing tables after their first creation.
    add_missing_columns(engine, "companysettings", {
        "ollama_url": "TEXT",
        "ollama_model": "TEXT",
    })

def seed_initial_data():
    """Populate default Chart of Accounts for a Quebec-based consultant."""
    with Session(engine) as session:
        # Check if we already have accounts
        statement = select(Account)
        results = session.exec(statement).first()
        if results:
            return

        # Default Accounts
        defaults = [
            # Assets
            Account(code="1000", name="Cash on Hand", type=AccountType.ASSET, is_system=True),
            Account(code="1100", name="Accounts Receivable", type=AccountType.ASSET, is_system=True),
            Account(code="1200", name="Bank Account (RBC)", type=AccountType.ASSET),
            
            # Liabilities
            Account(code="2000", name="Accounts Payable", type=AccountType.LIABILITY, is_system=True),
            Account(code="2100", name="TPS Payable", type=AccountType.LIABILITY, is_system=True),
            Account(code="2200", name="TVQ Payable", type=AccountType.LIABILITY, is_system=True),
            
            # Income
            Account(code="4000", name="Consulting Revenue", type=AccountType.INCOME, is_system=True),
            Account(code="4100", name="Other Income", type=AccountType.INCOME),
            
            # Expenses
            Account(code="5000", name="Software & Subscriptions", type=AccountType.EXPENSE),
            Account(code="5100", name="Office Supplies", type=AccountType.EXPENSE),
            Account(code="5200", name="Travel Expenses", type=AccountType.EXPENSE),
        ]
        
        # Default Taxes for Quebec
        taxes = [
            TaxRate(name="TPS", rate=0.05, description="Fédéral (GST)"),
            TaxRate(name="TVQ", rate=0.09975, description="Provincial (QST)"),
        ]
        
        session.add_all(defaults)
        session.add_all(taxes)
        session.commit()

if __name__ == "__main__":
    import os
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    create_db_and_tables()
    seed_initial_data()
    print("✅ Database initialized with standard Chart of Accounts for Québec.")
