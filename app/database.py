from datetime import datetime
from enum import Enum
from typing import List, Optional
from sqlmodel import Field, Relationship, SQLModel, Session, create_engine, select

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
    neq: Optional[str] = None # Numéro d'entreprise du Québec
    tps_number: Optional[str] = None
    tvq_number: Optional[str] = None
    currency: str = Field(default="CAD")
    language: str = Field(default="en") # en/es
    custom_template_path: Optional[str] = None

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
    created_at: datetime = Field(default_factory=datetime.utcnow)

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
    date: datetime = Field(default_factory=datetime.utcnow)
    due_date: Optional[datetime] = None
    customer_id: int = Field(foreign_key="customer.id")
    status: str = Field(default="Draft") # Draft, Sent, Paid, Cancelled
    subtotal: float = Field(default=0.0)
    tax_total: float = Field(default=0.0)
    total: float = Field(default=0.0)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

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
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Expense(SQLModel, table=True):
    """Business expenses linked to Chart of Accounts."""
    id: Optional[int] = Field(default=None, primary_key=True)
    date: datetime = Field(default_factory=datetime.utcnow)
    description: str
    amount: float = Field(default=0.0)  # pre-tax subtotal
    tps: float = Field(default=0.0)     # TPS amount (5% of amount if applicable)
    tvq: float = Field(default=0.0)     # TVQ amount (9.975% of amount if applicable)
    total: float = Field(default=0.0)   # amount + tps + tvq
    account_id: int = Field(foreign_key="account.id")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

# --- Database Engine ---

sqlite_file_name = "data/accounting.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

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
