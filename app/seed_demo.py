from datetime import datetime, timedelta
from sqlmodel import Session, select
from database import engine, Customer, Service, Invoice, InvoiceItem, RecurringProfile

def seed_demo_data():
    with Session(engine) as session:
        # Create a Demo Customer
        customer = Customer(name="Acme Corp", email="billing@acme.com", address="123 Industrial Way, Montreal, QC")
        session.add(customer)
        session.commit()
        session.refresh(customer)

        # Create a Demo Service
        service = Service(name="Strategic Consulting", description="Monthly architectural review", unit_price=2500.0)
        session.add(service)
        session.commit()
        session.refresh(service)

        # Create a Paid Invoice (Past)
        past_date = datetime.now() - timedelta(days=34)
        inv_paid = Invoice(
            number="INV-2026-001",
            date=past_date,
            customer_id=customer.id,
            subtotal=2500.0,
            tax_total=374.38, # 5% + 9.975%
            total=2874.38,
            status="Paid"
        )
        session.add(inv_paid)

        # Create an Overdue Invoice
        overdue_date = datetime.now() - timedelta(days=45)
        inv_overdue = Invoice(
            number="INV-2026-002",
            date=overdue_date,
            customer_id=customer.id,
            subtotal=1000.0,
            tax_total=149.75,
            total=1149.75,
            status="Overdue"
        )
        session.add(inv_overdue)

        # Create a Recurring Profile (Starts today to trigger the engine)
        profile = RecurringProfile(
            customer_id=customer.id,
            service_id=service.id,
            amount=2500.0,
            next_issue_date=datetime.now() - timedelta(minutes=5), # Triggerable
            frequency="monthly",
            is_active=True
        )
        session.add(profile)
        
        session.commit()
        print("🚀 Demo data seeded successfully.")

if __name__ == "__main__":
    seed_demo_data()
