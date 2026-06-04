import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from sqlmodel import Session, select

from database import Account, CompanySettings, Customer, Expense, Invoice, InvoiceItem

TPS_RATE = 0.05
TVQ_RATE = 0.09975


@dataclass
class AccountantExportContext:
    start_date: datetime
    end_date: datetime
    generated_at: datetime
    company: dict[str, str]
    summary: dict[str, str]
    invoices: list[dict[str, str]]
    expenses: list[dict[str, str]]
    tax_report: list[dict[str, str]]
    customers: list[dict[str, str]]
    accounts: list[dict[str, str]]
    invoice_items: list[dict[str, str]]
    include_invoice_items: bool


def money(value: float | int | None) -> str:
    return str(
        Decimal(str(value or 0)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    )


def text(value) -> str:
    return "" if value is None else str(value)


def day(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def rows_to_csv_text(headers: list[str], rows: Iterable[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def inclusive_end(end_date: datetime) -> datetime:
    return end_date.replace(hour=23, minute=59, second=59, microsecond=999999)


def company_dict(settings: CompanySettings | None) -> dict[str, str]:
    if not settings:
        return {
            "legal_name": "",
            "address": "",
            "phone": "",
            "email": "",
            "neq": "",
            "tps_number": "",
            "tvq_number": "",
            "currency": "CAD",
        }
    return {
        "legal_name": text(settings.legal_name),
        "address": text(settings.address),
        "phone": text(settings.phone),
        "email": text(settings.email),
        "neq": text(settings.neq),
        "tps_number": text(settings.tps_number),
        "tvq_number": text(settings.tvq_number),
        "currency": text(settings.currency or "CAD"),
    }


def build_accountant_export_context(
    session: Session,
    start_date: datetime,
    end_date: datetime,
    include_invoice_items: bool = False,
    generated_at: datetime | None = None,
) -> AccountantExportContext:
    generated_at = generated_at or datetime.now(UTC)
    end_bound = inclusive_end(end_date)
    settings = session.exec(select(CompanySettings)).first()
    company = company_dict(settings)

    invoices = session.exec(
        select(Invoice)
        .where(Invoice.date >= start_date, Invoice.date <= end_bound)
        .order_by(Invoice.date, Invoice.number)
    ).all()
    expenses = session.exec(
        select(Expense)
        .where(Expense.date >= start_date, Expense.date <= end_bound)
        .order_by(Expense.date, Expense.id)
    ).all()
    customers = session.exec(select(Customer).order_by(Customer.name)).all()
    accounts = session.exec(select(Account).order_by(Account.code)).all()
    invoice_ids = [invoice.id for invoice in invoices if invoice.id is not None]
    customer_ids = {invoice.customer_id for invoice in invoices}
    customer_map = {customer.id: customer for customer in customers}
    account_map = {account.id: account for account in accounts}

    paid_invoices = [invoice for invoice in invoices if invoice.status == "Paid"]
    tps_collected = sum(invoice.subtotal * TPS_RATE for invoice in paid_invoices)
    tvq_collected = sum(invoice.subtotal * TVQ_RATE for invoice in paid_invoices)
    expense_tps = sum(expense.tps for expense in expenses)
    expense_tvq = sum(expense.tvq for expense in expenses)

    invoice_rows = []
    for invoice in invoices:
        customer = customer_map.get(invoice.customer_id)
        invoice_rows.append(
            {
                "invoice_number": text(invoice.number),
                "invoice_date": day(invoice.date),
                "due_date": day(invoice.due_date),
                "customer_name": text(customer.name if customer else ""),
                "customer_email": text(customer.email if customer else ""),
                "status": text(invoice.status),
                "subtotal": money(invoice.subtotal),
                "tps": money(invoice.subtotal * TPS_RATE),
                "tvq": money(invoice.subtotal * TVQ_RATE),
                "tax_total": money(invoice.tax_total),
                "total": money(invoice.total),
                "notes": text(invoice.notes),
            }
        )

    expense_rows = []
    for expense in expenses:
        account = account_map.get(expense.account_id)
        expense_rows.append(
            {
                "date": day(expense.date),
                "description": text(expense.description),
                "account_code": text(account.code if account else ""),
                "account_name": text(account.name if account else ""),
                "subtotal": money(expense.amount),
                "tps": money(expense.tps),
                "tvq": money(expense.tvq),
                "total": money(expense.total),
                "notes": text(expense.notes),
            }
        )

    used_customers = [customer for customer in customers if customer.id in customer_ids]
    customer_rows = [
        {
            "name": text(customer.name),
            "contact": text(customer.contact),
            "email": text(customer.email),
            "phone": text(customer.phone),
            "address": text(customer.address),
            "currency": text(customer.currency),
        }
        for customer in used_customers
    ]
    account_rows = [
        {
            "code": text(account.code),
            "name": text(account.name),
            "type": text(account.type.value if hasattr(account.type, "value") else account.type),
            "description": text(account.description),
            "is_active": "true" if account.is_active else "false",
            "is_system": "true" if account.is_system else "false",
        }
        for account in accounts
    ]

    item_rows: list[dict[str, str]] = []
    if include_invoice_items and invoice_ids:
        items = session.exec(
            select(InvoiceItem)
            .where(InvoiceItem.invoice_id.in_(invoice_ids))
            .order_by(InvoiceItem.invoice_id, InvoiceItem.id)
        ).all()
        invoice_map = {invoice.id: invoice for invoice in invoices}
        for item in items:
            invoice = invoice_map.get(item.invoice_id)
            customer = customer_map.get(invoice.customer_id) if invoice else None
            item_rows.append(
                {
                    "invoice_number": text(invoice.number if invoice else ""),
                    "invoice_date": day(invoice.date if invoice else None),
                    "customer_name": text(customer.name if customer else ""),
                    "service_id": text(item.service_id),
                    "description": text(item.description),
                    "quantity": money(item.quantity),
                    "unit_price": money(item.unit_price),
                    "line_total": money(item.total),
                }
            )

    summary = {
        "period_start": day(start_date),
        "period_end": day(end_date),
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "currency": company["currency"] or "CAD",
        "invoice_count": str(len(invoices)),
        "paid_invoice_count": str(len(paid_invoices)),
        "sent_invoice_count": str(len([invoice for invoice in invoices if invoice.status == "Sent"])),
        "cancelled_invoice_count": str(len([invoice for invoice in invoices if invoice.status == "Cancelled"])),
        "expense_count": str(len(expenses)),
        "invoiced_subtotal": money(sum(invoice.subtotal for invoice in invoices)),
        "invoiced_tax_total": money(sum(invoice.tax_total for invoice in invoices)),
        "invoiced_total": money(sum(invoice.total for invoice in invoices)),
        "paid_subtotal": money(sum(invoice.subtotal for invoice in paid_invoices)),
        "paid_tax_total": money(sum(invoice.tax_total for invoice in paid_invoices)),
        "paid_total": money(sum(invoice.total for invoice in paid_invoices)),
        "expense_subtotal": money(sum(expense.amount for expense in expenses)),
        "expense_tps": money(expense_tps),
        "expense_tvq": money(expense_tvq),
        "expense_total": money(sum(expense.total for expense in expenses)),
        "net_before_taxes": money(
            sum(invoice.subtotal for invoice in paid_invoices) - sum(expense.amount for expense in expenses)
        ),
    }
    tax_report = [
        {"metric": "TPS collected from paid invoices", "amount": money(tps_collected)},
        {"metric": "TVQ collected from paid invoices", "amount": money(tvq_collected)},
        {"metric": "TPS recorded on expenses", "amount": money(expense_tps)},
        {"metric": "TVQ recorded on expenses", "amount": money(expense_tvq)},
        {"metric": "Net TPS payable estimate", "amount": money(tps_collected - expense_tps)},
        {"metric": "Net TVQ payable estimate", "amount": money(tvq_collected - expense_tvq)},
    ]
    return AccountantExportContext(
        start_date=start_date,
        end_date=end_date,
        generated_at=generated_at,
        company=company,
        summary=summary,
        invoices=invoice_rows,
        expenses=expense_rows,
        tax_report=tax_report,
        customers=customer_rows,
        accounts=account_rows,
        invoice_items=item_rows,
        include_invoice_items=include_invoice_items,
    )
