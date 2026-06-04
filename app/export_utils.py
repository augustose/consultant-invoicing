import csv
import html
import io
import json
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from sqlmodel import Session, select

from database import Account, CompanySettings, Customer, Expense, Invoice, InvoiceItem

TPS_RATE = 0.05
TVQ_RATE = 0.09975

SUMMARY_HEADERS = [
    "period_start",
    "period_end",
    "generated_at",
    "currency",
    "invoice_count",
    "paid_invoice_count",
    "sent_invoice_count",
    "cancelled_invoice_count",
    "expense_count",
    "invoiced_subtotal",
    "invoiced_tax_total",
    "invoiced_total",
    "paid_subtotal",
    "paid_tax_total",
    "paid_total",
    "expense_subtotal",
    "expense_tps",
    "expense_tvq",
    "expense_total",
    "net_before_taxes",
]
INVOICE_HEADERS = [
    "invoice_number",
    "invoice_date",
    "due_date",
    "customer_name",
    "customer_email",
    "status",
    "subtotal",
    "tps",
    "tvq",
    "tax_total",
    "total",
    "notes",
]
EXPENSE_HEADERS = ["date", "description", "account_code", "account_name", "subtotal", "tps", "tvq", "total", "notes"]
TAX_HEADERS = ["metric", "amount"]
CUSTOMER_HEADERS = ["name", "contact", "email", "phone", "address", "currency"]
ACCOUNT_HEADERS = ["code", "name", "type", "description", "is_active", "is_system"]
INVOICE_ITEM_HEADERS = [
    "invoice_number",
    "invoice_date",
    "customer_name",
    "service_id",
    "description",
    "quantity",
    "unit_price",
    "line_total",
]

SUMMARY_TEXT_FIELDS = {"currency"}
INVOICE_TEXT_FIELDS = {"invoice_number", "customer_name", "customer_email", "status", "notes"}
EXPENSE_TEXT_FIELDS = {"description", "account_code", "account_name", "notes"}
TAX_TEXT_FIELDS = {"metric"}
CUSTOMER_TEXT_FIELDS = {"name", "contact", "email", "phone", "address", "currency"}
ACCOUNT_TEXT_FIELDS = {"code", "name", "type", "description"}
INVOICE_ITEM_TEXT_FIELDS = {"invoice_number", "customer_name", "service_id", "description"}


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


