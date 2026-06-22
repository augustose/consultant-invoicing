import calendar
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from nicegui import app, ui, run, context
from sqlmodel import Session, select
from starlette.responses import HTMLResponse, Response
from database import engine, Account, TaxRate, AccountType, Customer, Service, Invoice, InvoiceItem, RecurringProfile, CompanySettings, Expense, ClientExpense, ClientExpenseEvent, get_or_create_reimbursable_service, get_or_create_unassigned_customer, tax_breakdown, TPS_RATE, TVQ_RATE, COMBINED_TAX_RATE, utc_now
from pdf_utils import build_invoice_pdf
from template_utils import TemplateManager
from export_utils import create_accountant_audit_xml, create_accountant_csv_zip, validate_export_range
import log_config  # noqa: F401 — initializes logging on import
from loguru import logger
import os, json, csv, base64
from ollama_utils import (
    ollama_is_ready, list_models, probe_model_is_vision,
    normalize_to_image, extract_receipt, read_upload_file,
)

# Serve stored receipts read-only for inline previews (localhost single-user app).
os.makedirs('data/receipts', exist_ok=True)
app.add_media_files('/receipts', 'data/receipts')
import plotly.graph_objects as go
from collections import defaultdict

LAST_EXTERNAL_INVOICE_NUMBER = 100122
INVOICE_STATUS_FILTERS = ["All", "Draft", "Sent", "Overdue", "Paid", "Written Off", "Cancelled"]
INVOICE_PERIOD_FILTERS = ["All Time", "This Month", "Last Month", "This Year", "Last Year", "Custom"]
INVOICE_SORT_OPTIONS = ["Date newest", "Date oldest", "Total high", "Total low", "Customer A-Z", "Invoice #"]

# Quebec tax constants (TPS_RATE/TVQ_RATE/COMBINED_TAX_RATE) and tax_breakdown
# are imported from database.py as the single source of truth.

# --- Client expense workflow ---
CLIENT_EXPENSE_TRANSITIONS = {
    "pending": ("claimed",),
    "claimed": ("waiting",),
    "waiting": ("disputed", "reimbursed"),
    "disputed": ("reimbursed", "written_off"),
    "reimbursed": (),
    "written_off": (),
}
CLIENT_EXPENSE_STATUSES = tuple(CLIENT_EXPENSE_TRANSITIONS.keys())
FOLLOWUP_THRESHOLD_DAYS = 30
REIMBURSABLE_SERVICE_NAME = "Reimbursable Expense"


def client_is_active(client):
    """Return False after NiceGUI has deleted the browser client."""
    return client is not None and not getattr(client, "_deleted", False)


def safe_client_notify(client, message, **kwargs):
    """Send a notification only while the originating NiceGUI client exists."""
    if not client_is_active(client):
        logger.info(f"Skipped notification for deleted client: {message}")
        return False

    options = {"message": str(message), "position": kwargs.pop("position", "bottom")}
    if "multi_line" in kwargs:
        options["multiLine"] = kwargs.pop("multi_line")
    if "close_button" in kwargs:
        options["closeBtn"] = kwargs.pop("close_button")
    options.update({key: value for key, value in kwargs.items() if value is not None})
    client.outbox.enqueue_message("notify", options, client.id)
    return True


def safe_notification_dismiss(notification):
    """Dismiss a NiceGUI notification if its client still exists."""
    if notification is None or not client_is_active(getattr(notification, "client", None)):
        return False
    notification.dismiss()
    return True


def compute_tax_split(amount, apply_tps, apply_tvq):
    """(tps, tvq, total) for a pre-tax amount. Quebec TPS/TVQ, rounded to cents."""
    amount = amount or 0
    tps = round(amount * TPS_RATE, 2) if apply_tps else 0.0
    tvq = round(amount * TVQ_RATE, 2) if apply_tvq else 0.0
    return tps, tvq, round(amount + tps + tvq, 2)


def compute_invoice_totals(items):
    """(subtotal, tax_total, total) over (line_total, taxable) pairs.

    Tax is applied only to taxable lines; non-taxable lines (e.g. reimbursed
    client expenses already tax-inclusive) are added to the subtotal untaxed.
    When every line is taxable this equals the legacy `subtotal * COMBINED_TAX_RATE`.
    """
    subtotal = sum((line_total or 0) for line_total, _ in items)
    taxable_base = sum((line_total or 0) for line_total, taxable in items if taxable)
    tax_total = taxable_base * COMBINED_TAX_RATE
    return subtotal, tax_total, subtotal + tax_total


def client_expense_next_states(status):
    """Valid next statuses for a client expense (empty for terminal states)."""
    return CLIENT_EXPENSE_TRANSITIONS.get(status, ())


def client_expense_can_transition(current, target):
    return target in client_expense_next_states(current)


def advance_recurrence_date(current, day):
    """Same day next month, clamped to the last valid day of shorter months."""
    month = current.month + 1
    year = current.year
    if month > 12:
        month = 1
        year += 1
    last_day = calendar.monthrange(year, month)[1]
    return current.replace(year=year, month=month, day=min(day, last_day))


def client_expense_needs_followup(status, last_change, today, threshold=FOLLOWUP_THRESHOLD_DAYS):
    """True when an expense has sat in `waiting` longer than the threshold."""
    if status != "waiting":
        return False
    return (today - last_change).days > threshold