def safe_csv_text(value) -> str:
    value = text(value)
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def day(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def rows_to_csv_text(headers: list[str], rows: Iterable[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def csv_safe_rows(rows: Iterable[dict[str, str]], text_fields: set[str]) -> list[dict[str, str]]:
    return [
        {key: safe_csv_text(value) if key in text_fields else value for key, value in row.items()}
        for row in rows
    ]


def add_mapping(parent: ET.Element, tag: str, values: dict[str, str]) -> ET.Element:
    element = ET.SubElement(parent, tag)
    for key, value in values.items():
        child = ET.SubElement(element, key)
        child.text = text(value)
    return element


def add_text(parent: ET.Element, tag: str, value: str) -> ET.Element:
    child = ET.SubElement(parent, tag)
    child.text = text(value)
    return child


def render_audit_xml(context: AccountantExportContext) -> bytes:
    root = ET.Element("accountant_export")
    metadata = ET.SubElement(root, "metadata")
    add_text(metadata, "format", "audit_xml")
    add_text(metadata, "generated_at", context.summary["generated_at"])
    add_text(metadata, "currency", context.summary["currency"])
    add_text(metadata, "include_invoice_items", "true" if context.include_invoice_items else "false")

    company = ET.SubElement(root, "company")
    for key, value in context.company.items():
        add_text(company, key, value)

    period = ET.SubElement(root, "period")
    add_text(period, "start_date", context.summary["period_start"])
    add_text(period, "end_date", context.summary["period_end"])

    add_mapping(root, "summary", context.summary)
    accounts = ET.SubElement(root, "chart_of_accounts")
    for account in context.accounts:
        add_mapping(accounts, "account", account)
    customers = ET.SubElement(root, "customers")
    for customer in context.customers:
        add_mapping(customers, "customer", customer)
    invoices = ET.SubElement(root, "invoices")
    for invoice in context.invoices:
        add_mapping(invoices, "invoice", invoice)
    invoice_items = ET.SubElement(root, "invoice_items")
    for item in context.invoice_items:
        add_mapping(invoice_items, "invoice_item", item)
    expenses = ET.SubElement(root, "expenses")
    for expense in context.expenses:
        add_mapping(expenses, "expense", expense)
    tax_summary = ET.SubElement(root, "tax_summary")
    for tax in context.tax_report:
        add_mapping(tax_summary, "tax", tax)

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


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
        "currency": text(company["currency"] or "CAD"),
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


def export_filename(prefix: str, start_date: datetime, end_date: datetime, suffix: str) -> str:
    return f"{prefix}_{day(start_date)}_to_{day(end_date)}.{suffix}"


def metric_card(label: str, value: str, currency: str) -> str:
    escaped_label = html.escape(label)
    escaped_value = html.escape(value)
    escaped_currency = html.escape(currency)
    return f"""
        <div class="rounded border border-slate-200 bg-white p-4">
          <div class="text-sm font-medium text-slate-500">{escaped_label}</div>
          <div class="mt-2 text-2xl font-semibold text-slate-950">{escaped_value}</div>
          <div class="mt-1 text-xs uppercase tracking-wide text-slate-400">{escaped_currency}</div>
        </div>
    """


def file_description(name: str) -> str:
    descriptions = {
        "accountant_report.html": "Human-readable summary report for the export period.",
        "summary.csv": "One-row financial summary for the selected period.",
        "invoices.csv": "Invoice register for invoices dated within the selected period.",
        "expenses.csv": "Expense register for expenses dated within the selected period.",
        "tax_report.csv": "TPS and TVQ collection and expense tax summary.",
        "customers.csv": "Customers referenced by invoices in the selected period.",
        "chart_of_accounts.csv": "Chart of accounts snapshot.",
        "invoice_items.csv": "Invoice line items for invoices in the selected period.",
        "manifest.json": "Machine-readable file list and export metadata.",
    }
    return descriptions.get(name, "Export file.")


def render_accountant_html_report(context: AccountantExportContext, files: list[str]) -> str:
    company_name = html.escape(context.company.get("legal_name") or "Company")
    period_text = f"{day(context.start_date)} to {day(context.end_date)}"
    escaped_period = html.escape(period_text)
    currency = context.summary["currency"]
    cards = "\n".join(
        [
            metric_card("Invoiced total", context.summary["invoiced_total"], currency),
            metric_card("Paid total", context.summary["paid_total"], currency),
            metric_card("Expense total", context.summary["expense_total"], currency),
            metric_card("Net before taxes", context.summary["net_before_taxes"], currency),
        ]
    )
    count_cards = "\n".join(
        [
            metric_card("Invoices", context.summary["invoice_count"], ""),
            metric_card("Paid invoices", context.summary["paid_invoice_count"], ""),
            metric_card("Expenses", context.summary["expense_count"], ""),
            metric_card("Customers", str(len(context.customers)), ""),
            metric_card("Accounts", str(len(context.accounts)), ""),
        ]
    )
    tax_rows = "\n".join(
        f"""
          <tr class="border-t border-slate-200">
            <td class="py-2 pr-4 text-sm text-slate-700">{html.escape(row["metric"])}</td>
            <td class="py-2 text-right font-mono text-sm text-slate-700">{html.escape(row["amount"])}</td>
          </tr>
        """
        for row in context.tax_report
    )
    file_rows = "\n".join(
        f"""
          <tr class="border-t border-slate-200">
            <td class="py-2 pr-4 font-mono text-sm text-slate-700">{html.escape(name)}</td>
            <td class="py-2 text-sm text-slate-600">{html.escape(file_description(name))}</td>
          </tr>
        """
        for name in files
    )
    empty_note = ""
    if not context.invoices and not context.expenses:
        empty_note = """
        <section class="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          No invoices or expenses were found for this period.
        </section>
        """

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Accountant Export Report</title>
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="bg-slate-50 text-slate-900">
    <main class="mx-auto max-w-5xl px-6 py-10">
      <header class="mb-8">
        <p class="text-sm font-medium uppercase tracking-wide text-slate-500">Accountant export</p>
        <h1 class="mt-2 text-3xl font-semibold">{company_name}</h1>
        <p class="mt-2 text-slate-600">{escaped_period}</p>
        <p class="mt-1 text-sm text-slate-500">Generated {html.escape(context.summary["generated_at"])}</p>
      </header>

      {empty_note}

      <section class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards}
      </section>

      <section class="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {count_cards}
      </section>

      <section class="mt-8 rounded border border-slate-200 bg-white p-5">
        <h2 class="text-lg font-semibold">Tax summary</h2>
        <table class="mt-4 w-full border-collapse text-left">
          <tbody>{tax_rows}</tbody>
        </table>
      </section>

      <section class="mt-8 rounded border border-slate-200 bg-white p-5">
        <h2 class="text-lg font-semibold">Files included</h2>
        <table class="mt-4 w-full border-collapse text-left">
          <thead>
            <tr class="text-sm text-slate-500">
              <th class="pb-2 pr-4 font-medium">File</th>
              <th class="pb-2 font-medium">Description</th>
            </tr>
          </thead>
          <tbody>{file_rows}</tbody>
        </table>
        <p class="mt-4 text-sm text-slate-500">
          CSV files are the primary accountant-friendly interchange format. They may be imported or reviewed manually depending on the accountant's software.
        </p>
      </section>
    </main>
  </body>
</html>
"""


def build_csv_files(context: AccountantExportContext) -> dict[str, str]:
    files = {
        "summary.csv": rows_to_csv_text(SUMMARY_HEADERS, csv_safe_rows([context.summary], SUMMARY_TEXT_FIELDS)),
        "invoices.csv": rows_to_csv_text(INVOICE_HEADERS, csv_safe_rows(context.invoices, INVOICE_TEXT_FIELDS)),
        "expenses.csv": rows_to_csv_text(EXPENSE_HEADERS, csv_safe_rows(context.expenses, EXPENSE_TEXT_FIELDS)),
        "tax_report.csv": rows_to_csv_text(TAX_HEADERS, csv_safe_rows(context.tax_report, TAX_TEXT_FIELDS)),
        "customers.csv": rows_to_csv_text(CUSTOMER_HEADERS, csv_safe_rows(context.customers, CUSTOMER_TEXT_FIELDS)),
        "chart_of_accounts.csv": rows_to_csv_text(
            ACCOUNT_HEADERS,
            csv_safe_rows(context.accounts, ACCOUNT_TEXT_FIELDS),
        ),
    }
    if context.include_invoice_items:
        files["invoice_items.csv"] = rows_to_csv_text(
            INVOICE_ITEM_HEADERS,
            csv_safe_rows(context.invoice_items, INVOICE_ITEM_TEXT_FIELDS),
        )
    return files


def validate_export_range(start_date: datetime, end_date: datetime) -> None:
    if end_date < start_date:
        raise ValueError("End date must be on or after start date")


def create_accountant_csv_zip(
    session: Session,
    start_date: datetime,
    end_date: datetime,
    include_invoice_items: bool = False,
    export_dir: str | Path = "data/exports",
) -> Path:
    validate_export_range(start_date, end_date)
    context = build_accountant_export_context(
        session=session,
        start_date=start_date,
        end_date=end_date,
        include_invoice_items=include_invoice_items,
    )
    csv_files = build_csv_files(context)
    files = ["accountant_report.html", *csv_files.keys(), "manifest.json"]
    manifest = {
        "format": "csv_zip",
        "period_start": day(start_date),
        "period_end": day(end_date),
        "generated_at": context.generated_at.isoformat(timespec="seconds"),
        "include_invoice_items": include_invoice_items,
        "files": files,
    }

    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)
    zip_path = export_path / export_filename("accountant_export", start_date, end_date, "zip")

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("accountant_report.html", render_accountant_html_report(context, files))
        for name, content in csv_files.items():
            archive.writestr(name, content)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))

    return zip_path


def create_accountant_audit_xml(
    session: Session,
    start_date: datetime,
    end_date: datetime,
    include_invoice_items: bool = False,
    export_dir: str | Path = "data/exports",
) -> Path:
    validate_export_range(start_date, end_date)
    context = build_accountant_export_context(session, start_date, end_date, include_invoice_items)
    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)
    xml_path = export_path / export_filename("accountant_audit", start_date, end_date, "xml")
    xml_path.write_bytes(render_audit_xml(context))
    return xml_path