def currency_cents(value):
    """Currency comparison key using normal half-up cent rounding."""
    try:
        return int((Decimal(str(value or 0)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return 0


def receipt_preview_url(receipt_path):
    """Return a `/receipts/...` URL to preview a receipt, or None.

    Image receipts are served directly; PDF receipts are rendered to a cached
    first-page `*.thumb.png` so they can preview as an image too.
    """
    if not receipt_path or not os.path.exists(receipt_path):
        return None
    path_for_url = receipt_path
    if receipt_path.lower().endswith('.pdf'):
        thumb = receipt_path + '.thumb.png'
        if not os.path.exists(thumb):
            try:
                from ollama_utils import pdf_first_page_to_png
                with open(receipt_path, 'rb') as f:
                    png = pdf_first_page_to_png(f.read())
                with open(thumb, 'wb') as f:
                    f.write(png)
            except Exception:
                return None
        path_for_url = thumb
    return '/receipts/' + os.path.basename(path_for_url)


def flag_duplicate_expense_ids(expenses):
    """Return the ids of expenses sharing the same (calendar date, total).

    Display-only duplicate detection. Zero-total rows are ignored so a batch of
    weak/empty extractions isn't all flagged against each other.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for exp in expenses:
        if not exp.total:
            continue
        day = exp.date.date() if hasattr(exp.date, "date") else exp.date
        groups[(day, currency_cents(exp.total))].append(exp.id)
    flagged = set()
    for ids in groups.values():
        if len(ids) > 1:
            flagged.update(ids)
    return flagged


def _optional_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def filter_client_expenses(expenses, filters):
    """Apply list-page filters to client expenses while preserving row order."""
    customer = filters.get("customer", "All")
    status = filters.get("status", "All")
    min_total = _optional_float(filters.get("min_total"))
    max_total = _optional_float(filters.get("max_total"))
    duplicate_total = _optional_float(filters.get("duplicate_total"))

    filtered = list(expenses)

    if customer != "All":
        filtered = [exp for exp in filtered if getattr(exp, "customer_id", None) == customer]
    if status != "All":
        filtered = [exp for exp in filtered if getattr(exp, "status", None) == status]
    if min_total is not None:
        filtered = [exp for exp in filtered if (getattr(exp, "total", 0) or 0) >= min_total]
    if max_total is not None:
        filtered = [exp for exp in filtered if (getattr(exp, "total", 0) or 0) <= max_total]
    if duplicate_total is not None:
        filtered = [
            exp for exp in filtered
            if currency_cents(getattr(exp, "total", 0)) == currency_cents(duplicate_total)
        ]

    return filtered


def sanitize_receipt_filename(name):
    """Safe basename: drop directories, collapse unsafe chars, keep the extension."""
    base = os.path.basename(str(name or "")).strip()
    base = base.replace("..", "")
    stem, ext = os.path.splitext(base)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_.")
    ext = re.sub(r"[^A-Za-z0-9.]+", "", ext)
    cleaned = f"{stem}{ext}"
    return cleaned or "receipt"


def next_invoice_number(invoices) -> str:
    numeric_numbers = []
    for invoice in invoices:
        number = str(getattr(invoice, "number", "")).strip()
        if number.isdigit():
            numeric_numbers.append(int(number))
    return str(max(numeric_numbers + [LAST_EXTERNAL_INVOICE_NUMBER]) + 1)


def invoice_item_description(service) -> str:
    description = str(getattr(service, "description", "") or "").strip()
    if description:
        return f"{service.name}\n{description}"
    return service.name


def can_cancel_invoice(status: str) -> bool:
    return status == "Draft"


def invoice_due_date(invoice):
    return invoice.due_date or (invoice.date + timedelta(days=30))


def invoice_display_status(invoice, today=None) -> str:
    today = today or datetime.today()
    if invoice.status == "Sent" and invoice_due_date(invoice).date() < today.date():
        return "Overdue"
    return invoice.status


def invoice_filter_period_bounds(period: str, today=None):
    today = today or datetime.today()
    first_this_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    first_this_year = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = first_this_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_year = today.year - 1
    last_year_start = datetime(last_year, 1, 1)
    last_year_end = datetime(last_year, 12, 31, 23, 59, 59, 999999)

    if period == "This Month":
        return first_this_month, today
    if period == "Last Month":
        return last_month_start, last_month_end
    if period == "This Year":
        return first_this_year, today
    if period == "Last Year":
        return last_year_start, last_year_end
    return None, None


def can_mark_invoice_paid(status: str) -> bool:
    return status in {"Sent", "Overdue"}


def can_write_off_invoice(status: str) -> bool:
    return status in {"Sent", "Overdue"}


def invoice_list_columns(customer_label: str):
    return [
        {'name': 'num', 'label': '#', 'field': 'number', 'align': 'left'},
        {'name': 'date', 'label': 'Date', 'field': 'date_fmt', 'align': 'left'},
        {'name': 'cust', 'label': customer_label, 'field': 'cname', 'align': 'left'},
        {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'center'},
        {'name': 'total', 'label': 'Total', 'field': 'total_fmt', 'align': 'right'},
        {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
    ]


def build_invoice_list_row(inv, customers, today=None):
    display_status = invoice_display_status(inv, today=today)
    return {
        **inv.model_dump(),
        'date_fmt': inv.date.strftime('%Y-%m-%d'),
        'raw_status': inv.status,
        'status': display_status,
        'cname': next((c.name for c in customers if c.id == inv.customer_id), '?'),
        'total_fmt': f'${inv.total:,.2f}',
        'can_send': inv.status == 'Draft',
        'can_cancel': can_cancel_invoice(inv.status),
        'can_mark_paid': can_mark_invoice_paid(display_status),
        'can_write_off': can_write_off_invoice(display_status),
    }


def filter_and_sort_invoice_rows(rows, filters):
    query = str(filters.get("query") or "").strip().lower()
    status = filters.get("status") or "All"
    customer_id = filters.get("customer_id")
    d_from = filters.get("from")
    d_to = filters.get("to")
    sort = filters.get("sort") or "Date newest"

    filtered = list(rows)

    if query:
        filtered = [
            row for row in filtered
            if query in str(row.get("number", "")).lower()
            or query in str(row.get("cname", "")).lower()
        ]

    if status and status != "All":
        filtered = [row for row in filtered if row.get("status") == status]

    if customer_id not in (None, "All"):
        filtered = [row for row in filtered if row.get("customer_id") == customer_id]

    if d_from is not None:
        filtered = [row for row in filtered if row.get("date") and row["date"] >= d_from]

    if d_to is not None:
        end_bound = d_to.replace(hour=23, minute=59, second=59, microsecond=999999)
        filtered = [row for row in filtered if row.get("date") and row["date"] <= end_bound]

    if sort == "Date oldest":
        return sorted(filtered, key=lambda row: row.get("date") or datetime.min)
    if sort == "Total high":
        return sorted(filtered, key=lambda row: row.get("total") or 0, reverse=True)
    if sort == "Total low":
        return sorted(filtered, key=lambda row: row.get("total") or 0)
    if sort == "Customer A-Z":
        return sorted(filtered, key=lambda row: str(row.get("cname") or "").lower())
    if sort == "Invoice #":
        return sorted(filtered, key=lambda row: str(row.get("number") or ""))
    return sorted(filtered, key=lambda row: row.get("date") or datetime.min, reverse=True)


# --- i18n System ---
TRANSLATIONS = {
    'en': {
        'dashboard': 'Dashboard', 'invoices': 'Invoices', 'recurring': 'Subscription',
        'customers': 'Customers', 'services': 'Services', 'accounts': 'Accounts',
        'reports': 'Reports', 'expenses': 'Expenses', 'client_expenses': 'Client Expenses', 'settings': 'Settings', 'help': 'Help', 'welcome': 'Welcome back, Consultant',
        'overdue': 'OVERDUE', 'draft': 'DRAFT / PENDING', 'paid': 'PAID (TOTAL)',
        'new_invoice': 'New Invoice', 'add_customer': 'Add Customer', 'add_service': 'Add Service',
        'mark_paid': 'Mark as Paid', 'download_pdf': 'Download PDF', 'preview': 'Preview',
        'export_data': 'Export Data for Accountant', 'all_invoices': 'All Invoices',
        'next_billing': 'Upcoming Billing Tasks', 'recent_activity': 'Recent Activity', 
        'cashflow': 'Cashflow Statistics', 'items': 'Line Items', 'desc': 'Description',
        'qty': 'Qty', 'price': 'Price', 'total': 'Total', 'subtotal': 'Subtotal',
        'tax': 'Taxes (TPS & TVQ)', 'grand_total': 'Grand Total'
    },
    'es': {
        'dashboard': 'Tablero', 'invoices': 'Facturas', 'recurring': 'Suscripciones',
        'customers': 'Clientes', 'services': 'Servicios', 'accounts': 'Cuentas',
        'reports': 'Reportes', 'expenses': 'Gastos', 'client_expenses': 'Gastos de Cliente', 'settings': 'Configuración', 'help': 'Ayuda', 'welcome': 'Bienvenido de nuevo, Consultor',
        'overdue': 'VENCIDO', 'draft': 'BORRADOR / PENDIENTE', 'paid': 'PAGADO (TOTAL)',
        'new_invoice': 'Nueva Factura', 'add_customer': 'Agregar Cliente', 'add_service': 'Agregar Servicio',
        'mark_paid': 'Marcar como Pagado', 'download_pdf': 'Descargar PDF', 'preview': 'Vista Previa',
        'export_data': 'Exportar para Contador', 'all_invoices': 'Todas las Facturas',
        'next_billing': 'Próximas Tareas de Cobro', 'recent_activity': 'Actividad Reciente',
        'cashflow': 'Estadísticas de Flujo', 'items': 'Conceptos', 'desc': 'Descripción',
        'qty': 'Cant', 'price': 'Precio', 'total': 'Total', 'subtotal': 'Subtotal',
        'tax': 'Impuestos (TPS y TVQ)', 'grand_total': 'Total General'
    }
}

def _(key):
    lang = app.storage.user.get('lang', 'en')
    return TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, key)

# --- App Styling ---
def inject_premium_styles():
    # Force dark mode state from storage
    is_dark = app.storage.user.get('dark_mode', False)
    ui.dark_mode().value = is_dark
    
    ui.add_head_html('<link rel="preconnect" href="https://fonts.googleapis.com">')
    ui.add_head_html('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    ui.add_head_html('<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">')
    try:
        if os.path.exists('app/style.css'):
              with open('app/style.css', 'r') as f:
                  ui.add_head_html(f'<style>{f.read()}</style>')
              logger.debug("CSS cargado exitosamente")
        else:
            logger.warning("Archivo style.css no encontrado")
    except Exception as e:
        logger.error(f"Error al cargar CSS: {e}")

# --- Global Components ---
def create_menu(active_path='/'):
    is_dark = app.storage.user.get('dark_mode', False)
    with ui.left_drawer(value=True).classes('p-0'):
        with ui.column().classes('w-full h-full p-6 pt-10 gap-8'):
            with ui.row().classes('items-center gap-3 px-4 mb-4 cursor-pointer').on('click', lambda: ui.navigate.to('/')):
                ui.icon('auto_awesome', color='indigo-600').classes('text-3xl animate-pulse')
                ui.label('Accounting AI').classes('text-2xl font-bold text-slate-900 tracking-tight dark:text-slate-100')
            
            with ui.column().classes('w-full gap-1'):
                pages = [
                    ('/', 'dashboard', 'Dashboard'),
                    ('/invoices', 'receipt', 'Invoices'),
                    ('/recurring', 'autorenew', 'Subscription'),
                    ('/customers', 'group', 'Customers'),
                    ('/services', 'inventory_2', 'Services'),
                    ('/accounts', 'account_balance_wallet', 'Accounts'),
                    ('/expenses', 'payments', 'Expenses'),
                    ('/client-expenses', 'request_quote', 'Client_Expenses'),
                    ('/reports', 'bar_chart', 'Reports'),
                    ('/settings', 'settings', 'Settings'),
                    ('/help', 'help_outline', 'Help'),
                ]
                for path, icon, key in pages:
                    active = active_path == path
                    cls = f'menu-item {"menu-item-active" if active else ""}'
                    with ui.button(on_click=lambda p=path: ui.navigate.to(p)).props('flat no-caps align=left').classes(f'w-full {cls}'):
                        with ui.row().classes('items-center gap-4 w-full'):
                            ui.icon(icon, size='22px').classes('opacity-80')
                            ui.label(_(key.lower())).classes('text-[15px]')

            ui.space()
            
            with ui.column().classes('w-full px-4 gap-4'):
                with ui.row().classes('w-full items-center justify-between px-2 text-slate-500'):
                    ui.icon('translate', size='20px')
                    lang_sel = ui.select({'en': 'EN', 'es': 'ES'}, value=app.storage.user.get('lang', 'en')).props('dense flat borderless color=slate-400')
                    lang_sel.on_value_change(lambda e: (app.storage.user.update({'lang': e.value}), ui.run_javascript('window.location.reload()')))
                
                with ui.row().classes('w-full items-center justify-between px-2 text-slate-500'):
                    ui.icon('dark_mode' if not is_dark else 'light_mode', size='20px')
                    def toggle_dark(e):
                        app.storage.user['dark_mode'] = e.value
                        ui.dark_mode().value = e.value
                    ui.switch(value=is_dark).on_value_change(toggle_dark)

# --- Invoice Preview Tool ---
def open_invoice_preview(inv_id):
    logger.info(f"Abriendo vista previa de factura ID={inv_id}")
    with Session(engine) as s:
        inv = s.get(Invoice, inv_id)
        if not inv:
            logger.error(f"Factura ID={inv_id} no encontrada en la base de datos")
            ui.notify('Factura no encontrada', color='red-500')
            return
        cust = s.get(Customer, inv.customer_id)
        items = s.exec(select(InvoiceItem).where(InvoiceItem.invoice_id == inv_id)).all()
        logger.debug(f"Factura #{inv.number}: {len(items)} items, cliente={cust.name}")
    
    with ui.dialog().classes('p-0 backdrop-blur-sm') as d, ui.column().classes('p-0 bg-transparent'):
        with ui.card().classes('invoice-preview animate-fade-in'):
            with ui.row().classes('invoice-header w-full'):
                with ui.column():
                    ui.label('INVOICE').classes('text-5xl font-black text-indigo-600 mb-2')
                    ui.label(f'#{inv.number}').classes('text-xl text-slate-400 font-medium')
                with ui.column().classes('text-right'):
                    ui.label('Consultant Pro').classes('text-xl font-bold')
                    ui.label('Montréal, QC').classes('text-slate-500')
                    ui.label('contact@consultant.ai').classes('text-slate-500')
            ui.separator().classes('my-10 opacity-50')
            with ui.row().classes('w-full justify-between mb-12'):
                with ui.column():
                    ui.label('BILL TO').classes('text-xs font-bold text-slate-400 tracking-widest mb-1')
                    ui.label(cust.name).classes('text-lg font-bold')
                    ui.label(cust.email).classes('text-slate-500')
                with ui.column().classes('text-right'):
                    ui.label('DATE').classes('text-xs font-bold text-slate-400 tracking-widest mb-1')
                    ui.label(inv.date.strftime('%B %d, %Y')).classes('text-slate-800 font-semibold')
            with ui.column().classes('w-full invoice-line-items'):
                with ui.row().classes('w-full border-b-2 border-slate-900 pb-2 mb-4'):
                    ui.label(_('desc')).classes('flex-grow font-bold text-slate-900')
                    ui.label(_('qty')).classes('w-20 text-center font-bold text-slate-900')
                    ui.label(_('total')).classes('w-32 text-right font-bold text-slate-900')
                for it in items:
                    with ui.row().classes('w-full py-4 border-b border-slate-100'):
                        ui.label(it.description).classes('flex-grow text-slate-700')
                        ui.label(str(it.quantity)).classes('w-20 text-center text-slate-700')
                        ui.label(f'${it.total:,.2f}').classes('w-32 text-right font-semibold')
            with ui.column().classes('invoice-totals gap-2'):
                with ui.row().classes('w-full justify-between'):
                    ui.label(_('subtotal')).classes('text-slate-500'); ui.label(f'${inv.subtotal:,.2f}')
                _prev_tps, _prev_tvq = tax_breakdown(inv.tax_total)
                with ui.row().classes('w-full justify-between'):
                    ui.label('TPS (5%)').classes('text-slate-500'); ui.label(f'${_prev_tps:,.2f}')
                with ui.row().classes('w-full justify-between'):
                    ui.label('TVQ (9.975%)').classes('text-slate-500'); ui.label(f'${_prev_tvq:,.2f}')
                with ui.row().classes('w-full justify-between pt-4 border-t border-slate-200 mt-2'):
                    ui.label(_('grand_total')).classes('text-xl font-black text-indigo-600')
                    ui.label(f'${inv.total:,.2f}').classes('text-xl font-black text-indigo-600')
        with ui.row().classes('w-full justify-center p-6 gap-4'):
            ui.button('Close', on_click=d.close).props('flat text-color=white')
            ui.button('Download PDF', icon='file_download', on_click=lambda: ui.run_javascript(f'window.open("/download/{inv.id}", "_blank")')).classes('btn-primary')
    d.open()

# --- Logic Actions ---
def _update_invoice_status(iid, new_status: str, msg: str, color: str):
    try:
        with Session(engine) as s:
            inv = s.get(Invoice, iid)
            if inv:
                inv.status = new_status; s.add(inv); s.commit()
                logger.info(f"Invoice #{inv.number} → {new_status}")
                ui.notify(msg, color=color); ui.navigate.to('/invoices')
            else:
                ui.notify('Invoice not found', color='red-500')
    except Exception as e:
        logger.exception(f"Error updating invoice ID={iid} to {new_status}")
        ui.notify(f'Error: {e}', color='red-500')

def mark_invoice_as_sent_action(iid):
    _update_invoice_status(iid, 'Sent', 'Invoice marked as Sent.', 'indigo-500')

def mark_invoice_as_paid_action(iid):
    try:
        with Session(engine) as s:
            inv = s.get(Invoice, iid)
            if not inv:
                ui.notify('Invoice not found', color='red-500')
                return
            if not can_mark_invoice_paid(invoice_display_status(inv)):
                ui.notify('Only sent or overdue invoices can be marked paid.', color='amber-500')
                return
    except Exception as e:
        logger.exception(f"Error validating invoice payment for ID={iid}")
        ui.notify(f'Error: {e}', color='red-500')
        return
    _update_invoice_status(iid, 'Paid', 'Payment registered!', 'emerald-500')


def mark_invoice_as_written_off_action(iid):
    try:
        with Session(engine) as s:
            inv = s.get(Invoice, iid)
            if not inv:
                ui.notify('Invoice not found', color='red-500')
                return
            if not can_write_off_invoice(invoice_display_status(inv)):
                ui.notify('Only sent or overdue invoices can be written off.', color='amber-500')
                return
    except Exception as e:
        logger.exception(f"Error validating invoice write-off for ID={iid}")
        ui.notify(f'Error: {e}', color='red-500')
        return
    _update_invoice_status(iid, 'Written Off', 'Invoice written off.', 'amber-600')

def mark_invoice_as_cancelled_action(iid):
    try:
        with Session(engine) as s:
            inv = s.get(Invoice, iid)
            if not inv:
                ui.notify('Invoice not found', color='red-500')
                return
            if not can_cancel_invoice(inv.status):
                ui.notify('Only draft invoices can be cancelled.', color='amber-500')
                return
    except Exception as e:
        logger.exception(f"Error validating invoice cancellation for ID={iid}")
        ui.notify(f'Error: {e}', color='red-500')
        return
    _update_invoice_status(iid, 'Cancelled', 'Invoice cancelled.', 'red-500')

# --- Pages ---
@ui.page('/invoices')
def invoices_page():
    logger.debug("Cargando página: /invoices")
    inject_premium_styles(); create_menu('/invoices')
    today = datetime.today()
    with Session(engine) as session:
        customers = session.exec(select(Customer)).all(); services = session.exec(select(Service)).all(); invoices = session.exec(select(Invoice)).all()
    
    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        with ui.row().classes('w-full justify-between items-end mb-10'):
            with ui.column():
                ui.label(_('invoices')).classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight')
                ui.label(_('all_invoices')).classes('text-slate-500 text-lg')
            
            with ui.dialog() as dialog, ui.card().classes('p-10 w-[950px] premium-card h-auto'):
                ui.label(_('new_invoice')).classes('text-3xl font-extrabold mb-10 text-slate-900 dark:text-slate-100')
                with ui.row().classes('w-full gap-8 mb-10'):
                    c_sel = ui.select({c.id: c.name for c in customers}, label=_('customers')).classes('flex-1').props('outlined rounded')
                    i_date = ui.input('Invoice Date', value=datetime.today().strftime('%Y-%m-%d')).classes('w-48').props('outlined rounded append-icon=calendar_today')
                line_items = []
                it_cont = ui.column().classes('w-full gap-3 mb-8')
                # Placeholders for totals labels
                totals_labels = {}
                def update_totals():
                    items = [((i['q'].value or 0) * (i['p'].value or 0), True) for i in line_items if i['s'].value]
                    sub, tax, tot = compute_invoice_totals(items)
                    if 'sub' in totals_labels: totals_labels['sub'].text = f'${sub:,.2f}'
                    if 'tax' in totals_labels: totals_labels['tax'].text = f'${tax:,.2f}'
                    if 'tot' in totals_labels: totals_labels['tot'].text = f'${tot:,.2f}'

                def add_row():
                    with it_cont:
                        with ui.row().classes('w-full items-center gap-4 p-5 bg-slate-50 rounded-2xl border border-slate-100 dark:bg-slate-800 dark:border-slate-700'):
                            s_sel = ui.select({s.id: s.name for s in services}, label=_('services')).classes('flex-grow').props('flat borderless')
                            iqty = ui.number('Qty', value=1.0).classes('w-24').props('borderless'); iprc = ui.number('Price').classes('w-32').props('borderless prefix=$')
                            def s_ch(e):
                                p = next((s.unit_price for s in services if s.id == e.value), 0.0)
                                iprc.set_value(p); update_totals()
                            s_sel.on_value_change(s_ch); iqty.on_value_change(update_totals); iprc.on_value_change(update_totals)
                            line_items.append({'s': s_sel, 'q': iqty, 'p': iprc})
                add_row()
                ui.button('Add Line Item', icon='add', on_click=add_row).props('flat no-caps text-color=indigo-600').classes('mt-2 h-12 rounded-xl')
                with ui.row().classes('w-full justify-end mt-12 py-8 border-t border-slate-100 dark:border-slate-800'):
                    with ui.column().classes('w-80 gap-3 text-right'):
                        with ui.row().classes('w-full justify-between'): 
                            ui.label(_('subtotal')).classes('text-slate-500 font-medium')
                            totals_labels['sub'] = ui.label('$0.00').classes('text-2xl font-bold')
                        with ui.row().classes('w-full justify-between'): 
                            ui.label(_('tax')).classes('text-slate-500 font-medium')
                            totals_labels['tax'] = ui.label('$0.00').classes('text-slate-500')
                        with ui.row().classes('w-full justify-between pt-4 mt-2 border-t-2 border-slate-900 dark:border-slate-200'): 
                            ui.label(_('total')).classes('text-xl font-bold')
                            totals_labels['tot'] = ui.label('$0.00').classes('text-3xl font-black text-indigo-600')
                        update_totals() # Initialize

                def save():
                    if not c_sel.value: return ui.notify('Pick a client!', color='red-500')
                    try:
                        with Session(engine) as s:
                            items = [(i['q'].value * i['p'].value, True) for i in line_items if i['s'].value]
                            sub, tax, tot = compute_invoice_totals(items)
                            existing_invoices = s.exec(select(Invoice)).all()
                            inv = Invoice(number=next_invoice_number(existing_invoices), customer_id=c_sel.value, date=datetime.strptime(i_date.value, '%Y-%m-%d'), subtotal=sub, tax_total=tax, total=tot, status='Draft')
                            s.add(inv); s.commit(); s.refresh(inv)
                            for i in line_items:
                                if i['s'].value:
                                    service = next(ser for ser in services if ser.id == i['s'].value)
                                    s.add(InvoiceItem(invoice_id=inv.id, service_id=i['s'].value, description=invoice_item_description(service), quantity=i['q'].value, unit_price=i['p'].value, total=i['q'].value*i['p'].value))
                            s.commit()
                            logger.info(f"Nueva factura creada: #{inv.number}, total=${inv.total:,.2f}, cliente_id={inv.customer_id}")
                            ui.notify('Invoice Saved!'); dialog.close(); ui.navigate.to('/invoices')
                    except Exception as e:
                        logger.exception("Error al guardar nueva factura")
                        ui.notify(f'Error al guardar: {e}', color='red-500')

                with ui.row().classes('w-full justify-end gap-4 mt-8'):
                    ui.button('Discard', on_click=dialog.close).props('flat no-caps').classes('text-slate-400')
                    ui.button('Save Invoice', on_click=save).classes('btn-primary px-10 h-14 rounded-2xl')
            ui.button(_('new_invoice'), icon='add_circle', on_click=dialog.open).classes('btn-primary px-8 h-14 rounded-2xl shadow-xl')

        filter_state = {
            "query": "",
            "status": "All",
            "customer_id": "All",
            "period": "All Time",
            "from": None,
            "to": None,
            "sort": "Date newest",
        }
        all_invoice_rows = [build_invoice_list_row(i, customers, today=today) for i in invoices]
        customer_options = {"All": "All customers", **{c.id: c.name for c in customers}}

        def parse_custom_invoice_dates():
            try:
                d_from = datetime.strptime(from_input.value, '%Y-%m-%d')
                d_to = datetime.strptime(to_input.value, '%Y-%m-%d')
            except (TypeError, ValueError):
                ui.notify('Invalid date format. Use YYYY-MM-DD', color='red-500')
                return None
            if d_to < d_from:
                ui.notify('End date must be on or after start date', color='red-500')
                return None
            return d_from, d_to

        def refresh_invoice_table():
            table_container.clear()
            rows = filter_and_sort_invoice_rows(all_invoice_rows, filter_state)
            with table_container:
                if not rows:
                    with ui.card().classes('w-full p-10 premium-card items-center justify-center'):
                        ui.icon('search_off', size='40px', color='slate-300')
                        ui.label('No invoices match these filters').classes('text-slate-400 text-sm mt-2')
                    return

                with ui.card().classes('w-full p-0 overflow-hidden premium-card'):
                    cols = invoice_list_columns(_('customers'))
                    table = ui.table(columns=cols, rows=rows, row_key='id').classes('w-full border-none shadow-none')
                    table.add_slot('body-cell-status', '''<q-td :props="props"><q-badge :color="props.row.status === 'Paid' ? 'emerald-500' : (props.row.status === 'Sent' ? 'indigo-500' : (props.row.status === 'Overdue' ? 'orange-500' : (props.row.status === 'Written Off' ? 'slate-500' : (props.row.status === 'Cancelled' ? 'red-500' : 'amber-500'))))" :style="{padding:'8px 16px',borderRadius:'100px',fontWeight:'700',fontSize:'10px'}">{{ props.row.status }}</q-badge></q-td>''')
                    table.add_slot('body-cell-actions', '''<q-td :props="props"><q-btn flat round icon="visibility" title="Preview" @click="$parent.$emit('preview', props.row.id)" /><q-btn flat round color="indigo-600" icon="file_download" title="Download PDF" @click="$parent.$emit('download', props.row.id)" /><q-btn v-if="props.row.can_send" flat round color="indigo-400" icon="send" title="Mark as Sent" @click="$parent.$emit('sent', props.row.id)" /><q-btn v-if="props.row.can_mark_paid" flat round color="emerald-500" icon="check" title="Mark as Paid" @click="$parent.$emit('paid', props.row.id)" /><q-btn v-if="props.row.can_write_off" flat round color="amber-600" icon="money_off" title="Write off invoice" @click="$parent.$emit('writeoff', props.row.id)" /><q-btn v-if="props.row.can_cancel" flat round color="red-300" icon="cancel" title="Cancel draft invoice" @click="$parent.$emit('cancel', props.row.id)" /></q-td>''')
                    table.on('preview', lambda e: open_invoice_preview(e.args)); table.on('sent', lambda e: mark_invoice_as_sent_action(e.args)); table.on('paid', lambda e: mark_invoice_as_paid_action(e.args)); table.on('cancel', lambda e: mark_invoice_as_cancelled_action(e.args)); table.on('writeoff', lambda e: mark_invoice_as_written_off_action(e.args)); table.on('download', lambda e: ui.run_javascript(f'window.open("/download/{e.args}", "_blank")'))

        def update_invoice_filter(key, value):
            filter_state[key] = value
            refresh_invoice_table()

        def apply_invoice_period(period):
            filter_state['period'] = period
            custom_date_row.set_visibility(period == 'Custom')
            if period == 'Custom':
                return
            filter_state['from'], filter_state['to'] = invoice_filter_period_bounds(period, today)
            refresh_invoice_table()

        def apply_custom_invoice_dates():
            dates = parse_custom_invoice_dates()
            if dates is None:
                return
            filter_state['period'] = 'Custom'
            filter_state['from'], filter_state['to'] = dates
            refresh_invoice_table()

        def clear_invoice_filters():
            filter_state.update({
                "query": "",
                "status": "All",
                "customer_id": "All",
                "period": "All Time",
                "from": None,
                "to": None,
                "sort": "Date newest",
            })
            query_input.set_value('')
            status_select.set_value('All')
            customer_select.set_value('All')
            period_select.set_value('All Time')
            sort_select.set_value('Date newest')
            from_input.set_value(today.strftime('%Y-%m-%d'))
            to_input.set_value(today.strftime('%Y-%m-%d'))
            custom_date_row.set_visibility(False)
            refresh_invoice_table()

        with ui.card().classes('w-full p-4 premium-card mb-4'):
            with ui.row().classes('w-full items-center gap-3 flex-wrap'):
                query_input = ui.input('Search invoices or customers').props('dense outlined clearable').classes('flex-1 min-w-64')
                status_select = ui.select(INVOICE_STATUS_FILTERS, value='All', label='Status').props('dense outlined').classes('w-40')
                customer_select = ui.select(customer_options, value='All', label='Customer').props('dense outlined').classes('w-56')
                period_select = ui.select(INVOICE_PERIOD_FILTERS, value='All Time', label='Period').props('dense outlined').classes('w-40')
                sort_select = ui.select(INVOICE_SORT_OPTIONS, value='Date newest', label='Sort').props('dense outlined').classes('w-44')
                ui.button('Clear', icon='restart_alt', on_click=clear_invoice_filters).props('flat no-caps').classes('h-10 rounded-lg px-4 text-slate-500')
            with ui.row().classes('w-full items-center gap-3 flex-wrap mt-3') as custom_date_row:
                from_input = ui.input('From', value=today.strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                to_input = ui.input('To', value=today.strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                ui.button('Apply', icon='check', on_click=apply_custom_invoice_dates).classes('btn-primary h-10 rounded-lg px-5')
            custom_date_row.set_visibility(False)

        table_container = ui.column().classes('w-full')
        query_input.on_value_change(lambda e: update_invoice_filter('query', e.value or ''))
        status_select.on_value_change(lambda e: update_invoice_filter('status', e.value or 'All'))
        customer_select.on_value_change(lambda e: update_invoice_filter('customer_id', e.value or 'All'))
        period_select.on_value_change(lambda e: apply_invoice_period(e.value or 'All Time'))
        sort_select.on_value_change(lambda e: update_invoice_filter('sort', e.value or 'Date newest'))
        refresh_invoice_table()

@ui.page('/')
def dashboard_page():
    logger.debug("Cargando página: / (dashboard)")
    inject_premium_styles(); create_menu('/')

    with Session(engine) as s:
        invs = s.exec(select(Invoice).order_by(Invoice.date.desc())).all()
        customers = s.exec(select(Customer)).all()

    cust_map = {c.id: c.name for c in customers}

    paid   = [i for i in invs if i.status == 'Paid']
    sent   = [i for i in invs if i.status == 'Sent']
    drafts = [i for i in invs if i.status == 'Draft']

    def stat_card(label, icon, color, border, amount, count):
        with ui.card().classes(f'flex-1 p-8 premium-card {border}'):
            with ui.row().classes('items-center gap-3 mb-4'):
                ui.icon(icon, color=color, size='28px')
                ui.label(label).classes('text-[10px] font-black text-slate-400 uppercase tracking-widest')
            ui.label(f'${amount:,.2f}').classes('text-4xl font-black text-slate-900 dark:text-slate-100')
            ui.label(f'{count} invoice{"s" if count != 1 else ""}').classes('text-xs text-slate-400 mt-1')

    # Build monthly revenue chart (paid invoices, last 12 months)
    monthly = defaultdict(float)
    for i in paid:
        key = i.date.strftime('%b %Y')
        monthly[key] += i.total
    # Sort chronologically
    from datetime import date
    months_sorted = sorted(monthly.keys(), key=lambda m: datetime.strptime(m, '%b %Y'))[-12:]
    chart_labels = months_sorted
    chart_values = [monthly[m] for m in months_sorted]

    fig = go.Figure(go.Bar(
        x=chart_labels,
        y=chart_values,
        marker_color='#3b82f6',
        marker_line_width=0,
    ))
    fig.update_layout(
        margin=dict(l=16, r=16, t=16, b=16),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color='#94a3b8')),
        yaxis=dict(showgrid=True, gridcolor='#f1f5f9', tickprefix='$', tickfont=dict(size=10, color='#94a3b8')),
        font=dict(family='Inter, system-ui, sans-serif'),
        showlegend=False,
    )

    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        with ui.row().classes('w-full justify-between items-end mb-10'):
            with ui.column():
                ui.label(_('welcome')).classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100')
                ui.label('Real-time overview of your consulting business').classes('text-slate-400 text-base mt-1')
            ui.button('New Invoice', icon='add_circle', on_click=lambda: ui.navigate.to('/invoices')).classes('btn-primary h-12 rounded-xl px-6')

        # ── Stat cards ──
        with ui.row().classes('w-full gap-6 mb-10'):
            stat_card('Paid', 'auto_awesome', 'emerald-500', 'stat-paid', sum(i.total for i in paid), len(paid))
            stat_card('Awaiting Payment', 'send', 'indigo-500', 'stat-overdue', sum(i.total for i in sent), len(sent))
            stat_card('Draft', 'history_toggle_off', 'amber-500', 'stat-pending', sum(i.total for i in drafts), len(drafts))
            with ui.card().classes('flex-1 p-8 premium-card'):
                with ui.row().classes('items-center gap-3 mb-4'):
                    ui.icon('people', color='slate-400', size='28px')
                    ui.label('Clients').classes('text-[10px] font-black text-slate-400 uppercase tracking-widest')
                ui.label(str(len(customers))).classes('text-4xl font-black text-slate-900 dark:text-slate-100')
                ui.label('active clients').classes('text-xs text-slate-400 mt-1')

        # ── Chart + Recent invoices ──
        with ui.row().classes('w-full gap-6'):
            with ui.column().classes('flex-1 gap-4'):
                ui.label('Monthly Revenue').classes('text-xl font-bold text-slate-800 dark:text-slate-200')
                with ui.card().classes('w-full p-4 premium-card'):
                    if chart_values:
                        ui.plotly(fig).classes('w-full h-64')
                    else:
                        with ui.column().classes('w-full h-64 items-center justify-center'):
                            ui.icon('bar_chart', size='48px', color='indigo-200')
                            ui.label('No paid invoices yet').classes('text-slate-400 text-sm mt-2')

            with ui.column().classes('flex-[1.4] gap-4'):
                ui.label('Recent Invoices').classes('text-xl font-bold text-slate-800 dark:text-slate-200')
                with ui.card().classes('w-full p-0 premium-card overflow-hidden'):
                    cols = [
                        {'name': 'num',    'label': '#',       'field': 'number',  'align': 'left'},
                        {'name': 'cust',   'label': 'Client',  'field': 'cname',   'align': 'left'},
                        {'name': 'date',   'label': 'Date',    'field': 'date_fmt','align': 'left'},
                        {'name': 'status', 'label': 'Status',  'field': 'status',  'align': 'center'},
                        {'name': 'total',  'label': 'Total',   'field': 'total_fmt','align': 'right'},
                    ]
                    rows = [
                        {
                            **i.model_dump(),
                            'cname':     cust_map.get(i.customer_id, '?'),
                            'date_fmt':  i.date.strftime('%Y-%m-%d'),
                            'total_fmt': f'${i.total:,.2f}',
                        }
                        for i in invs[:10]
                    ]
                    t = ui.table(columns=cols, rows=rows, row_key='id').classes('w-full border-none shadow-none')
                    t.add_slot('body-cell-status', '''<q-td :props="props"><q-badge :color="props.row.status === 'Paid' ? 'emerald-500' : (props.row.status === 'Sent' ? 'indigo-500' : (props.row.status === 'Cancelled' ? 'red-500' : 'amber-500'))" :style="{padding:'4px 12px',borderRadius:'999px',fontWeight:'700',fontSize:'10px'}">{{ props.row.status }}</q-badge></q-td>''')

@ui.page('/expenses')
def expenses_page():
    inject_premium_styles(); create_menu('/expenses')

    TPS_RATE = 0.05
    TVQ_RATE = 0.09975

    today = datetime.today()
    first_this_month = today.replace(day=1)
    first_this_year  = today.replace(month=1, day=1)

    PRESETS = {
        'This Month': (first_this_month, today),
        'This Year':  (first_this_year,  today),
        'All Time':   (datetime(2000, 1, 1), today),
    }

    with Session(engine) as s:
        expense_accounts = s.exec(
            select(Account).where(Account.type == AccountType.EXPENSE, Account.is_active == True)
            .order_by(Account.code)
        ).all()

    account_options = {acc.id: f"{acc.code} — {acc.name}" for acc in expense_accounts}

    form = {
        'date': today.strftime('%Y-%m-%d'),
        'description': '',
        'amount': 0.0,
        'apply_tps': False,
        'apply_tvq': False,
        'account_id': expense_accounts[0].id if expense_accounts else None,
        'notes': '',
    }

    def compute_total(amount, apply_tps, apply_tvq):
        return compute_tax_split(amount, apply_tps, apply_tvq)

    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        ui.label('Expenses').classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-2')
        ui.label('Track business expenses linked to your chart of accounts').classes('text-slate-400 text-base mb-8')

        # ── Add Expense Form ──
        with ui.card().classes('w-full p-6 premium-card mb-6'):
            ui.label('Add Expense').classes('text-sm font-black text-slate-400 uppercase tracking-widest mb-4')

            with ui.row().classes('w-full gap-4 flex-wrap'):
                date_input = ui.input('Date', value=form['date']).props('dense outlined').classes('w-40')
                desc_input = ui.input('Description').props('dense outlined').classes('flex-1 min-w-48')
                acct_select = ui.select(account_options, value=form['account_id'], label='Account').props('dense outlined').classes('w-72')

            with ui.row().classes('w-full items-center gap-4 mt-3 flex-wrap'):
                amount_input = ui.number('Amount (pre-tax)', value=0.0, format='%.2f').props('dense outlined prefix=$').classes('w-44')
                tps_check = ui.checkbox('TPS (5%)', value=False)
                tvq_check = ui.checkbox('TVQ (9.975%)', value=False)
                total_label = ui.label('Total: $0.00').classes('text-lg font-bold text-indigo-600 ml-4')

            def update_total():
                tps, tvq, total = compute_total(amount_input.value or 0, tps_check.value, tvq_check.value)
                total_label.set_text(f'Total: ${total:,.2f}')

            amount_input.on_value_change(lambda _: update_total())
            tps_check.on_value_change(lambda _: update_total())
            tvq_check.on_value_change(lambda _: update_total())

            with ui.row().classes('w-full gap-4 mt-3'):
                notes_input = ui.input('Notes (optional)').props('dense outlined').classes('flex-1')

                def save_expense():
                    if not desc_input.value.strip():
                        ui.notify('Description is required', color='red-500'); return
                    if not acct_select.value:
                        ui.notify('Select an account', color='red-500'); return
                    try:
                        exp_date = datetime.strptime(date_input.value, '%Y-%m-%d')
                    except ValueError:
                        ui.notify('Invalid date format. Use YYYY-MM-DD', color='red-500'); return

                    amt = float(amount_input.value or 0)
                    if amt <= 0:
                        ui.notify('Amount must be greater than zero', color='red-500'); return
                    tps, tvq, total = compute_total(amt, tps_check.value, tvq_check.value)

                    with Session(engine) as s:
                        exp = Expense(
                            date=exp_date,
                            description=desc_input.value.strip(),
                            amount=amt,
                            tps=tps,
                            tvq=tvq,
                            total=total,
                            account_id=acct_select.value,
                            notes=notes_input.value.strip() or None,
                        )
                        s.add(exp); s.commit()

                    ui.notify('Expense saved!', color='emerald-500')
                    date_input.value = today.strftime('%Y-%m-%d')
                    desc_input.value = ''
                    amount_input.value = 0.0
                    tps_check.value = False
                    tvq_check.value = False
                    notes_input.value = ''
                    update_total()
                    refresh_table()

                ui.button('Add Expense', icon='add', on_click=save_expense).classes('btn-primary h-10 px-6')

        # ── Period Filter ──
        filter_state = {'from': first_this_month, 'to': today}
        preset_btns = {}

        def set_expense_preset(name):
            for n, btn in preset_btns.items():
                btn.classes(replace='btn-primary h-9 rounded-lg px-4 text-sm' if n == name
                            else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300')
            d_from, d_to = PRESETS[name]
            filter_state['from'] = d_from
            filter_state['to'] = d_to
            refresh_table()

        def export_expenses_csv():
            d_from = filter_state['from']
            d_to   = filter_state['to'].replace(hour=23, minute=59, second=59)
            with Session(engine) as s:
                expenses = s.exec(
                    select(Expense).where(Expense.date >= d_from, Expense.date <= d_to)
                    .order_by(Expense.date.desc())
                ).all()
                acct_map = {a.id: f"{a.code} — {a.name}" for a in s.exec(select(Account).where(Account.type == AccountType.EXPENSE)).all()}
            if not expenses:
                ui.notify('No expenses to export in this period', color='amber-500'); return
            path = 'data/expenses_export.csv'
            with open(path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Date', 'Description', 'Account', 'Subtotal', 'TPS', 'TVQ', 'Total', 'Notes'])
                for exp in expenses:
                    writer.writerow([
                        exp.date.strftime('%Y-%m-%d'),
                        exp.description,
                        acct_map.get(exp.account_id, '?'),
                        f'{exp.amount:.2f}',
                        f'{exp.tps:.2f}',
                        f'{exp.tvq:.2f}',
                        f'{exp.total:.2f}',
                        exp.notes or '',
                    ])
            ui.download(path)
            ui.notify(f'Exported {len(expenses)} expenses to CSV', color='emerald-500')

        with ui.card().classes('w-full p-4 premium-card mb-4'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
                with ui.row().classes('items-center gap-3 flex-wrap'):
                    ui.label('Period:').classes('text-sm font-semibold text-slate-500 mr-2')
                    for name in PRESETS:
                        is_active = name == 'This Month'
                        cls = 'btn-primary h-9 rounded-lg px-4 text-sm' if is_active else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                        btn = ui.button(name, on_click=lambda n=name: set_expense_preset(n)).classes(cls)
                        preset_btns[name] = btn
                ui.button('Export CSV', icon='download', on_click=export_expenses_csv).props('flat').classes('h-9 rounded-lg px-4 text-sm text-emerald-600')

        # ── Expenses Table ──
        table_container = ui.column().classes('w-full')

        def refresh_table():
            table_container.clear()
            d_from = filter_state['from']
            d_to   = filter_state['to'].replace(hour=23, minute=59, second=59)
            with Session(engine) as s:
                expenses = s.exec(
                    select(Expense).where(Expense.date >= d_from, Expense.date <= d_to)
                    .order_by(Expense.date.desc())
                ).all()
                fresh_accounts = s.exec(select(Account).where(Account.type == AccountType.EXPENSE)).all()
            acc_name_map = {acc.id: f"{acc.code} — {acc.name}" for acc in fresh_accounts}

            with table_container:
                if not expenses:
                    with ui.card().classes('w-full p-10 premium-card items-center justify-center'):
                        ui.icon('receipt_long', size='40px', color='slate-300')
                        ui.label('No expenses in this period').classes('text-slate-400 text-sm mt-2')
                    return

                cols = [
                    {'name': 'date',    'label': 'Date',        'field': 'date_fmt',   'align': 'left'},
                    {'name': 'desc',    'label': 'Description', 'field': 'description','align': 'left'},
                    {'name': 'account', 'label': 'Account',     'field': 'acct_name',  'align': 'left'},
                    {'name': 'amount',  'label': 'Subtotal',    'field': 'amount_fmt', 'align': 'right'},
                    {'name': 'tps',     'label': 'TPS',         'field': 'tps_fmt',    'align': 'right'},
                    {'name': 'tvq',     'label': 'TVQ',         'field': 'tvq_fmt',    'align': 'right'},
                    {'name': 'total',   'label': 'Total',       'field': 'total_fmt',  'align': 'right'},
                ]
                rows = [{
                    **exp.model_dump(),
                    'date_fmt':   exp.date.strftime('%Y-%m-%d'),
                    'acct_name':  acc_name_map.get(exp.account_id, '?'),
                    'amount_fmt': f'${exp.amount:,.2f}',
                    'tps_fmt':    f'${exp.tps:,.2f}',
                    'tvq_fmt':    f'${exp.tvq:,.2f}',
                    'total_fmt':  f'${exp.total:,.2f}',
                } for exp in expenses]

                with ui.card().classes('w-full p-0 premium-card overflow-hidden'):
                    tbl = ui.table(columns=cols, rows=rows, row_key='id').classes('w-full border-none shadow-none')
                    tbl.add_slot('body-cell-total', '''<q-td :props="props"><span class="font-bold text-indigo-600">{{ props.row.total_fmt }}</span></q-td>''')

                # Summary row
                tot_amount = sum(e.amount for e in expenses)
                tot_tps    = sum(e.tps    for e in expenses)
                tot_tvq    = sum(e.tvq    for e in expenses)
                tot_total  = sum(e.total  for e in expenses)
                with ui.card().classes('w-full px-6 py-4 premium-card mt-2'):
                    with ui.row().classes('w-full justify-end gap-8 items-center'):
                        for label, val in [('Subtotal', tot_amount), ('TPS', tot_tps), ('TVQ', tot_tvq)]:
                            with ui.column().classes('items-end'):
                                ui.label(label).classes('text-[10px] font-black text-slate-400 uppercase tracking-widest')
                                ui.label(f'${val:,.2f}').classes('text-sm font-semibold text-slate-600')
                        with ui.column().classes('items-end'):
                            ui.label('Grand Total').classes('text-[10px] font-black text-slate-400 uppercase tracking-widest')
                            ui.label(f'${tot_total:,.2f}').classes('text-xl font-black text-indigo-600')

        refresh_table()

CLIENT_EXPENSE_STATUS_COLORS = {
    'pending': 'amber-500', 'claimed': 'indigo-500', 'waiting': 'orange-500',
    'disputed': 'red-500', 'reimbursed': 'emerald-500', 'written_off': 'slate-500',
}

CLIENT_EXPENSE_STATUS_LABELS = {
    'pending': 'Pending', 'claimed': 'Claimed', 'waiting': 'Waiting',
    'disputed': 'Disputed', 'reimbursed': 'Reimbursed', 'written_off': 'Written off',
}


def render_client_expense_workflow(framed=True):
    """Horizontal reference strip of the client-expense reimbursement workflow.

    Rendered wherever expense statuses are shown so the user can see, at a
    glance, every state an expense can be in and how it moves between them.
    Terminal states (no valid next state) are marked with a lock icon.
    """
    def _badge(status):
        b = ui.badge(CLIENT_EXPENSE_STATUS_LABELS.get(status, status)).props(
            f'color={CLIENT_EXPENSE_STATUS_COLORS.get(status, "slate-500")}'
        ).style('padding:5px 12px;border-radius:100px;font-weight:700;font-size:10px')
        if not client_expense_next_states(status):  # terminal
            with b:
                ui.icon('lock', size='11px').classes('ml-1 opacity-80')

    def _arrow():
        ui.icon('arrow_forward', size='16px').classes('text-slate-300')

    def _body():
        ui.label('Expense workflow').classes(
            'text-xs font-black text-slate-400 uppercase tracking-widest mb-3')
        # Happy path: pending → claimed → waiting → reimbursed
        with ui.row().classes('items-center gap-2 flex-wrap'):
            _badge('pending'); _arrow()
            _badge('claimed'); _arrow()
            _badge('waiting'); _arrow()
            _badge('reimbursed')
        # Dispute branch: waiting → disputed → reimbursed / written_off
        with ui.row().classes('items-center gap-2 flex-wrap mt-2'):
            ui.label('If disputed:').classes('text-xs text-slate-400 mr-1')
            _badge('waiting'); _arrow()
            _badge('disputed'); _arrow()
            _badge('reimbursed')
            ui.label('or').classes('text-xs text-slate-400')
            _badge('written_off')
        ui.label('Locked states are terminal — no further changes.').classes(
            'text-[11px] text-slate-400 mt-3')

    if framed:
        with ui.card().classes('w-full p-4 premium-card mt-4'):
            _body()
    else:
        with ui.column().classes('w-full gap-0 mb-6'):
            _body()


def _client_expense_last_change(session, expense):
    """Most recent status-change timestamp, falling back to created_at."""
    last = session.exec(
        select(ClientExpenseEvent.changed_at)
        .where(ClientExpenseEvent.client_expense_id == expense.id)
        .order_by(ClientExpenseEvent.changed_at.desc())
    ).first()
    return last or expense.created_at


@ui.page('/client-expenses')
def client_expenses_page():
    inject_premium_styles(); create_menu('/client-expenses')
    today = datetime.today()
    os.makedirs('data/receipts', exist_ok=True)

    with Session(engine) as s:
        customers = s.exec(select(Customer)).all()
        conf = s.exec(select(CompanySettings)).first()
    customer_options = {c.id: c.name for c in customers}
    ollama_url = conf.ollama_url if conf else None
    ollama_model = conf.ollama_model if conf else None
    ai_ready = ollama_is_ready(ollama_url, ollama_model)

    pending_receipt = {'name': None, 'content': None}

    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        ui.label(_('client_expenses')).classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-2')
        ui.label('Track purchases made on behalf of clients and their reimbursement').classes('text-slate-400 text-base mb-8')

        if not customer_options:
            with ui.card().classes('w-full p-10 premium-card items-center justify-center'):
                ui.icon('group_off', size='40px', color='slate-300')
                ui.label('Add a customer first to record client expenses').classes('text-slate-400 text-sm mt-2')
            return

        # ── Add form ──
        with ui.expansion('Add Client Expense', value=False, icon='add').classes('w-full p-6 premium-card mb-6'):
            with ui.row().classes('w-full gap-4 flex-wrap'):
                cust_select = ui.select(customer_options, value=next(iter(customer_options)), label='Customer').props('dense outlined').classes('w-56')
                date_input = ui.input('Date', value=today.strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                desc_input = ui.input('Description').props('dense outlined').classes('flex-1 min-w-48')
            with ui.row().classes('w-full items-center gap-4 mt-3 flex-wrap'):
                amount_input = ui.number('Amount (pre-tax)', value=0.0, format='%.2f').props('dense outlined prefix=$').classes('w-44')
                tps_check = ui.checkbox('TPS (5%)', value=False)
                tvq_check = ui.checkbox('TVQ (9.975%)', value=False)
                total_label = ui.label('Total: $0.00').classes('text-lg font-bold text-indigo-600 ml-4')

            def update_total():
                _, _, total = compute_tax_split(amount_input.value or 0, tps_check.value, tvq_check.value)
                total_label.set_text(f'Total: ${total:,.2f}')
            amount_input.on_value_change(lambda _: update_total())
            tps_check.on_value_change(lambda _: update_total())
            tvq_check.on_value_change(lambda _: update_total())

            with ui.row().classes('w-full items-center gap-4 mt-3 flex-wrap'):
                recurring_check = ui.checkbox('Recurring monthly', value=False)
                day_input = ui.number('Day of month', value=today.day, min=1, max=31).props('dense outlined').classes('w-36')
                day_input.bind_visibility_from(recurring_check, 'value')
                notes_input = ui.input('Notes (optional)').props('dense outlined').classes('flex-1 min-w-48')

            def save_expense():
                if not desc_input.value.strip():
                    ui.notify('Description is required', color='red-500'); return
                try:
                    exp_date = datetime.strptime(date_input.value, '%Y-%m-%d')
                except ValueError:
                    ui.notify('Invalid date format. Use YYYY-MM-DD', color='red-500'); return
                amt = float(amount_input.value or 0)
                if amt <= 0:
                    ui.notify('Amount must be greater than zero', color='red-500'); return
                tps, tvq, total = compute_tax_split(amt, tps_check.value, tvq_check.value)
                day = int(day_input.value or exp_date.day) if recurring_check.value else None
                with Session(engine) as s:
                    exp = ClientExpense(
                        customer_id=cust_select.value, description=desc_input.value.strip(),
                        date=exp_date, amount=amt, tps=tps, tvq=tvq, total=total,
                        status='pending', is_recurring=recurring_check.value,
                        recurrence_day=day,
                        next_due_date=advance_recurrence_date(exp_date, day) if recurring_check.value else None,
                        notes=notes_input.value.strip() or None,
                    )
                    s.add(exp); s.commit(); s.refresh(exp)
                    s.add(ClientExpenseEvent(client_expense_id=exp.id, status='pending'))
                    if pending_receipt['content']:
                        fname = f"{exp.id}_{sanitize_receipt_filename(pending_receipt['name'])}"
                        path = os.path.join('data/receipts', fname)
                        with open(path, 'wb') as f:
                            f.write(pending_receipt['content'])
                        exp.receipt_path = path
                        s.add(exp)
                    s.commit()
                pending_receipt['name'] = None; pending_receipt['content'] = None
                ui.notify('Client expense saved!', color='emerald-500')
                desc_input.value = ''; amount_input.value = 0.0
                tps_check.value = False; tvq_check.value = False
                recurring_check.value = False; notes_input.value = ''
                update_total(); refresh_table()

            # ── Receipt upload (single control; auto-fills with AI when configured) ──
            def _do_extract(content, name):
                image_bytes = normalize_to_image(content, name)
                b64 = base64.b64encode(image_bytes).decode('ascii')
                return extract_receipt(ollama_url, ollama_model, b64)

            async def on_receipt_upload(e):
                try:
                    name, content = await read_upload_file(e.file)
                    logger.info(f"[receipt] upload received: name={name} ai_ready={ai_ready}")
                    pending_receipt['name'] = name
                    pending_receipt['content'] = content
                    if not ai_ready:
                        ui.notify(f'Receipt "{name}" attached', color='indigo-500')
                        return
                    progress = ui.notification('Reading receipt with AI…', spinner=True, timeout=None)
                    try:
                        data = await run.io_bound(_do_extract, content, name)
                    except Exception as ex:
                        logger.warning(f"[receipt] extraction failed: {ex!r}")
                        progress.dismiss()
                        ui.notify(f'Receipt "{name}" attached, but AI could not read it — '
                                  'please fill the form manually.', color='amber-500')
                        return
                    logger.info(f"[receipt] extract OK: amount={data['amount']} "
                                f"total={data['total']} date={data['date']}")
                    if data['date']:
                        date_input.value = data['date'].strftime('%Y-%m-%d')
                    desc_input.value = data['description']
                    amount_input.value = data['amount'] or data['total']
                    tps_check.value = data['tps'] > 0
                    tvq_check.value = data['tvq'] > 0
                    notes_input.value = data['notes']
                    update_total()
                    progress.dismiss()
                    logger.info("[receipt] form fields updated")
                    msg = f'Receipt "{name}" read — review every field, then Add Expense.'
                    if data['warnings']:
                        msg += ' ⚠ ' + ' '.join(data['warnings'])
                    ui.notify(msg, color='emerald-500', multi_line=True, timeout=8000)
                except Exception as ex:
                    logger.exception(f"[receipt] UNEXPECTED handler error: {ex!r}")
                    ui.notify(f'Receipt error: {ex}', color='red-500')

            with ui.column().classes('w-full gap-1 mt-3'):
                if ai_ready:
                    ui.label('📄 Upload a receipt (image or PDF) — AI reads it and fills the form below. '
                             'Review every field, then click Add Expense.').classes('text-xs text-violet-600 font-medium')
                _upload_label = 'Upload receipt — AI auto-fill' if ai_ready else 'Attach receipt (optional)'
                _upload_color = 'color=violet-600' if ai_ready else 'color=indigo-600'
                ui.upload(on_upload=on_receipt_upload, label=_upload_label, auto_upload=True
                          ).props('flat ' + _upload_color).classes('w-full max-w-md')

            # ── Bulk import: drop many receipts → auto-create pending rows ──
            if ai_ready:
                async def on_bulk_upload(e):
                    upload_client = context.client
                    files = e.files
                    logger.info(f"[bulk] received {len(files)} file(s)")
                    progress = ui.notification(f'Reading {len(files)} receipt(s) with AI…',
                                               spinner=True, timeout=None)
                    with Session(engine) as s:
                        unassigned_id = get_or_create_unassigned_customer(s).id
                    created = failed = 0
                    for f in files:
                        try:
                            name, content = await read_upload_file(f)
                            data = await run.io_bound(_do_extract, content, name)
                            with Session(engine) as s:
                                exp = ClientExpense(
                                    customer_id=unassigned_id,
                                    description=data['description'],
                                    date=data['date'] or utc_now(),
                                    amount=data['amount'], tps=data['tps'], tvq=data['tvq'],
                                    total=data['total'] or data['amount'],
                                    status='pending', notes=data['notes'] or None,
                                )
                                s.add(exp); s.commit(); s.refresh(exp)
                                s.add(ClientExpenseEvent(client_expense_id=exp.id, status='pending'))
                                fname = f"{exp.id}_{sanitize_receipt_filename(name)}"
                                path = os.path.join('data/receipts', fname)
                                with open(path, 'wb') as fh:
                                    fh.write(content)
                                exp.receipt_path = path
                                s.add(exp); s.commit()
                            created += 1
                        except Exception as ex:
                            logger.warning(f"[bulk] failed for {getattr(f, 'name', '?')}: {ex!r}")
                            failed += 1
                    safe_notification_dismiss(progress)
                    msg = f'Imported {created} expense(s) into "Unassigned" — review and assign customers below.'
                    if failed:
                        msg += f' {failed} could not be read and were skipped.'
                    safe_client_notify(upload_client, msg, color='emerald-500' if created else 'amber-500',
                                       multi_line=True, timeout=8000)
                    if client_is_active(upload_client):
                        refresh_table()

                with ui.column().classes('w-full gap-1 mt-3'):
                    ui.label('📥 Or drop several receipts at once — each is read and added to the list '
                             'as a pending expense under "Unassigned".').classes('text-xs text-violet-600 font-medium')
                    ui.upload(on_multi_upload=on_bulk_upload, label='Import multiple receipts',
                              multiple=True, auto_upload=True).props('flat color=violet-600').classes('w-full max-w-md')

            ui.button('Add Expense', icon='add', on_click=save_expense).classes('btn-primary h-10 px-6 ml-auto')

        # ── Filters ──
        filter_state = {'customer': 'All', 'status': 'All', 'min_total': None, 'max_total': None, 'duplicate_total': None}
        filter_controls_paused = {'value': False}
        with ui.card().classes('w-full p-4 premium-card mb-4'):
            with ui.row().classes('w-full items-center gap-3 flex-wrap'):
                ui.label('Filter:').classes('text-sm font-semibold text-slate-500 mr-2')
                cust_filter = ui.select({'All': 'All customers', **customer_options}, value='All').props('dense outlined').classes('w-56')
                status_filter = ui.select(['All', *CLIENT_EXPENSE_STATUSES], value='All').props('dense outlined').classes('w-44')
                amount_min_filter = ui.number('Min total', value=None, min=0, step=0.01, format='%.2f').props('dense outlined prefix=$').classes('w-36')
                amount_max_filter = ui.number('Max total', value=None, min=0, step=0.01, format='%.2f').props('dense outlined prefix=$').classes('w-36')

                def set_filter_control_values(customer='All', status='All', min_total=None, max_total=None):
                    filter_controls_paused['value'] = True
                    try:
                        cust_filter.value = customer
                        status_filter.value = status
                        amount_min_filter.value = min_total
                        amount_max_filter.value = max_total
                    finally:
                        filter_controls_paused['value'] = False

                def update_filter(key, value):
                    if filter_controls_paused['value']:
                        return
                    filter_state[key] = value
                    if key in {'min_total', 'max_total'}:
                        filter_state['duplicate_total'] = None
                    refresh_table()

                def clear_filters():
                    filter_state.update(customer='All', status='All', min_total=None, max_total=None, duplicate_total=None)
                    set_filter_control_values()
                    refresh_table()

                def update_filter_direct(key, value):
                    if filter_controls_paused['value']:
                        return
                    filter_state[key] = value
                    refresh_table()

                cust_filter.on_value_change(lambda e: update_filter_direct('customer', e.value))
                status_filter.on_value_change(lambda e: update_filter_direct('status', e.value))
                amount_min_filter.on_value_change(lambda e: update_filter('min_total', e.value))
                amount_max_filter.on_value_change(lambda e: update_filter('max_total', e.value))
                ui.button('Clear', icon='backspace', on_click=clear_filters).props('flat dense no-caps').classes('text-slate-500')

        table_container = ui.column().classes('w-full')

        # Workflow reference, always visible below the list.
        render_client_expense_workflow()

        def open_receipt(expense_id):
            with Session(engine) as s:
                exp = s.get(ClientExpense, expense_id)
                path = exp.receipt_path if exp else None
            if path and os.path.exists(path):
                ui.download(path)
            else:
                ui.notify('No receipt on file', color='amber-500')

        def do_transition(expense_id, target):
            try:
                with Session(engine) as s:
                    transition_client_expense(s, expense_id, target)
                ui.notify(f'Status → {target}', color='emerald-500')
                refresh_table()
            except ValueError as ex:
                ui.notify(str(ex), color='red-500')

        def do_attach(expense_id, invoice_id, dialog):
            try:
                with Session(engine) as s:
                    attach_client_expense_to_invoice(s, expense_id, invoice_id)
                ui.notify('Attached to invoice', color='emerald-500')
                dialog.close(); refresh_table()
            except ValueError as ex:
                ui.notify(str(ex), color='red-500')

        def open_detail(expense_id):
            with Session(engine) as s:
                exp = s.get(ClientExpense, expense_id)
                events = s.exec(
                    select(ClientExpenseEvent).where(ClientExpenseEvent.client_expense_id == expense_id)
                    .order_by(ClientExpenseEvent.changed_at)
                ).all()
                draft_invoices = s.exec(
                    select(Invoice).where(Invoice.customer_id == exp.customer_id, Invoice.status == 'Draft')
                ).all()
                draft_options = {inv.id: f"#{inv.number} (${inv.total:,.2f})" for inv in draft_invoices}
                event_rows = [(e.status, e.changed_at.strftime('%Y-%m-%d %H:%M'), e.notes or '') for e in events]
                cust_name = customer_options.get(exp.customer_id, '?')
                cur_status, exp_total, exp_desc = exp.status, exp.total, exp.description
                attached_invoice = exp.invoice_id

                def _fmt_dt(v, with_time=True):
                    if v is None:
                        return '—'
                    return v.strftime('%Y-%m-%d %H:%M' if with_time else '%Y-%m-%d')

                detail_rows = [
                    ('ID', str(exp.id)),
                    ('Customer', cust_name),
                    ('Description', exp.description or '—'),
                    ('Date', _fmt_dt(exp.date, with_time=False)),
                    ('Subtotal (pre-tax)', f'${exp.amount:,.2f}'),
                    ('TPS', f'${exp.tps:,.2f}'),
                    ('TVQ', f'${exp.tvq:,.2f}'),
                    ('Total (tax-incl.)', f'${exp.total:,.2f}'),
                    ('Status', exp.status),
                    ('Receipt', exp.receipt_path or '—'),
                    ('Claim date', _fmt_dt(exp.claim_date)),
                    ('Reimbursed date', _fmt_dt(exp.reimbursed_date)),
                    ('Invoice', f'#{exp.invoice_id}' if exp.invoice_id else '—'),
                    ('Recurring', 'Yes' if exp.is_recurring else 'No'),
                    ('Recurrence day', str(exp.recurrence_day) if exp.recurrence_day is not None else '—'),
                    ('Next due date', _fmt_dt(exp.next_due_date, with_time=False)),
                    ('Notes', exp.notes or '—'),
                    ('Created at', _fmt_dt(exp.created_at)),
                    ('Updated at', _fmt_dt(exp.updated_at)),
                ]
            with ui.dialog() as dialog, ui.card().classes('p-8 w-[620px] max-w-[calc(100vw-2rem)] premium-card'):
                ui.label(exp_desc).classes('text-2xl font-extrabold text-slate-900 dark:text-slate-100')
                ui.label(f'{cust_name} · ${exp_total:,.2f}').classes('text-slate-500 mb-4')
                with ui.row().classes('items-center gap-2 mb-4'):
                    ui.label('Status:').classes('text-sm font-semibold text-slate-500')
                    ui.badge(cur_status).props(f'color={CLIENT_EXPENSE_STATUS_COLORS.get(cur_status, "slate-500")}')

                # Full workflow so the current status reads in context.
                render_client_expense_workflow(framed=False)

                ui.label('Details').classes('text-xs font-black text-slate-400 uppercase tracking-widest')
                with ui.grid(columns='auto 1fr').classes('gap-x-6 gap-y-2 mt-2 mb-6 w-full'):
                    for field_label, field_value in detail_rows:
                        ui.label(field_label).classes('text-sm font-semibold text-slate-500 whitespace-nowrap')
                        ui.label(field_value).classes('text-sm text-slate-800 dark:text-slate-200 break-all')

                next_states = client_expense_next_states(cur_status)
                if next_states:
                    ui.label('Advance status').classes('text-xs font-black text-slate-400 uppercase tracking-widest')
                    with ui.row().classes('gap-2 mb-6'):
                        for st in next_states:
                            ui.button(st, on_click=lambda s=st: (dialog.close(), do_transition(expense_id, s))).props('outline no-caps').classes('rounded-lg')
                else:
                    ui.label('This expense is in a terminal state.').classes('text-sm text-slate-400 mb-6')

                if attached_invoice is None and draft_options:
                    ui.label('Attach to draft invoice').classes('text-xs font-black text-slate-400 uppercase tracking-widest')
                    with ui.row().classes('items-center gap-2 mb-6'):
                        inv_pick = ui.select(draft_options, label='Draft invoice').props('dense outlined').classes('flex-1')
                        ui.button('Attach', icon='link', on_click=lambda: inv_pick.value and do_attach(expense_id, inv_pick.value, dialog)).props('flat color=indigo-600')
                elif attached_invoice is not None:
                    ui.label(f'Attached to invoice #{attached_invoice}').classes('text-sm text-emerald-600 mb-6')

                ui.label('History').classes('text-xs font-black text-slate-400 uppercase tracking-widest')
                with ui.column().classes('gap-1 mt-2 mb-4'):
                    for status, when, note in event_rows:
                        with ui.row().classes('items-center gap-3'):
                            ui.badge(status).props(f'color={CLIENT_EXPENSE_STATUS_COLORS.get(status, "slate-500")}')
                            ui.label(when).classes('text-sm text-slate-500')
                            if note:
                                ui.label(f'— {note}').classes('text-sm text-slate-400')
                with ui.row().classes('w-full justify-end'):
                    ui.button('Close', on_click=dialog.close).props('flat').classes('text-slate-400')
            dialog.open()

        def do_reassign(expense_id, customer_id):
            try:
                with Session(engine) as s:
                    reassign_client_expense_customer(s, expense_id, customer_id)
                ui.notify('Customer updated', color='emerald-500')
                refresh_table()
            except ValueError as ex:
                ui.notify(str(ex), color='red-500')

        def do_set_ref(expense_id, ref):
            try:
                with Session(engine) as s:
                    set_client_expense_external_ref(s, expense_id, ref)
                ui.notify('Reference saved', color='emerald-500')
                refresh_table()
            except ValueError as ex:
                ui.notify(str(ex), color='red-500')

        def open_preview(url):
            # A real <img> element — ui.image (q-img) collapses to 0×0 and
            # ui.html doesn't inject here; ui.element('img') renders reliably.
            with ui.dialog() as d, ui.card().classes('p-2'):
                ui.element('img').props(f'src="{url}"').style(
                    'max-width:85vw;max-height:85vh;display:block;border-radius:8px')
            d.open()

        def filter_by_duplicate_total(total):
            filter_state.update(customer='All', status='All', min_total=total, max_total=total, duplicate_total=total)
            set_filter_control_values(min_total=total, max_total=total)
            ui.notify(f'Filtering possible duplicates at ${total:,.2f}', color='amber-600')
            refresh_table()

        def refresh_table():
            table_container.clear()
            with Session(engine) as s:
                customers_now = s.exec(select(Customer)).all()
                expenses_all = s.exec(select(ClientExpense).order_by(ClientExpense.date.desc())).all()
                dup_ids = flag_duplicate_expense_ids(expenses_all)
                expenses = filter_client_expenses(expenses_all, filter_state)
                last_changes = {e.id: _client_expense_last_change(s, e) for e in expenses}
            cust_opts = {c.id: c.name for c in customers_now}
            with table_container:
                if not expenses:
                    with ui.card().classes('w-full p-10 premium-card items-center justify-center'):
                        ui.icon('request_quote', size='40px', color='slate-300')
                        ui.label('No client expenses yet').classes('text-slate-400 text-sm mt-2')
                    return
                cols = [
                    {'name': 'date', 'label': 'Date', 'field': 'date_fmt', 'align': 'left'},
                    {'name': 'receipt', 'label': '', 'field': 'preview', 'align': 'center'},
                    {'name': 'customer', 'label': 'Customer', 'field': 'customer_id', 'align': 'left'},
                    {'name': 'desc', 'label': 'Description', 'field': 'description', 'align': 'left'},
                    {'name': 'total', 'label': 'Total', 'field': 'total_fmt', 'align': 'right'},
                    {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'center'},
                    {'name': 'ref', 'label': 'Ref. #', 'field': 'external_ref', 'align': 'left'},
                    {'name': 'flags', 'label': '', 'field': 'is_dup', 'align': 'center'},
                    {'name': 'aging', 'label': 'Last change', 'field': 'aging', 'align': 'center'},
                    {'name': 'actions', 'label': '', 'field': 'actions', 'align': 'right'},
                ]
                rows = []
                for exp in expenses:
                    last = last_changes[exp.id]
                    days = (today - last).days
                    rows.append({
                        'id': exp.id,
                        'date_fmt': exp.date.strftime('%Y-%m-%d'),
                        'customer_id': exp.customer_id,
                        'cname': cust_opts.get(exp.customer_id, '?'),
                        'description': exp.description,
                        'total': exp.total,
                        'total_fmt': f'${exp.total:,.2f}',
                        'status': exp.status,
                        'external_ref': exp.external_ref or '',
                        'aging': f'{days}d',
                        'preview': receipt_preview_url(exp.receipt_path),
                        'has_receipt': bool(exp.receipt_path),
                        'is_dup': exp.id in dup_ids,
                        'followup': client_expense_needs_followup(exp.status, last, today),
                    })
                cust_opts_js = json.dumps([{'label': n, 'value': cid} for cid, n in cust_opts.items()])

                def _perform_delete(ids):
                    with Session(engine) as s:
                        result = delete_client_expenses(s, ids)
                    for p in result['deleted_paths']:
                        for fp in (p, p + '.thumb.png'):
                            try:
                                if os.path.exists(fp):
                                    os.remove(fp)
                            except OSError:
                                pass
                    msg = f"Deleted {result['deleted']} expense(s)."
                    if result['skipped']:
                        msg += f" {result['skipped']} attached to an invoice were kept."
                    ui.notify(msg, color='emerald-500' if result['deleted'] else 'amber-500')
                    refresh_table()

                def do_delete_selected():
                    ids = [r['id'] for r in tbl.selected]
                    if not ids:
                        ui.notify('Select one or more rows to delete first', color='amber-500')
                        return
                    with ui.dialog() as confirm, ui.card().classes('p-6 premium-card'):
                        ui.label(f'Delete {len(ids)} selected expense(s)?').classes('text-lg font-bold')
                        ui.label('This permanently removes them and their receipts. '
                                 'Expenses attached to an invoice are kept.').classes('text-sm text-slate-500 mt-1')
                        with ui.row().classes('w-full justify-end gap-2 mt-5'):
                            ui.button('Cancel', on_click=confirm.close).props('flat').classes('text-slate-400')
                            ui.button('Delete', color='red',
                                      on_click=lambda: (confirm.close(), _perform_delete(ids))).props('unelevated')
                    confirm.open()

                with ui.card().classes('w-full p-0 premium-card overflow-hidden'):
                    with ui.row().classes('w-full items-center gap-3 px-4 pt-3'):
                        ui.label('Select rows to reassign or delete').classes('text-xs text-slate-400')
                        ui.button('Delete selected', icon='delete', color='red',
                                  on_click=do_delete_selected).props('flat dense no-caps').classes('ml-auto')
                    tbl = ui.table(columns=cols, rows=rows, row_key='id', selection='multiple').classes('w-full border-none shadow-none')
                    tbl.add_slot('body-cell-status', '''<q-td :props="props"><q-badge :color="{'pending':'amber-500','claimed':'indigo-500','waiting':'orange-500','disputed':'red-500','reimbursed':'emerald-500','written_off':'slate-500'}[props.row.status] || 'slate-500'" :style="{padding:'6px 14px',borderRadius:'100px',fontWeight:'700',fontSize:'10px'}">{{ props.row.status }}</q-badge></q-td>''')
                    tbl.add_slot('body-cell-aging', '''<q-td :props="props"><span :class="props.row.followup ? 'text-red-500 font-bold' : 'text-slate-500'">{{ props.row.aging }}<q-icon v-if="props.row.followup" name="warning" class="q-ml-xs" /></span></q-td>''')
                    tbl.add_slot('body-cell-customer', f'''<q-td :props="props"><q-select dense options-dense borderless emit-value map-options :model-value="props.row.customer_id" :options='{cust_opts_js}' @update:model-value="val => $parent.$emit('reassign', {{id: props.row.id, customer_id: val}})" style="min-width:150px" /></q-td>''')
                    tbl.add_slot('body-cell-receipt', '''<q-td :props="props"><img v-if="props.row.preview" :src="props.row.preview" style="width:40px;height:40px;min-width:40px;max-width:40px;object-fit:cover;border-radius:6px;cursor:pointer;border:1px solid #e2e8f0" @click="$parent.$emit('preview', props.row.preview)"><q-tooltip v-if="props.row.preview">Click to enlarge</q-tooltip></q-td>''')
                    tbl.add_slot('body-cell-ref', '''<q-td :props="props"><q-input dense borderless :model-value="props.row.external_ref" placeholder="—" input-class="text-slate-600" @change="val => $parent.$emit('setref', {id: props.row.id, ref: val})" style="min-width:110px" /></q-td>''')
                    tbl.add_slot('body-cell-flags', '''<q-td :props="props"><q-badge v-if="props.row.is_dup" color="amber-600" :style="{padding:'5px 10px',borderRadius:'100px',fontWeight:'700',fontSize:'9px',cursor:'pointer'}" @click.stop="$parent.$emit('duplicate-total', props.row.total)">DUP<q-tooltip>Filter all expenses with this same total</q-tooltip></q-badge></q-td>''')
                    tbl.add_slot('body-cell-actions', '''<q-td :props="props"><q-btn flat round icon="open_in_full" title="Details" @click="$parent.$emit('detail', props.row.id)" /><q-btn v-if="props.row.has_receipt" flat round color="indigo-600" icon="download" title="Download receipt" @click="$parent.$emit('receipt', props.row.id)" /></q-td>''')
                    tbl.on('detail', lambda e: open_detail(e.args))
                    tbl.on('receipt', lambda e: open_receipt(e.args))
                    tbl.on('reassign', lambda e: do_reassign(e.args['id'], e.args['customer_id']))
                    tbl.on('setref', lambda e: do_set_ref(e.args['id'], e.args['ref']))
                    tbl.on('preview', lambda e: open_preview(e.args))
                    tbl.on('duplicate-total', lambda e: filter_by_duplicate_total(e.args))

        refresh_table()


@ui.page('/reports')
def reports_page():
    inject_premium_styles(); create_menu('/reports')

    TPS_RATE = 0.05
    TVQ_RATE = 0.09975

    today = datetime.today()
    first_this_month = today.replace(day=1)
    first_this_year  = today.replace(month=1, day=1)
    last_month_end   = first_this_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    last_year_start  = today.replace(year=today.year - 1, month=1, day=1)
    last_year_end    = today.replace(year=today.year - 1, month=12, day=31)

    PRESETS = {
        'This Month': (first_this_month, today),
        'Last Month': (last_month_start, last_month_end),
        'This Year':  (first_this_year,  today),
        'Last Year':  (last_year_start,  last_year_end),
        'All Time':   (datetime(2000, 1, 1), today),
        'Custom':     None,
    }

    state = {'preset': 'This Month', 'from': first_this_month, 'to': today}

    with Session(engine) as s:
        all_invoices  = s.exec(select(Invoice).order_by(Invoice.date.desc())).all()
        all_customers = s.exec(select(Customer)).all()
    cust_map = {c.id: c.name for c in all_customers}

    # ── Helper: expandable report card ──
    def report_card(icon, title, description, color='indigo-600'):
        expanded = {'open': False}
        with ui.card().classes('w-full p-0 premium-card overflow-hidden'):
            with ui.row().classes('w-full items-center gap-4 p-5 cursor-pointer') as header:
                ui.icon(icon, color=color, size='24px')
                with ui.column().classes('flex-1'):
                    ui.label(title).classes('text-base font-bold text-slate-800 dark:text-slate-200')
                    ui.label(description).classes('text-xs text-slate-400')
                chevron = ui.icon('expand_more', size='24px', color='slate-400')
            content = ui.column().classes('w-full px-5 pb-5 gap-4')
            content.set_visibility(False)

        def toggle():
            expanded['open'] = not expanded['open']
            content.set_visibility(expanded['open'])
            chevron.name = 'expand_less' if expanded['open'] else 'expand_more'

        header.on('click', toggle)
        return content

    def section_header(title):
        ui.label(title).classes('text-xs font-black text-slate-400 uppercase tracking-widest mt-4 mb-1 px-1')

    # ── Report renderers ──
    def render_sales_summary(container, invoices):
        container.clear()
        paid_invs = [i for i in invoices if i.status == 'Paid']
        sent_invs = [i for i in invoices if i.status == 'Sent']
        canc_invs = [i for i in invoices if i.status == 'Cancelled']
        total_invoiced    = sum(i.total for i in invoices if i.status != 'Cancelled')
        total_paid        = sum(i.total for i in paid_invs)
        total_outstanding = sum(i.total for i in sent_invs)

        with container:
            with ui.row().classes('w-full gap-4'):
                for label, val, color, icon in [
                    ('Total Invoiced', total_invoiced,    'indigo-600',  'calculate'),
                    ('Collected',      total_paid,        'emerald-600', 'check_circle'),
                    ('Outstanding',    total_outstanding, 'amber-600',   'hourglass_top'),
                    ('Cancelled',      sum(i.total for i in canc_invs), 'red-400', 'cancel'),
                ]:
                    with ui.card().classes('flex-1 p-5 bg-slate-50 dark:bg-slate-800 rounded-xl'):
                        with ui.row().classes('items-center gap-2 mb-1'):
                            ui.icon(icon, color=color, size='16px')
                            ui.label(label).classes('text-[10px] font-black text-slate-400 uppercase tracking-widest')
                        ui.label(f'${val:,.2f}').classes('text-2xl font-black text-slate-900 dark:text-slate-100')

            cols = [
                {'name': 'num',      'label': '#',        'field': 'number',    'align': 'left'},
                {'name': 'cust',     'label': 'Client',   'field': 'cname',     'align': 'left'},
                {'name': 'date',     'label': 'Date',     'field': 'date_fmt',  'align': 'left'},
                {'name': 'status',   'label': 'Status',   'field': 'status',    'align': 'center'},
                {'name': 'subtotal', 'label': 'Subtotal', 'field': 'sub_fmt',   'align': 'right'},
                {'name': 'taxes',    'label': 'Taxes',    'field': 'tax_fmt',   'align': 'right'},
                {'name': 'total',    'label': 'Total',    'field': 'total_fmt', 'align': 'right'},
            ]
            rows = [{
                **i.model_dump(),
                'cname':     cust_map.get(i.customer_id, '?'),
                'date_fmt':  i.date.strftime('%Y-%m-%d'),
                'sub_fmt':   f'${i.subtotal:,.2f}',
                'tax_fmt':   f'${i.tax_total:,.2f}',
                'total_fmt': f'${i.total:,.2f}',
            } for i in invoices]
            if rows:
                t = ui.table(columns=cols, rows=rows, row_key='id').classes('w-full border-none shadow-none')
                t.add_slot('body-cell-status', '''<q-td :props="props"><q-badge :color="props.row.status === 'Paid' ? 'green' : (props.row.status === 'Sent' ? 'indigo' : (props.row.status === 'Cancelled' ? 'red' : 'amber'))" :style="{padding:'4px 12px',borderRadius:'999px',fontWeight:'700',fontSize:'10px'}">{{ props.row.status }}</q-badge></q-td>''')
            else:
                with ui.column().classes('w-full items-center p-8'):
                    ui.icon('search_off', size='40px', color='slate-300')
                    ui.label('No invoices in this period').classes('text-slate-400 text-sm mt-2')

    def render_revenue_trend(container, invoices):
        container.clear()
        paid = [i for i in invoices if i.status == 'Paid']
        monthly = defaultdict(float)
        for inv in paid:
            key = inv.date.strftime('%b %Y')
            monthly[key] += inv.total
        sorted_months = sorted(monthly.keys(), key=lambda m: datetime.strptime(m, '%b %Y'))
        vals = [monthly[m] for m in sorted_months]

        with container:
            if not sorted_months:
                with ui.column().classes('w-full items-center p-8'):
                    ui.icon('bar_chart', size='40px', color='slate-300')
                    ui.label('No paid invoices in this period').classes('text-slate-400 text-sm mt-2')
                return
            fig = go.Figure(go.Bar(
                x=sorted_months,
                y=vals,
                marker_color='#4f46e5',
                text=[f'${v:,.0f}' for v in vals],
                textposition='outside',
            ))
            fig.update_layout(
                margin=dict(t=20, b=20, l=20, r=20),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=False, tickfont=dict(size=11)),
                yaxis=dict(showgrid=True, gridcolor='#e2e8f0', tickprefix='$', tickfont=dict(size=11)),
                height=280,
            )
            ui.plotly(fig).classes('w-full')

    def render_tax_report(container, invoices):
        container.clear()
        paid_invs = [i for i in invoices if i.status == 'Paid']
        paid_subtotal = sum(i.subtotal for i in paid_invs)
        tps_collected = paid_subtotal * TPS_RATE
        tvq_collected = paid_subtotal * TVQ_RATE

        with container:
            with ui.row().classes('w-full gap-4'):
                for label, val, sub, color in [
                    ('TPS Collected',   tps_collected,  f'5% on ${paid_subtotal:,.2f}',    'blue-600'),
                    ('TVQ Collected',   tvq_collected,  f'9.975% on ${paid_subtotal:,.2f}', 'purple-600'),
                    ('Total Taxes Due', tps_collected + tvq_collected, 'TPS + TVQ',         'emerald-600'),
                    ('Taxable Revenue', paid_subtotal,  f'{len(paid_invs)} paid invoices',  'indigo-600'),
                ]:
                    with ui.card().classes('flex-1 p-5 bg-slate-50 dark:bg-slate-800 rounded-xl'):
                        ui.label(label).classes('text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1')
                        ui.label(f'${val:,.2f}').classes('text-2xl font-black text-slate-900 dark:text-slate-100')
                        ui.label(sub).classes('text-xs text-slate-400 mt-1')

            tax_cols = [
                {'name': 'num',      'label': '#',            'field': 'number',   'align': 'left'},
                {'name': 'cust',     'label': 'Client',       'field': 'cname',    'align': 'left'},
                {'name': 'date',     'label': 'Date',         'field': 'date_fmt', 'align': 'left'},
                {'name': 'subtotal', 'label': 'Subtotal',     'field': 'sub_fmt',  'align': 'right'},
                {'name': 'tps',      'label': 'TPS (5%)',     'field': 'tps_fmt',  'align': 'right'},
                {'name': 'tvq',      'label': 'TVQ (9.975%)', 'field': 'tvq_fmt',  'align': 'right'},
                {'name': 'total',    'label': 'Total',        'field': 'total_fmt','align': 'right'},
            ]
            tax_rows = [{
                **i.model_dump(),
                'cname':     cust_map.get(i.customer_id, '?'),
                'date_fmt':  i.date.strftime('%Y-%m-%d'),
                'sub_fmt':   f'${i.subtotal:,.2f}',
                'tps_fmt':   f'${i.subtotal * TPS_RATE:,.2f}',
                'tvq_fmt':   f'${i.subtotal * TVQ_RATE:,.2f}',
                'total_fmt': f'${i.total:,.2f}',
            } for i in paid_invs]
            if tax_rows:
                ui.table(columns=tax_cols, rows=tax_rows, row_key='id').classes('w-full border-none shadow-none')
            else:
                with ui.column().classes('w-full items-center p-8'):
                    ui.icon('receipt_long', size='40px', color='slate-300')
                    ui.label('No paid invoices in this period').classes('text-slate-400 text-sm mt-2')

    def render_income_by_customer(container, invoices):
        container.clear()
        paid_invs = [i for i in invoices if i.status == 'Paid']
        by_cust = defaultdict(lambda: {'count': 0, 'subtotal': 0.0, 'taxes': 0.0, 'total': 0.0})
        for inv in paid_invs:
            cname = cust_map.get(inv.customer_id, 'Unknown')
            by_cust[cname]['count']    += 1
            by_cust[cname]['subtotal'] += inv.subtotal
            by_cust[cname]['taxes']    += inv.tax_total
            by_cust[cname]['total']    += inv.total

        with container:
            if not by_cust:
                with ui.column().classes('w-full items-center p-8'):
                    ui.icon('group', size='40px', color='slate-300')
                    ui.label('No paid invoices in this period').classes('text-slate-400 text-sm mt-2')
                return

            sorted_custs = sorted(by_cust.items(), key=lambda x: x[1]['total'], reverse=True)

            with ui.row().classes('w-full gap-6 items-start'):
                with ui.column().classes('flex-1'):
                    cols = [
                        {'name': 'cust',     'label': 'Customer',   'field': 'cust',      'align': 'left'},
                        {'name': 'count',    'label': '# Invoices', 'field': 'count',     'align': 'center'},
                        {'name': 'subtotal', 'label': 'Subtotal',   'field': 'sub_fmt',   'align': 'right'},
                        {'name': 'taxes',    'label': 'Taxes',      'field': 'tax_fmt',   'align': 'right'},
                        {'name': 'total',    'label': 'Total Paid', 'field': 'total_fmt', 'align': 'right'},
                    ]
                    rows = [{
                        'cust':      name,
                        'count':     data['count'],
                        'sub_fmt':   f'${data["subtotal"]:,.2f}',
                        'tax_fmt':   f'${data["taxes"]:,.2f}',
                        'total_fmt': f'${data["total"]:,.2f}',
                    } for name, data in sorted_custs]
                    tbl = ui.table(columns=cols, rows=rows, row_key='cust').classes('w-full border-none shadow-none')
                    tbl.add_slot('body-cell-total', '''<q-td :props="props"><span class="font-bold text-indigo-600">{{ props.row.total_fmt }}</span></q-td>''')

                with ui.column().classes('w-72 shrink-0'):
                    labels = [name for name, _ in sorted_custs]
                    values = [data['total'] for _, data in sorted_custs]
                    fig = go.Figure(go.Pie(
                        labels=labels, values=values,
                        hole=0.55,
                        marker_colors=['#4f46e5', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
                        textinfo='percent',
                        hovertemplate='%{label}: $%{value:,.2f}<extra></extra>',
                    ))
                    fig.update_layout(
                        margin=dict(t=10, b=10, l=10, r=10),
                        paper_bgcolor='rgba(0,0,0,0)',
                        showlegend=True,
                        legend=dict(font=dict(size=11)),
                        height=240,
                    )
                    ui.plotly(fig).classes('w-full')

    def render_aged_receivables(container, invoices):
        # Always receives all_invoices (unfiltered) — AR exposure should show all outstanding, not period-scoped
        container.clear()
        today = datetime.today()
        unpaid = [i for i in invoices if i.status in ('Sent', 'Overdue')]

        buckets = {'Current (0\u201330d)': [], '31\u201360d': [], '61\u201390d': [], '90d+': []}
        for inv in unpaid:
            ref_date = inv.due_date or inv.date
            age = (today - ref_date).days
            if age <= 30:
                buckets['Current (0\u201330d)'].append(inv)
            elif age <= 60:
                buckets['31\u201360d'].append(inv)
            elif age <= 90:
                buckets['61\u201390d'].append(inv)
            else:
                buckets['90d+'].append(inv)

        bucket_colors = {
            'Current (0\u201330d)': 'emerald-600',
            '31\u201360d':          'amber-500',
            '61\u201390d':          'orange-500',
            '90d+':            'red-600',
        }

        with container:
            if not unpaid:
                with ui.column().classes('w-full items-center p-8'):
                    ui.icon('check_circle', size='40px', color='emerald-400')
                    ui.label('No outstanding invoices').classes('text-slate-400 text-sm mt-2')
                return

            with ui.row().classes('w-full gap-4 mb-4'):
                for bucket, invs in buckets.items():
                    total = sum(i.total for i in invs)
                    color = bucket_colors[bucket]
                    with ui.card().classes('flex-1 p-4 bg-slate-50 dark:bg-slate-800 rounded-xl'):
                        ui.label(bucket).classes(f'text-[10px] font-black text-{color} uppercase tracking-widest mb-1')
                        ui.label(f'${total:,.2f}').classes('text-xl font-black text-slate-900 dark:text-slate-100')
                        ui.label(f'{len(invs)} invoice{"s" if len(invs) != 1 else ""}').classes('text-xs text-slate-400')

            all_rows = []
            for bucket, invs in buckets.items():
                for inv in invs:
                    ref_date = inv.due_date or inv.date
                    age = (today - ref_date).days
                    all_rows.append({
                        **inv.model_dump(),
                        'cname':     cust_map.get(inv.customer_id, '?'),
                        'date_fmt':  inv.date.strftime('%Y-%m-%d'),
                        'due_fmt':   inv.due_date.strftime('%Y-%m-%d') if inv.due_date else '\u2014',
                        'age_days':  age,
                        'bucket':    bucket,
                        'total_fmt': f'${inv.total:,.2f}',
                    })

            cols = [
                {'name': 'num',    'label': '#',           'field': 'number',   'align': 'left'},
                {'name': 'cust',   'label': 'Client',      'field': 'cname',    'align': 'left'},
                {'name': 'date',   'label': 'Invoice Date','field': 'date_fmt', 'align': 'left'},
                {'name': 'due',    'label': 'Due Date',    'field': 'due_fmt',  'align': 'left'},
                {'name': 'age',    'label': 'Days Old',    'field': 'age_days', 'align': 'center'},
                {'name': 'bucket', 'label': 'Bucket',      'field': 'bucket',   'align': 'center'},
                {'name': 'total',  'label': 'Total Due',   'field': 'total_fmt','align': 'right'},
            ]
            tbl = ui.table(columns=cols, rows=all_rows, row_key='id').classes('w-full border-none shadow-none')
            tbl.add_slot('body-cell-bucket', '''
                <q-td :props="props">
                  <q-badge
                    :color="props.row.bucket === 'Current (0\u201330d)' ? 'green' : (props.row.bucket === '31\u201360d' ? 'amber' : (props.row.bucket === '61\u201390d' ? 'orange' : 'red'))"
                    :style="{padding:'3px 10px',borderRadius:'999px',fontWeight:'700',fontSize:'10px'}">
                    {{ props.row.bucket }}
                  </q-badge>
                </q-td>''')

    # ── Page layout ──
    def apply_filter():
        d_from = state['from']
        d_to   = state['to'].replace(hour=23, minute=59, second=59)
        filtered = [i for i in all_invoices if d_from <= i.date <= d_to]
        render_sales_summary(sales_content, filtered)
        render_revenue_trend(trend_content, filtered)
        render_tax_report(tax_content, filtered)
        render_income_by_customer(cust_content, filtered)
        render_aged_receivables(aged_content, all_invoices)  # unfiltered: shows full AR exposure

    def open_accountant_export_dialog():
        export_state = {
            'preset': state['preset'],
            'from': state['from'],
            'to': state['to'],
        }
        export_preset_btns = {}
        format_options = {'csv_zip': 'CSV ZIP (recommended)', 'audit_xml': 'Audit XML'}

        def range_text():
            return f"{export_state['from'].strftime('%Y-%m-%d')} to {export_state['to'].strftime('%Y-%m-%d')}"

        def update_export_buttons():
            for name, btn in export_preset_btns.items():
                btn.classes(replace='btn-primary h-9 rounded-lg px-4 text-sm' if name == export_state['preset']
                            else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300')

        def set_export_preset(name):
            export_state['preset'] = name
            update_export_buttons()
            if name != 'Custom':
                d_from, d_to = PRESETS[name]
                export_state['from'] = d_from
                export_state['to'] = d_to
                custom_export_row.set_visibility(False)
                export_from_input.set_value(d_from.strftime('%Y-%m-%d'))
                export_to_input.set_value(d_to.strftime('%Y-%m-%d'))
                export_range_label.set_text(range_text())
            else:
                custom_export_row.set_visibility(True)

        def parse_custom_export_range():
            d_from = datetime.strptime(export_from_input.value, '%Y-%m-%d')
            d_to = datetime.strptime(export_to_input.value, '%Y-%m-%d')
            validate_export_range(d_from, d_to)
            return d_from, d_to

        def apply_custom_export_range():
            try:
                d_from, d_to = parse_custom_export_range()
            except (TypeError, ValueError) as exc:
                message = str(exc) if "End date must be on or after start date" in str(exc) else 'Invalid date format. Use YYYY-MM-DD'
                ui.notify(message, color='red-500')
                return
            export_state['preset'] = 'Custom'
            export_state['from'] = d_from
            export_state['to'] = d_to
            update_export_buttons()
            export_range_label.set_text(range_text())

        def export_for_accountant():
            try:
                if export_state['preset'] == 'Custom':
                    d_from, d_to = parse_custom_export_range()
                    export_state['from'] = d_from
                    export_state['to'] = d_to
                    export_range_label.set_text(range_text())
                validate_export_range(export_state['from'], export_state['to'])
                with Session(engine) as session:
                    if format_select.value == 'audit_xml':
                        path = create_accountant_audit_xml(
                            session,
                            export_state['from'],
                            export_state['to'],
                            bool(include_items_check.value),
                        )
                    else:
                        path = create_accountant_csv_zip(
                            session,
                            export_state['from'],
                            export_state['to'],
                            bool(include_items_check.value),
                        )
                ui.download(str(path))
                ui.notify(f"Accountant export ready: {range_text()}", color='emerald-500')
                dialog.close()
            except ValueError as exc:
                ui.notify(str(exc), color='red-500')
            except Exception:
                logger.exception("Error generating accountant export")
                ui.notify('Error generating accountant export', color='red-500')

        with ui.dialog() as dialog, ui.card().classes('p-8 w-[560px] max-w-[calc(100vw-2rem)] premium-card'):
            with ui.row().classes('w-full items-start justify-between gap-4 mb-5'):
                with ui.column().classes('gap-1'):
                    ui.label('Export for Accountant').classes('text-2xl font-extrabold text-slate-900 dark:text-slate-100')
                    ui.label('Choose a period and export format').classes('text-sm text-slate-400')
                ui.button(icon='close', on_click=dialog.close).props('flat round dense').classes('text-slate-400')

            ui.label('Period').classes('text-xs font-black text-slate-400 uppercase tracking-widest mb-2')
            with ui.row().classes('items-center gap-2 flex-wrap mb-3'):
                for name in PRESETS:
                    is_active = name == export_state['preset']
                    cls = 'btn-primary h-9 rounded-lg px-4 text-sm' if is_active else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                    btn = ui.button(name, on_click=lambda n=name: set_export_preset(n)).classes(cls)
                    export_preset_btns[name] = btn

            export_range_label = ui.label(range_text()).classes('text-sm text-slate-400 font-medium mb-3')

            with ui.row().classes('items-center gap-4 mb-5') as custom_export_row:
                custom_export_row.set_visibility(export_state['preset'] == 'Custom')
                export_from_input = ui.input('From', value=export_state['from'].strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                export_to_input = ui.input('To', value=export_state['to'].strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                ui.button('Apply', on_click=apply_custom_export_range).classes('btn-primary h-9 rounded-lg px-5 text-sm')

            format_select = ui.select(format_options, value='csv_zip', label='Format').props('dense outlined').classes('w-full mb-4')
            include_items_check = ui.checkbox('Include invoice line-item details', value=False).classes('mb-6')

            with ui.row().classes('w-full justify-end gap-3'):
                ui.button('Cancel', on_click=dialog.close).classes('h-10 rounded-lg px-5 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300')
                ui.button('Export', icon='download', on_click=export_for_accountant).classes('btn-primary h-10 rounded-lg px-5 text-sm')

        dialog.open()

    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        with ui.row().classes('w-full items-center justify-between gap-4 mb-6'):
            with ui.column().classes('gap-1'):
                ui.label('Reports').classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100')
                ui.label('Financial reports for any period').classes('text-slate-400 text-base')
            ui.button('Export for Accountant', icon='folder_zip', on_click=open_accountant_export_dialog).classes('btn-primary h-12 rounded-xl px-6')

        preset_btns = {}

        with ui.card().classes('w-full p-6 premium-card mb-6'):
            def set_preset(name):
                state['preset'] = name
                for n, btn in preset_btns.items():
                    btn.classes(replace='btn-primary h-9 rounded-lg px-4 text-sm' if n == name
                                else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300')
                if name != 'Custom':
                    d_from, d_to = PRESETS[name]
                    state['from'] = d_from
                    state['to']   = d_to
                    custom_row.set_visibility(False)
                    date_range_label.set_text(f"{d_from.strftime('%b %d, %Y')} — {d_to.strftime('%b %d, %Y')}")
                    apply_filter()
                else:
                    custom_row.set_visibility(True)

            with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
                with ui.row().classes('items-center gap-3 flex-wrap'):
                    ui.label('Period:').classes('text-sm font-semibold text-slate-500 mr-2')
                    for name in PRESETS:
                        is_active = name == state['preset']
                        cls = 'btn-primary h-9 rounded-lg px-4 text-sm' if is_active else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                        btn = ui.button(name, on_click=lambda n=name: set_preset(n)).classes(cls)
                        preset_btns[name] = btn
                date_range_label = ui.label(
                    f"{state['from'].strftime('%b %d, %Y')} — {state['to'].strftime('%b %d, %Y')}"
                ).classes('text-sm text-slate-400 font-medium')

            with ui.row().classes('items-center gap-4 mt-3') as custom_row:
                custom_row.set_visibility(False)
                from_input = ui.input('From', value=state['from'].strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                to_input   = ui.input('To',   value=state['to'].strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                def apply_custom():
                    try:
                        state['from'] = datetime.strptime(from_input.value, '%Y-%m-%d')
                        state['to']   = datetime.strptime(to_input.value,   '%Y-%m-%d')
                        date_range_label.set_text(f"{state['from'].strftime('%b %d, %Y')} — {state['to'].strftime('%b %d, %Y')}")
                        apply_filter()
                    except ValueError:
                        ui.notify('Invalid date format. Use YYYY-MM-DD', color='red-500')
                ui.button('Apply', on_click=apply_custom).classes('btn-primary h-9 rounded-lg px-5 text-sm')

        section_header('Income')
        sales_content = report_card('receipt_long',    'Sales Summary',              'Total invoiced, collected, and outstanding for the period')
        trend_content = report_card('bar_chart',       'Monthly Revenue Trend',      'Paid revenue per month \u2014 bar chart', color='emerald-600')

        section_header('Taxes')
        tax_content   = report_card('account_balance', 'Sales Tax Report (TPS/TVQ)', 'TPS & TVQ collected on paid invoices', color='blue-600')

        section_header('Customers')
        cust_content  = report_card('group',           'Income by Customer',         'Revenue breakdown per client', color='purple-600')
        aged_content  = report_card('hourglass_top',   'Aged Receivables',           'Unpaid invoices grouped by age (30/60/90 days)', color='amber-600')

        apply_filter()


@ui.page('/accounts')
def accounts_page():
    inject_premium_styles(); create_menu('/accounts')

    TYPE_COLORS = {
        'Asset': 'blue-500', 'Liability': 'red-400',
        'Income': 'emerald-500', 'Expense': 'amber-500', 'Equity': 'purple-500',
    }

    def render_accounts(container):
        container.clear()
        with Session(engine) as s:
            accounts = s.exec(select(Account).order_by(Account.code)).all()
        with container:
            with ui.row().classes('w-full px-6 py-2 gap-4'):
                ui.label('CODE').classes('w-16 text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('NAME').classes('flex-1 text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('TYPE').classes('w-28 text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('STATUS').classes('w-20 text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('').classes('w-24')  # actions spacer
            for acc in accounts:
                with ui.card().classes('w-full px-6 py-3 premium-card'):
                    display = ui.row().classes('w-full items-center gap-4')
                    edit_row = ui.row().classes('w-full items-center gap-4')
                    edit_row.set_visibility(False)

                    with display:
                        ui.label(acc.code).classes('w-16 font-mono text-slate-400 text-sm shrink-0')
                        ui.label(acc.name).classes('flex-1 font-semibold' + ('' if acc.is_active else ' line-through text-slate-400'))
                        with ui.row().classes('w-28 shrink-0 items-center'):
                            ui.badge(acc.type, color=TYPE_COLORS.get(acc.type, 'slate-400')).classes('text-xs px-3 py-1')
                        with ui.row().classes('w-20 shrink-0 items-center'):
                            ui.badge('Active' if acc.is_active else 'Inactive',
                                     color='emerald-500' if acc.is_active else 'slate-400').classes('text-xs px-3 py-1')
                        with ui.row().classes('w-24 shrink-0 items-center justify-end gap-1'):
                            def start_edit(d=display, e=edit_row):
                                d.set_visibility(False); e.set_visibility(True)
                            ui.button(icon='edit', on_click=start_edit).props('flat round dense').classes('text-slate-400')
                            if acc.is_system:
                                ui.icon('lock', size='18px').classes('text-slate-300').tooltip('System account — protected')
                            else:
                                def toggle_active(aid=acc.id, active=acc.is_active):
                                    with Session(engine) as s:
                                        a = s.get(Account, aid); a.is_active = not active
                                        s.add(a); s.commit()
                                    ui.navigate.reload()
                                ui.button(
                                    icon='toggle_on' if acc.is_active else 'toggle_off',
                                    on_click=toggle_active
                                ).props('flat round dense').classes('text-emerald-500' if acc.is_active else 'text-slate-300')

                                def delete_account(aid=acc.id, aname=acc.name):
                                    with Session(engine) as s:
                                        a = s.get(Account, aid); s.delete(a); s.commit()
                                    logger.info(f"Account deleted: {aname}")
                                    ui.notify(f'Account "{aname}" deleted.', color='emerald-500')
                                    ui.navigate.reload()
                                ui.button(icon='delete_outline', on_click=delete_account).props('flat round dense').classes('text-red-300')

                    with edit_row:
                        ui.label(acc.code).classes('w-16 font-mono text-slate-400 text-sm')
                        name_in = ui.input(value=acc.name).classes('flex-1').props('dense outlined')
                        desc_in = ui.input(value=acc.description or '').props('dense outlined placeholder=Description').classes('flex-1')

                        def save(aid=acc.id, ni=name_in, di=desc_in):
                            with Session(engine) as s:
                                a = s.get(Account, aid)
                                a.name = ni.value.strip()
                                a.description = di.value.strip() or None
                                s.add(a); s.commit()
                            logger.info(f"Account {aid} updated: {ni.value}")
                            ui.navigate.reload()

                        def cancel(d=display, e=edit_row):
                            e.set_visibility(False); d.set_visibility(True)

                        ui.button(icon='check', on_click=save).props('flat round dense').classes('text-emerald-600')
                        ui.button(icon='close', on_click=cancel).props('flat round dense').classes('text-slate-400')

    def open_add_account():
        with ui.dialog() as dlg, ui.card().classes('p-8 w-[480px]'):
            ui.label('New Account').classes('text-2xl font-bold mb-6')
            code_in = ui.input('Code (e.g. 5300)').classes('w-full').props('outlined rounded')
            name_in = ui.input('Name').classes('w-full').props('outlined rounded')
            type_in = ui.select(
                {t.value: t.value for t in AccountType},
                label='Type', value=AccountType.EXPENSE.value
            ).classes('w-full').props('outlined rounded')

            def save_new():
                if not code_in.value.strip() or not name_in.value.strip():
                    ui.notify('Code and Name are required.', color='red-500'); return
                with Session(engine) as s:
                    exists = s.exec(select(Account).where(Account.code == code_in.value.strip())).first()
                    if exists:
                        ui.notify('Account code already exists.', color='red-500'); return
                    s.add(Account(code=code_in.value.strip(), name=name_in.value.strip(), type=type_in.value))
                    s.commit()
                logger.info(f"Account created: {code_in.value} {name_in.value}")
                dlg.close(); ui.navigate.reload()

            with ui.row().classes('w-full justify-end gap-3 mt-6'):
                ui.button('Cancel', on_click=dlg.close).props('flat no-caps').classes('text-slate-400')
                ui.button('Create', on_click=save_new).classes('btn-primary h-12 rounded-xl px-8')
        dlg.open()

    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        with ui.row().classes('w-full justify-between items-end mb-10'):
            ui.label(_('accounts')).classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100')
            with ui.row().classes('gap-3'):
                ui.button('Export JSON', icon='download', on_click=lambda: export_accounting_data('json')).classes('btn-secondary h-12 rounded-xl px-6').props('flat')
                ui.button('Add Account', icon='add_circle', on_click=open_add_account).classes('btn-primary h-12 rounded-xl px-6')
        container = ui.column().classes('w-full gap-2')
        render_accounts(container)

@ui.page('/customers')
def customers_page():
    inject_premium_styles(); create_menu('/customers')

    def has_invoices(customer_id: int) -> bool:
        with Session(engine) as s:
            return s.exec(select(Invoice).where(Invoice.customer_id == customer_id)).first() is not None

    def render_customers(container):
        container.clear()
        with Session(engine) as s:
            customers = s.exec(select(Customer).order_by(Customer.name)).all()
        with container:
            with ui.row().classes('w-full px-6 py-2 gap-4'):
                ui.label('NAME').classes('flex-1 text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('EMAIL').classes('w-52 shrink-0 text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('PHONE').classes('w-36 shrink-0 text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('CONTACT').classes('w-36 shrink-0 text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('').classes('w-24 shrink-0')  # actions spacer
            for cust in customers:
                in_use = has_invoices(cust.id)
                with ui.card().classes('w-full px-6 py-3 premium-card'):
                    display = ui.row().classes('w-full items-center gap-4')
                    edit_row = ui.column().classes('w-full gap-3')
                    edit_row.set_visibility(False)

                    with display:
                        ui.label(cust.name).classes('flex-1 font-semibold')
                        ui.label(cust.email).classes('w-52 shrink-0 text-slate-500 text-sm truncate')
                        ui.label(cust.phone or '—').classes('w-36 shrink-0 text-slate-500 text-sm')
                        ui.label(cust.contact or '—').classes('w-36 shrink-0 text-slate-500 text-sm')
                        with ui.row().classes('w-24 shrink-0 items-center justify-end gap-1'):
                            def start_edit(d=display, e=edit_row):
                                d.set_visibility(False); e.set_visibility(True)
                            ui.button(icon='edit', on_click=start_edit).props('flat round dense').classes('text-slate-400')
                            if in_use:
                                ui.icon('receipt_long', size='18px').classes('text-slate-300').tooltip('Has invoices — cannot delete')
                            else:
                                def delete_customer(cid=cust.id, cname=cust.name):
                                    with Session(engine) as s:
                                        c = s.get(Customer, cid); s.delete(c); s.commit()
                                    logger.info(f"Customer deleted: {cname}")
                                    ui.notify(f'Customer "{cname}" deleted.', color='emerald-500')
                                    ui.navigate.reload()
                                ui.button(icon='delete_outline', on_click=delete_customer).props('flat round dense').classes('text-red-300')

                    with edit_row:
                        with ui.row().classes('w-full gap-3'):
                            name_in = ui.input(value=cust.name).props('dense outlined placeholder=Name').classes('flex-1')
                            email_in = ui.input(value=cust.email).props('dense outlined placeholder=Email').classes('flex-1')
                        with ui.row().classes('w-full gap-3'):
                            phone_in = ui.input(value=cust.phone or '').props('dense outlined placeholder=Phone').classes('w-48')
                            contact_in = ui.input(value=cust.contact or '').props('dense outlined placeholder=Contact person').classes('flex-1')
                            address_in = ui.input(value=cust.address or '').props('dense outlined placeholder=Address').classes('flex-1')

                        def save(cid=cust.id, ni=name_in, ei=email_in, phi=phone_in, coi=contact_in, ai=address_in):
                            if not ni.value.strip():
                                ui.notify('Name is required.', color='red-500'); return
                            if not ei.value.strip():
                                ui.notify('Email is required.', color='red-500'); return
                            with Session(engine) as s:
                                c = s.get(Customer, cid)
                                c.name = ni.value.strip()
                                c.email = ei.value.strip()
                                c.phone = phi.value.strip() or None
                                c.contact = coi.value.strip() or None
                                c.address = ai.value.strip() or None
                                s.add(c); s.commit()
                            logger.info(f"Customer {cid} updated: {ni.value}")
                            ui.navigate.reload()

                        def cancel(d=display, e=edit_row):
                            e.set_visibility(False); d.set_visibility(True)

                        with ui.row().classes('w-full justify-end gap-2'):
                            ui.button('Save', icon='check', on_click=save).props('no-caps').classes('btn-primary h-9 rounded-lg px-4 text-sm')
                            ui.button('Cancel', on_click=cancel).props('flat no-caps').classes('text-slate-400')

    def open_add_customer():
        with ui.dialog() as dlg, ui.card().classes('p-8 w-[520px]'):
            ui.label('New Customer').classes('text-2xl font-bold mb-6')
            name_in = ui.input('Name *').classes('w-full').props('outlined rounded')
            email_in = ui.input('Email *').classes('w-full').props('outlined rounded')
            with ui.row().classes('w-full gap-3'):
                phone_in = ui.input('Phone').classes('flex-1').props('outlined rounded')
                contact_in = ui.input('Contact Person').classes('flex-1').props('outlined rounded')
            address_in = ui.input('Address').classes('w-full').props('outlined rounded')

            def save_new():
                if not name_in.value.strip():
                    ui.notify('Name is required.', color='red-500'); return
                if not email_in.value.strip():
                    ui.notify('Email is required.', color='red-500'); return
                with Session(engine) as s:
                    s.add(Customer(
                        name=name_in.value.strip(),
                        email=email_in.value.strip(),
                        phone=phone_in.value.strip() or None,
                        contact=contact_in.value.strip() or None,
                        address=address_in.value.strip() or None,
                    ))
                    s.commit()
                logger.info(f"Customer created: {name_in.value}")
                dlg.close(); ui.navigate.reload()

            with ui.row().classes('w-full justify-end gap-3 mt-6'):
                ui.button('Cancel', on_click=dlg.close).props('flat no-caps').classes('text-slate-400')
                ui.button('Create', on_click=save_new).classes('btn-primary h-12 rounded-xl px-8')
        dlg.open()

    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        with ui.row().classes('w-full justify-between items-end mb-10'):
            ui.label(_('customers')).classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100')
            ui.button('Add Customer', icon='add_circle', on_click=open_add_customer).classes('btn-primary h-12 rounded-xl px-6')
        container = ui.column().classes('w-full gap-2')
        render_customers(container)

@ui.page('/services')
def services_page():
    inject_premium_styles(); create_menu('/services')

    def is_in_use(service_id: int) -> bool:
        with Session(engine) as s:
            return s.exec(select(InvoiceItem).where(InvoiceItem.service_id == service_id)).first() is not None

    def render_services(container):
        container.clear()
        with Session(engine) as s:
            services = s.exec(select(Service).order_by(Service.name)).all()
        with container:
            with ui.row().classes('w-full px-6 py-2 gap-4'):
                ui.label('NAME').classes('flex-1 text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('DESCRIPTION').classes('flex-1 text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('UNIT PRICE').classes('w-28 text-right text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('STATUS').classes('w-20 text-[11px] font-black text-slate-400 uppercase tracking-widest')
                ui.label('').classes('w-24')  # actions spacer
            for svc in services:
                in_use = is_in_use(svc.id)
                with ui.card().classes('w-full px-6 py-3 premium-card'):
                    display = ui.row().classes('w-full items-center gap-4')
                    edit_row = ui.row().classes('w-full items-center gap-4')
                    edit_row.set_visibility(False)

                    with display:
                        ui.label(svc.name).classes('flex-1 font-semibold' + ('' if svc.is_active else ' line-through text-slate-400'))
                        ui.label(svc.description or '').classes('flex-1 text-slate-500 text-sm truncate')
                        with ui.row().classes('w-28 shrink-0 items-center justify-end'):
                            ui.label(f'${svc.unit_price:,.2f}').classes('font-semibold text-slate-700 dark:text-slate-300')
                        with ui.row().classes('w-20 shrink-0 items-center'):
                            ui.badge('Active' if svc.is_active else 'Inactive',
                                     color='emerald-500' if svc.is_active else 'slate-400').classes('text-xs px-3 py-1')
                        with ui.row().classes('w-24 shrink-0 items-center justify-end gap-1'):
                            def start_edit(d=display, e=edit_row):
                                d.set_visibility(False); e.set_visibility(True)
                            ui.button(icon='edit', on_click=start_edit).props('flat round dense').classes('text-slate-400')

                            def toggle_active(sid=svc.id, active=svc.is_active):
                                with Session(engine) as s:
                                    sv = s.get(Service, sid); sv.is_active = not active
                                    s.add(sv); s.commit()
                                ui.navigate.reload()
                            ui.button(
                                icon='toggle_on' if svc.is_active else 'toggle_off',
                                on_click=toggle_active
                            ).props('flat round dense').classes('text-emerald-500' if svc.is_active else 'text-slate-300')

                            if in_use:
                                ui.icon('link', size='18px').classes('text-slate-300').tooltip('Used in invoices — cannot delete')
                            else:
                                def delete_service(sid=svc.id, sname=svc.name):
                                    with Session(engine) as s:
                                        sv = s.get(Service, sid); s.delete(sv); s.commit()
                                    logger.info(f"Service deleted: {sname}")
                                    ui.notify(f'Service "{sname}" deleted.', color='emerald-500')
                                    ui.navigate.reload()
                                ui.button(icon='delete_outline', on_click=delete_service).props('flat round dense').classes('text-red-300')

                    with edit_row:
                        name_in = ui.input(value=svc.name).props('dense outlined placeholder=Name').classes('flex-1')
                        desc_in = ui.input(value=svc.description or '').props('dense outlined placeholder=Description').classes('flex-1')
                        price_in = ui.number(value=svc.unit_price, min=0).props('dense outlined prefix=$').classes('w-32')

                        def save(sid=svc.id, ni=name_in, di=desc_in, pi=price_in):
                            if not ni.value.strip():
                                ui.notify('Name is required.', color='red-500'); return
                            with Session(engine) as s:
                                sv = s.get(Service, sid)
                                sv.name = ni.value.strip()
                                sv.description = di.value.strip() or None
                                sv.unit_price = pi.value or 0.0
                                s.add(sv); s.commit()
                            logger.info(f"Service {sid} updated: {ni.value}")
                            ui.navigate.reload()

                        def cancel(d=display, e=edit_row):
                            e.set_visibility(False); d.set_visibility(True)

                        ui.button(icon='check', on_click=save).props('flat round dense').classes('text-emerald-600')
                        ui.button(icon='close', on_click=cancel).props('flat round dense').classes('text-slate-400')

    def open_add_service():
        with ui.dialog() as dlg, ui.card().classes('p-8 w-[480px]'):
            ui.label('New Service').classes('text-2xl font-bold mb-6')
            name_in = ui.input('Name').classes('w-full').props('outlined rounded')
            desc_in = ui.input('Description').classes('w-full').props('outlined rounded')
            price_in = ui.number('Unit Price', value=0.0, min=0).classes('w-full').props('outlined rounded prefix=$')

            def save_new():
                if not name_in.value.strip():
                    ui.notify('Name is required.', color='red-500'); return
                with Session(engine) as s:
                    s.add(Service(name=name_in.value.strip(), description=desc_in.value.strip() or None, unit_price=price_in.value or 0.0))
                    s.commit()
                logger.info(f"Service created: {name_in.value}")
                dlg.close(); ui.navigate.reload()

            with ui.row().classes('w-full justify-end gap-3 mt-6'):
                ui.button('Cancel', on_click=dlg.close).props('flat no-caps').classes('text-slate-400')
                ui.button('Create', on_click=save_new).classes('btn-primary h-12 rounded-xl px-8')
        dlg.open()

    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        with ui.row().classes('w-full justify-between items-end mb-10'):
            ui.label(_('services')).classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100')
            ui.button('Add Service', icon='add_circle', on_click=open_add_service).classes('btn-primary h-12 rounded-xl px-6')
        container = ui.column().classes('w-full gap-2')
        render_services(container)

@ui.page('/recurring')
def recurring_page():
    inject_premium_styles(); create_menu('/recurring')
    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        ui.label(_('recurring')).classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-10')
        with ui.card().classes('w-full p-8 premium-card'):
            with Session(engine) as s:
                profiles = s.exec(select(RecurringProfile)).all(); cts = {c.id: c.name for c in s.exec(select(Customer)).all()}
                rows = [{**p.model_dump(), 'cname': cts.get(p.customer_id), 'amt_fmt': f'${p.amount:,.2f}'} for p in profiles]
                ui.table(columns=[{'name':'c','label':_('customers'),'field':'cname','align':'left'},{'name':'a','label':'Amount','field':'amt_fmt','align':'right'}], rows=rows).classes('w-full border-none shadow-none')

def export_accounting_data(format):
    logger.info(f"Exportando datos contables en formato: {format}")
    try:
        with Session(engine) as session:
            data = {'accounts': [a.model_dump() for a in session.exec(select(Account)).all()], 'invoices': [i.model_dump() for i in session.exec(select(Invoice)).all()], 'customers': [c.model_dump() for c in session.exec(select(Customer)).all()]}
            path = f"data/accounting_export.{format}"
            if format == 'json':
                with open(path, 'w') as f: json.dump(data, f, indent=4, default=str)
            logger.info(f"Datos exportados exitosamente a: {path}")
            ui.download(path); ui.notify(f"Data exported to {format.upper()}", color='indigo-600')
    except Exception as e:
        logger.exception(f"Error al exportar datos en formato {format}")
        ui.notify(f'Error al exportar: {e}', color='red-500')

@ui.page('/settings')
def settings_page():
    inject_premium_styles(); create_menu('/settings')
    with Session(engine) as s:
        conf = s.exec(select(CompanySettings)).first()
        if not conf:
            conf = CompanySettings(legal_name="New Business INC.", address="123 Street, City", phone="514-000-0000", email="")
            s.add(conf); s.commit(); s.refresh(conf)
    
    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        ui.label('Settings & Customization').classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-2')
        ui.label('Configure your legal identity and invoice templates.').classes('text-slate-500 mb-10')
        
        with ui.row().classes('w-full gap-8'):
            # Company Settings Card
            with ui.card().classes('flex-1 p-8 premium-card'):
                ui.label('Company Metadata').classes('text-xl font-bold mb-6')
                lname = ui.input('Legal Business Name', value=conf.legal_name).classes('w-full').props('outlined rounded')
                addr = ui.input('Address', value=conf.address).classes('w-full').props('outlined rounded')
                with ui.row().classes('w-full gap-4'):
                    tel = ui.input('Phone', value=conf.phone).classes('flex-1').props('outlined rounded')
                    email = ui.input('Email', value=conf.email).classes('flex-1').props('outlined rounded')
                
                with ui.row().classes('w-full gap-4'):
                    tps = ui.input('GST #', value=conf.tps_number).classes('flex-1').props('outlined rounded')
                    tvq = ui.input('QST #', value=conf.tvq_number).classes('flex-1').props('outlined rounded')

                def save_settings():
                    try:
                        with Session(engine) as s:
                            db_conf = s.get(CompanySettings, conf.id)
                            db_conf.legal_name = lname.value
                            db_conf.address = addr.value
                            db_conf.phone = tel.value
                            db_conf.email = email.value
                            db_conf.tps_number = tps.value
                            db_conf.tvq_number = tvq.value
                            s.add(db_conf); s.commit()
                            logger.info(f"Configuración de empresa actualizada: {lname.value}")
                            ui.notify('Settings saved successfully!', color='emerald-500')
                    except Exception as e:
                        logger.exception("Error al guardar configuración de empresa")
                        ui.notify(f'Error: {e}', color='red-500')
                
                ui.button('Update Metadata', icon='save', on_click=save_settings).classes('btn-primary w-full mt-6 h-14 rounded-2xl')

            # Template Customization Card
            with ui.column().classes('flex-1 gap-8'):
                with ui.card().classes('w-full p-8 premium-card'):
                    ui.label('Invoice HTML Template').classes('text-xl font-bold mb-4')

                    active_label = ui.label(
                        f'Active: {"Custom" if TemplateManager.has_custom_template() else "Default"}'
                    ).classes('text-sm mb-6 ' + ('text-emerald-600 font-semibold' if TemplateManager.has_custom_template() else 'text-slate-400'))

                    with ui.row().classes('w-full gap-4'):
                        def do_export():
                            try:
                                content = TemplateManager.export_fresh_template()
                                from pathlib import Path
                                path = str(Path('data') / 'invoice_template_fresh.html')
                                import os; os.makedirs('data', exist_ok=True)
                                with open(path, 'w') as f: f.write(content)
                                ui.download(path)
                                ui.notify('Default template downloaded!', color='indigo-600')
                            except Exception as e:
                                logger.exception("Error exporting template")
                                ui.notify(f'Error: {e}', color='red-500')

                        def do_reset():
                            try:
                                TemplateManager.reset_template()
                                active_label.text = 'Active: Default'
                                active_label.classes(remove='text-emerald-600 font-semibold', add='text-slate-400')
                                ui.notify('Reverted to default template.', color='indigo-600')
                            except Exception as e:
                                logger.exception("Error resetting template")
                                ui.notify(f'Error: {e}', color='red-500')

                        ui.button('Download Default Template', icon='file_download', on_click=do_export).classes('flex-1 h-14 rounded-2xl border-2 border-indigo-100 text-indigo-600').props('flat')
                        ui.button('Reset to Default', icon='restart_alt', on_click=do_reset).classes('h-14 rounded-2xl border-2 border-red-100 text-red-400').props('flat')

                    ui.separator().classes('my-6')

                    ui.label('Upload Custom Template').classes('text-sm font-bold text-slate-400 uppercase tracking-widest mb-4')

                    async def handle_upload(e):
                        try:
                            content = (await e.file.read()).decode('utf-8')
                            TemplateManager.import_template(content)
                            active_label.text = 'Active: Custom'
                            active_label.classes(remove='text-slate-400', add='text-emerald-600 font-semibold')
                            ui.notify('Custom template uploaded! Open any invoice preview to see it.', color='emerald-500')
                        except Exception as ex:
                            logger.exception("Error importing custom template")
                            ui.notify(f'Error: {ex}', color='red-500')

                    ui.upload(on_upload=handle_upload, label='Upload .html Template').classes('w-full').props('outlined rounded color=indigo-600')

                with ui.card().classes('w-full p-8 premium-card border-2 border-indigo-50'):
                    ui.label('Available Tag References').classes('text-sm font-bold text-slate-400 mb-4')
                    tags = ["{{ vendor_entity }}", "{{ vendor_address }}", "{{ invoice_number }}", "{{ client_entity }}", "{{ line_items }}", "{{ total }}", "{{ balance_due }}"]
                    with ui.row().classes('gap-2'):
                        for t in tags:
                            ui.badge(t, color='indigo-100').classes('text-indigo-600 px-3 py-1 lowercase font-mono')

        # ── AI Receipt Extraction (optional Ollama integration) ──
        with ui.card().classes('w-full p-8 premium-card mt-8'):
            ui.label('AI Receipt Extraction (Optional)').classes('text-xl font-bold mb-2')
            ui.label('Connect a self-hosted Ollama server to auto-fill client expenses from a '
                     'receipt image or PDF. Leave blank to keep entering expenses manually.').classes('text-slate-500 text-sm mb-6')

            ollama_url_input = ui.input('Ollama Server URL', value=conf.ollama_url or '',
                                        placeholder='http://192.168.1.50:11434').classes('w-full').props('outlined rounded')

            initial_models = {conf.ollama_model: conf.ollama_model} if conf.ollama_model else {}
            model_select = ui.select(initial_models, value=conf.ollama_model, label='Model').classes('w-full mt-4').props('outlined rounded')
            ollama_status = ui.label('').classes('text-sm mt-3')
            # Tracks which discovered models can read images (vision-capable).
            vision_map: dict = {}

            async def test_ollama_connection():
                url = (ollama_url_input.value or '').strip()
                if not url:
                    ui.notify('Enter a server URL first', color='amber-500'); return
                ollama_status.classes(replace='text-sm mt-3 text-slate-400')
                ollama_status.set_text('Connecting…')
                try:
                    names = await run.io_bound(list_models, url)
                except Exception as ex:
                    logger.warning(f"Ollama /api/tags failed: {ex}")
                    ollama_status.classes(replace='text-sm mt-3 text-red-500')
                    ollama_status.set_text(f'Could not reach Ollama at {url}.')
                    return
                if not names:
                    ollama_status.classes(replace='text-sm mt-3 text-amber-600')
                    ollama_status.set_text('Connected, but no models are installed on the server.')
                    return
                vision_map.clear()
                options = {}
                for name in names:
                    is_vision = await run.io_bound(probe_model_is_vision, url, name)
                    vision_map[name] = bool(is_vision)
                    options[name] = f'{name}  ✓ vision' if is_vision else f'{name}  — text only (cannot read receipts)'
                model_select.set_options(options)
                vision_count = sum(1 for v in vision_map.values() if v)
                ollama_status.classes(replace='text-sm mt-3 text-emerald-600')
                ollama_status.set_text(f'Connected — {len(names)} model(s), {vision_count} vision-capable. Select one and save.')

            def save_ollama_settings():
                url = (ollama_url_input.value or '').strip() or None
                model = model_select.value or None
                # Block models we know can't read images; vision_map is empty until tested.
                if model and vision_map.get(model) is False:
                    ui.notify('That model cannot read images. Pick a vision-capable model.', color='amber-500'); return
                try:
                    with Session(engine) as s:
                        db_conf = s.get(CompanySettings, conf.id)
                        db_conf.ollama_url = url
                        db_conf.ollama_model = model
                        s.add(db_conf); s.commit()
                    logger.info(f"Ollama settings updated: url={url}, model={model}")
                    ui.notify('AI settings saved!', color='emerald-500')
                except Exception as ex:
                    logger.exception("Error saving Ollama settings")
                    ui.notify(f'Error: {ex}', color='red-500')

            with ui.row().classes('w-full gap-4 mt-6'):
                ui.button('Test Connection', icon='wifi_tethering', on_click=test_ollama_connection).classes('h-14 rounded-2xl border-2 border-indigo-100 text-indigo-600').props('flat')
                ui.button('Save AI Settings', icon='save', on_click=save_ollama_settings).classes('btn-primary h-14 px-8 rounded-2xl ml-auto')


@ui.page('/help')
def help_page():
    inject_premium_styles(); create_menu('/help')
    with ui.column().classes('w-full p-8 max-w-6xl mx-auto animate-fade-in gap-8'):
        with ui.column().classes('gap-2'):
            ui.label('Help').classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight')
            ui.label('A practical guide to the main options in Accounting AI.').classes('text-slate-500 text-lg')

        with ui.column().classes('w-full gap-4'):
            ui.label('Navigation Guide').classes('text-2xl font-bold text-slate-900 dark:text-slate-100')
            rows = [
                {
                    'option': 'Dashboard',
                    'purpose': 'Monitor the current state of the business.',
                    'actions': 'Review paid, awaiting payment, draft totals, client count, monthly revenue, and recent invoices.',
                },
                {
                    'option': 'Invoices',
                    'purpose': 'Create and manage customer invoices.',
                    'actions': 'Add invoices from customers and services, preview them, download PDFs, mark sent, mark paid, write off, or cancel drafts.',
                },
                {
                    'option': 'Subscription',
                    'purpose': 'Review recurring billing profiles.',
                    'actions': 'See recurring customers and amounts; active profiles can generate draft recurring invoices when due.',
                },
                {
                    'option': 'Customers',
                    'purpose': 'Maintain the client list used by invoices.',
                    'actions': 'Add or edit customer names, emails, phone numbers, contact people, and addresses; delete customers only when they are not tied to invoices.',
                },
                {
                    'option': 'Services',
                    'purpose': 'Manage the catalog of billable work.',
                    'actions': 'Add services, set default descriptions and unit prices, edit existing services, toggle active status, and delete unused services.',
                },
                {
                    'option': 'Accounts',
                    'purpose': 'Maintain the chart of accounts.',
                    'actions': 'Add accounts, edit account names and descriptions, activate or deactivate non-system accounts, delete custom accounts, and export JSON data.',
                },
                {
                    'option': 'Expenses',
                    'purpose': 'Track business spending against expense accounts.',
                    'actions': 'Record date, description, account, amount, optional TPS/TVQ, and notes; filter by period and export expenses to CSV.',
                },
                {
                    'option': 'Client Expenses',
                    'purpose': 'Track purchases made on behalf of clients and their reimbursement.',
                    'actions': 'Record reimbursable expenses (optionally auto-filled from a receipt via AI), attach receipts, advance their status to claimed/reimbursed, and attach them to a draft invoice.',
                },
                {
                    'option': 'Reports',
                    'purpose': 'Analyze invoices, taxes, customers, and receivables.',
                    'actions': 'Use period presets or custom dates for sales summary, revenue trend, TPS/TVQ report, income by customer, and aged receivables.',
                },
                {
                    'option': 'Settings',
                    'purpose': 'Configure company identity, invoice templates, and optional AI.',
                    'actions': 'Update legal name, address, phone, email, GST/QST numbers, download the default template, upload custom HTML or reset it, and optionally connect an Ollama server for AI receipt extraction.',
                },
                {
                    'option': 'Help',
                    'purpose': 'Find workflow explanations and status rules.',
                    'actions': 'Review what each sidebar option does and how invoice states should be handled.',
                },
            ]
            ui.table(
                columns=[
                    {'name': 'option', 'label': 'Option', 'field': 'option', 'align': 'left'},
                    {'name': 'purpose', 'label': 'Use It For', 'field': 'purpose', 'align': 'left'},
                    {'name': 'actions', 'label': 'Main Actions', 'field': 'actions', 'align': 'left'},
                ],
                rows=rows,
                row_key='option',
            ).classes('w-full border-none shadow-none')

        with ui.column().classes('w-full gap-3 border-t border-slate-200 dark:border-slate-700 pt-6'):
            ui.label('Sidebar Controls').classes('text-xl font-bold text-slate-900 dark:text-slate-100')
            ui.label('Use the language selector at the bottom of the sidebar to switch between English and Spanish labels. Use the dark mode control to switch the interface theme for your current browser session.').classes('text-slate-600 dark:text-slate-300 leading-relaxed')

        with ui.column().classes('w-full gap-4'):
            ui.label('Standard Workflow').classes('text-2xl font-bold text-slate-900 dark:text-slate-100')
            with ui.row().classes('w-full gap-3 items-center flex-wrap'):
                for label, color in [
                    ('Draft', 'amber'),
                    ('Sent', 'indigo'),
                    ('Paid', 'emerald'),
                ]:
                    ui.badge(label, color=f'{color}-500').classes('px-4 py-2 text-sm font-bold')
                    if label != 'Paid':
                        ui.icon('arrow_forward', size='18px').classes('text-slate-400')
            ui.label('Draft invoices can be reviewed, sent, or cancelled. Once an invoice is sent, it becomes part of your accounting trail and should not be deleted or cancelled. Paid invoices are locked.').classes('text-slate-600 dark:text-slate-300 leading-relaxed')

        with ui.column().classes('w-full gap-4'):
            ui.label('Exception Workflow').classes('text-2xl font-bold text-slate-900 dark:text-slate-100')
            with ui.row().classes('w-full gap-3 items-center flex-wrap'):
                for label, color in [
                    ('Sent', 'indigo'),
                    ('Overdue', 'orange'),
                    ('Written Off', 'slate'),
                ]:
                    ui.badge(label, color=f'{color}-500').classes('px-4 py-2 text-sm font-bold')
                    if label != 'Written Off':
                        ui.icon('arrow_forward', size='18px').classes('text-slate-400')
            ui.label('If a customer does not pay, keep the invoice open as Sent or Overdue while you follow up. If you decide it is uncollectible after recovery efforts, mark it as Written Off. Keep supporting documents for your accountant.').classes('text-slate-600 dark:text-slate-300 leading-relaxed')

        with ui.column().classes('w-full gap-4'):
            ui.label('Status Rules').classes('text-2xl font-bold text-slate-900 dark:text-slate-100')
            rows = [
                {'status': 'Draft', 'meaning': 'Not issued yet.', 'actions': 'Send, cancel.'},
                {'status': 'Sent', 'meaning': 'Issued to the customer.', 'actions': 'Mark paid, write off if uncollectible.'},
                {'status': 'Overdue', 'meaning': 'Sent invoice past its due date.', 'actions': 'Mark paid, write off if uncollectible.'},
                {'status': 'Paid', 'meaning': 'Payment received.', 'actions': 'Locked.'},
                {'status': 'Written Off', 'meaning': 'Unpaid amount abandoned after recovery efforts.', 'actions': 'Locked.'},
                {'status': 'Cancelled', 'meaning': 'Draft abandoned before issue.', 'actions': 'Locked.'},
            ]
            ui.table(
                columns=[
                    {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'left'},
                    {'name': 'meaning', 'label': 'Meaning', 'field': 'meaning', 'align': 'left'},
                    {'name': 'actions', 'label': 'Available Actions', 'field': 'actions', 'align': 'left'},
                ],
                rows=rows,
                row_key='status',
            ).classes('w-full border-none shadow-none')

        with ui.column().classes('w-full gap-4 border-t border-slate-200 dark:border-slate-700 pt-6'):
            ui.label('AI Receipt Extraction (Optional)').classes('text-2xl font-bold text-slate-900 dark:text-slate-100')
            ui.label('Connect a self-hosted Ollama server to read a receipt (image or PDF) and pre-fill a client expense for you. It is fully optional: with no server configured, client expenses work exactly as before.').classes('text-slate-600 dark:text-slate-300 leading-relaxed')
            ai_steps = [
                ('1. Configure', 'In Settings → AI Receipt Extraction, enter your Ollama server URL (e.g. http://sphere-634.local:11434), click Test Connection, choose a vision-capable model (marked ✓ vision), and Save.'),
                ('2. Scan', 'In Client Expenses, an "Auto-fill from receipt" button appears once a server is configured. Upload a photo or PDF of the receipt.'),
                ('3. Review & confirm', 'The vendor, date, amount and taxes are read and pre-filled. Nothing is saved automatically — check every field, then click Add Expense.'),
            ]
            for step_title, step_body in ai_steps:
                with ui.row().classes('w-full gap-3 items-start'):
                    ui.label(step_title).classes('text-sm font-bold text-indigo-600 whitespace-nowrap min-w-36')
                    ui.label(step_body).classes('text-slate-600 dark:text-slate-300 leading-relaxed flex-1')
            ui.label('Notes: the customer is always chosen by you (never read from the receipt). Receipts in a foreign currency are converted to CAD using the receipt date, with the original amount kept in the expense notes. Only vision-capable models can read receipts; text-only models are listed but cannot be used.').classes('text-slate-500 text-sm leading-relaxed mt-2')

        with ui.column().classes('w-full gap-3 border-t border-slate-200 dark:border-slate-700 pt-6'):
            ui.label('Accounting note').classes('text-xl font-bold text-slate-900 dark:text-slate-100')
            ui.label('For tax reporting, credit notes, and bad debt treatment, confirm the final accounting treatment with your accountant. The app protects the invoice trail, but it does not replace professional accounting advice.').classes('text-slate-600 dark:text-slate-300 leading-relaxed')

def generate_due_client_expenses(session, now=None):
    """Create the next instance of each due recurring client expense.

    Time-based (independent of reimbursement status), modeled on the recurring
    invoice pass. The anchor record carries `next_due_date`; when it is reached a
    child is created carrying the chain forward (advanced one calendar month, day
    clamped) and the source's `next_due_date` is cleared so it stops generating.
    Receipts are NOT copied — each cycle's receipt is uploaded fresh.
    """
    now = now or datetime.now()
    due = session.exec(
        select(ClientExpense).where(
            ClientExpense.is_recurring == True,  # noqa: E712
            ClientExpense.next_due_date != None,  # noqa: E711
            ClientExpense.next_due_date <= now,
        )
    ).all()
    created = []
    for src in due:
        period = src.next_due_date
        day = src.recurrence_day or period.day
        child = ClientExpense(
            customer_id=src.customer_id, description=src.description,
            amount=src.amount, tps=src.tps, tvq=src.tvq, total=src.total,
            status="pending", is_recurring=True, recurrence_day=day,
            date=period, next_due_date=advance_recurrence_date(period, day),
            receipt_path=None,
        )
        session.add(child); session.commit(); session.refresh(child)
        session.add(ClientExpenseEvent(client_expense_id=child.id, status="pending"))
        src.next_due_date = None  # hand the anchor to the child
        session.add(src); session.commit()
        created.append(child)
    return created


def transition_client_expense(session, expense_id, target, notes=None, now=None):
    """Advance a client expense to `target`, validating the transition.

    Logs a `ClientExpenseEvent` and updates denormalized dates (`claim_date` on
    →claimed, `reimbursed_date` on →reimbursed). Raises ValueError on an invalid
    transition.
    """
    now = now or utc_now()
    expense = session.get(ClientExpense, expense_id)
    if expense is None:
        raise ValueError("Expense not found")
    if not client_expense_can_transition(expense.status, target):
        raise ValueError(f"Invalid transition: {expense.status} → {target}")

    expense.status = target
    expense.updated_at = now
    if target == "claimed":
        expense.claim_date = now
    elif target == "reimbursed":
        expense.reimbursed_date = now
    session.add(expense)
    session.add(ClientExpenseEvent(client_expense_id=expense.id, status=target, changed_at=now, notes=notes))
    session.commit()
    session.refresh(expense)
    return expense


def delete_client_expenses(session, ids):
    """Delete client expenses and their events. Skips invoice-attached ones.

    Returns {'deleted': int, 'skipped': int, 'deleted_paths': [receipt_path,...]}.
    `deleted_paths` lets the caller clean up receipt files on disk. Expenses
    attached to an invoice are never deleted (would orphan an invoice line).
    """
    deleted = skipped = 0
    deleted_paths = []
    for expense_id in ids:
        expense = session.get(ClientExpense, expense_id)
        if expense is None:
            continue
        if expense.invoice_id is not None:
            skipped += 1
            continue
        events = session.exec(
            select(ClientExpenseEvent).where(ClientExpenseEvent.client_expense_id == expense_id)
        ).all()
        for ev in events:
            session.delete(ev)
        if expense.receipt_path:
            deleted_paths.append(expense.receipt_path)
        session.delete(expense)
        deleted += 1
    session.commit()
    return {'deleted': deleted, 'skipped': skipped, 'deleted_paths': deleted_paths}


def reassign_client_expense_customer(session, expense_id, customer_id):
    """Change the customer of a client expense (used for inline list edits).

    Raises ValueError if the expense does not exist.
    """
    expense = session.get(ClientExpense, expense_id)
    if expense is None:
        raise ValueError("Expense not found")
    expense.customer_id = customer_id
    expense.updated_at = utc_now()
    session.add(expense)
    session.commit()
    session.refresh(expense)
    return expense


def set_client_expense_external_ref(session, expense_id, ref):
    """Set the optional reimbursement reference number on a client expense.

    Used for inline list edits. The value is free text (the same number may be
    reused across several expenses reimbursed together). Blank input clears it to
    NULL. Raises ValueError if the expense does not exist.
    """
    expense = session.get(ClientExpense, expense_id)
    if expense is None:
        raise ValueError("Expense not found")
    cleaned = (ref or "").strip()
    expense.external_ref = cleaned or None
    expense.updated_at = utc_now()
    session.add(expense)
    session.commit()
    session.refresh(expense)
    return expense


def attach_client_expense_to_invoice(session, expense_id, invoice_id):
    """Attach a client expense to a Draft invoice as a non-taxable line.

    The expense `total` is already tax-inclusive, so it is passed through untaxed.
    Non-taxable lines are identified by pointing at the shared "Reimbursable
    Expense" service (existing items all have NULL `tax_rate_id`, so NULL cannot be
    used as the marker). Invoice totals are recomputed over all lines and persisted.
    Raises ValueError if the invoice is not a Draft.
    """
    invoice = session.get(Invoice, invoice_id)
    expense = session.get(ClientExpense, expense_id)
    if invoice is None or expense is None:
        raise ValueError("Invoice or expense not found")
    if invoice.status != "Draft":
        raise ValueError("Reimbursements can only be attached to Draft invoices")

    reimb_svc = get_or_create_reimbursable_service(session)
    session.add(InvoiceItem(
        invoice_id=invoice.id, service_id=reimb_svc.id,
        description=f"Reimbursable expense: {expense.description}",
        quantity=1.0, unit_price=expense.total, total=expense.total,
        tax_rate_id=None,
    ))
    session.commit()

    lines = session.exec(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)).all()
    items = [(line.total, line.service_id != reimb_svc.id) for line in lines]
    invoice.subtotal, invoice.tax_total, invoice.total = compute_invoice_totals(items)
    expense.invoice_id = invoice.id
    expense.updated_at = utc_now()
    session.add(invoice); session.add(expense); session.commit()
    session.refresh(invoice)
    return invoice


def check_recurring():
    try:
        with Session(engine) as s:
            profiles = s.exec(select(RecurringProfile).where(RecurringProfile.is_active==True, RecurringProfile.next_issue_date<=datetime.now())).all()
            if profiles:
                logger.info(f"Procesando {len(profiles)} perfiles recurrentes")
            for p in profiles:
                inv = Invoice(number=f"REC-{datetime.now().strftime('%m%d')}", customer_id=p.customer_id, subtotal=p.amount, total=p.amount*1.14975, status='Draft')
                s.add(inv); s.commit(); p.next_issue_date += timedelta(days=30); s.add(p); s.commit()
                logger.info(f"Factura recurrente creada: #{inv.number}, perfil_id={p.id}")
            generated = generate_due_client_expenses(s)
            if generated:
                logger.info(f"Generados {len(generated)} gastos de cliente recurrentes")
    except Exception as e:
        logger.exception("Error al procesar facturación recurrente")

# --- HTML Invoice Preview Route (opens in new browser tab) ---
@app.get("/preview/{inv_id}")
async def preview_invoice_html(inv_id: int):
    """Serve a fully rendered HTML invoice in a new browser tab."""
    try:
        with Session(engine) as s:
            inv = s.get(Invoice, inv_id)
            if not inv:
                return HTMLResponse("<h1>Invoice not found</h1>", status_code=404)
            cust = s.get(Customer, inv.customer_id)
            items = s.exec(select(InvoiceItem).where(InvoiceItem.invoice_id == inv_id)).all()
            conf = s.exec(select(CompanySettings)).first()
            html_content = TemplateManager.render_invoice(inv, cust, items, conf)
            html_content = TemplateManager.add_print_toolbar(html_content, download_url=f"/download/{inv_id}")
            logger.info(f"HTML preview servido para factura #{inv.number}")
            return HTMLResponse(html_content)
    except Exception as e:
        logger.exception(f"Error al servir preview HTML para factura ID={inv_id}")
        return HTMLResponse(f"<h1>Error</h1><pre>{e}</pre>", status_code=500)


@app.get("/download/{inv_id}")
async def download_invoice_pdf(inv_id: int):
    """Download a real PDF invoice."""
    try:
        with Session(engine) as s:
            inv = s.get(Invoice, inv_id)
            if not inv:
                return HTMLResponse("<h1>Invoice not found</h1>", status_code=404)
            cust = s.get(Customer, inv.customer_id)
            items = s.exec(select(InvoiceItem).where(InvoiceItem.invoice_id == inv_id)).all()
            conf = s.exec(select(CompanySettings)).first()
            pdf_content = build_invoice_pdf(inv, cust, items, conf)
            filename = f"Invoice_{inv.number}_{inv.date.strftime('%Y-%m-%d')}.pdf"
            logger.info(f"PDF descargado para factura #{inv.number}")
            return Response(
                pdf_content,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    except Exception as e:
        logger.exception(f"Error al generar PDF para factura ID={inv_id}")
        return HTMLResponse(f"<h1>Error</h1><pre>{e}</pre>", status_code=500)


if __name__ in {"__main__", "__mp_main__"}:
    from database import create_db_and_tables, seed_initial_data
    logger.info("🚀 Iniciando Accounting AI...")
    logger.info(f"Python PID: {os.getpid()}")
    # Auto-create data directory and database if they don't exist
    os.makedirs("data", exist_ok=True)
    create_db_and_tables()
    seed_initial_data()
    logger.info("✅ Base de datos inicializada correctamente")
    app.on_startup(lambda: ui.timer(60.0, check_recurring))
    show_browser = os.getenv('NICEGUI_SHOW_BROWSER', 'true').lower() == 'true'
    logger.info(f"Servidor en puerto 8081, mostrar_navegador={show_browser}")
    ui.run(title="Accounting AI (Turbo)", port=8081, storage_secret='ultra-secure-key-turbo-inv-final-v2', show=show_browser)
