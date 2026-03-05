from datetime import datetime, timedelta
from nicegui import app, ui
from sqlmodel import Session, select
from starlette.responses import HTMLResponse
from database import engine, Account, TaxRate, AccountType, Customer, Service, Invoice, InvoiceItem, RecurringProfile, CompanySettings, Expense
from template_utils import TemplateManager
import log_config  # noqa: F401 — initializes logging on import
from loguru import logger
import os, json, csv
import plotly.graph_objects as go
from collections import defaultdict

# --- i18n System ---
TRANSLATIONS = {
    'en': {
        'dashboard': 'Dashboard', 'invoices': 'Invoices', 'recurring': 'Subscription',
        'customers': 'Customers', 'services': 'Services', 'accounts': 'Accounts',
        'reports': 'Reports', 'expenses': 'Expenses', 'settings': 'Settings', 'welcome': 'Welcome back, Consultant',
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
        'reports': 'Reportes', 'expenses': 'Gastos', 'settings': 'Configuración', 'welcome': 'Bienvenido de nuevo, Consultor',
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
                    ('/reports', 'bar_chart', 'Reports'),
                    ('/settings', 'settings', 'Settings'),
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
                with ui.row().classes('w-full justify-between'):
                    ui.label('TPS (5%)').classes('text-slate-500'); ui.label(f'${inv.subtotal * 0.05:,.2f}')
                with ui.row().classes('w-full justify-between'):
                    ui.label('TVQ (9.975%)').classes('text-slate-500'); ui.label(f'${inv.subtotal * 0.09975:,.2f}')
                with ui.row().classes('w-full justify-between pt-4 border-t border-slate-200 mt-2'):
                    ui.label(_('grand_total')).classes('text-xl font-black text-indigo-600')
                    ui.label(f'${inv.total:,.2f}').classes('text-xl font-black text-indigo-600')
        with ui.row().classes('w-full justify-center p-6 gap-4'):
            ui.button('Close', on_click=d.close).props('flat text-color=white')
            ui.button('Print / Save PDF', icon='print', on_click=lambda: ui.run_javascript(f'window.open("/preview/{inv.id}", "_blank")')).classes('btn-primary')
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
    _update_invoice_status(iid, 'Paid', 'Payment registered!', 'emerald-500')

def mark_invoice_as_cancelled_action(iid):
    _update_invoice_status(iid, 'Cancelled', 'Invoice cancelled.', 'red-500')

# --- Pages ---
@ui.page('/invoices')
def invoices_page():
    logger.debug("Cargando página: /invoices")
    inject_premium_styles(); create_menu('/invoices')
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
                    sub = sum((i['q'].value or 0) * (i['p'].value or 0) for i in line_items if i['s'].value)
                    tax = sub * 0.14975
                    if 'sub' in totals_labels: totals_labels['sub'].text = f'${sub:,.2f}'
                    if 'tax' in totals_labels: totals_labels['tax'].text = f'${tax:,.2f}'
                    if 'tot' in totals_labels: totals_labels['tot'].text = f'${(sub + tax):,.2f}'

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
                            sub = sum((i['q'].value * i['p'].value) for i in line_items if i['s'].value)
                            inv = Invoice(number=f"INV-{datetime.now().strftime('%m%d%H%M')}", customer_id=c_sel.value, date=datetime.strptime(i_date.value, '%Y-%m-%d'), subtotal=sub, tax_total=sub*0.14975, total=sub*1.14975, status='Draft')
                            s.add(inv); s.commit(); s.refresh(inv)
                            for i in line_items:
                                if i['s'].value: s.add(InvoiceItem(invoice_id=inv.id, service_id=i['s'].value, description=next(ser.name for ser in services if ser.id == i['s'].value), quantity=i['q'].value, unit_price=i['p'].value, total=i['q'].value*i['p'].value))
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

        with ui.card().classes('w-full p-0 overflow-hidden premium-card'):
            cols = [{'name':'num','label':'#','field':'number','align':'left'},{'name':'cust','label':_('customers'),'field':'cname','align':'left'},{'name':'status','label':'Status','field':'status','align':'center'},{'name':'total','label':'Total','field':'total_fmt','align':'right'},{'name':'actions','label':'','field':'id','align':'right'}]
            rows = [{**i.model_dump(), 'cname': next((c.name for c in customers if c.id == i.customer_id), '?'), 'total_fmt': f'${i.total:,.2f}'} for i in invoices]
            table = ui.table(columns=cols, rows=rows, row_key='id').classes('w-full border-none shadow-none')
            table.add_slot('body-cell-status', '''<q-td :props="props"><q-badge :color="props.row.status === 'Paid' ? 'emerald-500' : (props.row.status === 'Sent' ? 'indigo-500' : (props.row.status === 'Cancelled' ? 'red-500' : 'amber-500'))" :style="{padding:'8px 16px',borderRadius:'100px',fontWeight:'700',fontSize:'10px'}">{{ props.row.status }}</q-badge></q-td>''')
            table.add_slot('body-cell-actions', '''<q-td :props="props"><q-btn flat round icon="visibility" @click="$parent.$emit('preview', props.row.id)" /><q-btn flat round color="indigo-600" icon="print" @click="$parent.$emit('print', props.row.id)" /><q-btn v-if="props.row.status === 'Draft'" flat round color="indigo-400" icon="send" title="Mark as Sent" @click="$parent.$emit('sent', props.row.id)" /><q-btn v-if="props.row.status === 'Sent'" flat round color="emerald-500" icon="check" title="Mark as Paid" @click="$parent.$emit('paid', props.row.id)" /><q-btn v-if="props.row.status !== 'Paid' && props.row.status !== 'Cancelled'" flat round color="red-300" icon="cancel" title="Cancel invoice" @click="$parent.$emit('cancel', props.row.id)" /></q-td>''')
            table.on('preview', lambda e: open_invoice_preview(e.args)); table.on('sent', lambda e: mark_invoice_as_sent_action(e.args)); table.on('paid', lambda e: mark_invoice_as_paid_action(e.args)); table.on('cancel', lambda e: mark_invoice_as_cancelled_action(e.args)); table.on('print', lambda e: ui.run_javascript(f'window.open("/preview/{e.args}", "_blank")'))

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
        tps = round(amount * TPS_RATE, 2) if apply_tps else 0.0
        tvq = round(amount * TVQ_RATE, 2) if apply_tvq else 0.0
        return tps, tvq, round(amount + tps + tvq, 2)

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

        with ui.card().classes('w-full p-4 premium-card mb-4'):
            with ui.row().classes('items-center gap-3 flex-wrap'):
                ui.label('Period:').classes('text-sm font-semibold text-slate-500 mr-2')
                for name in PRESETS:
                    is_active = name == 'This Month'
                    cls = 'btn-primary h-9 rounded-lg px-4 text-sm' if is_active else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                    btn = ui.button(name, on_click=lambda n=name: set_expense_preset(n)).classes(cls)
                    preset_btns[name] = btn

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
        container.clear()
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
            with ui.row().classes('w-full gap-4 mb-4'):
                for bucket, invs in buckets.items():
                    total = sum(i.total for i in invs)
                    color = bucket_colors[bucket]
                    with ui.card().classes('flex-1 p-4 bg-slate-50 dark:bg-slate-800 rounded-xl'):
                        ui.label(bucket).classes(f'text-[10px] font-black text-{color} uppercase tracking-widest mb-1')
                        ui.label(f'${total:,.2f}').classes('text-xl font-black text-slate-900 dark:text-slate-100')
                        ui.label(f'{len(invs)} invoice{"s" if len(invs) != 1 else ""}').classes('text-xs text-slate-400')

            if not unpaid:
                with ui.column().classes('w-full items-center p-8'):
                    ui.icon('check_circle', size='40px', color='emerald-400')
                    ui.label('No outstanding invoices').classes('text-slate-400 text-sm mt-2')
                return

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
        render_aged_receivables(aged_content, all_invoices)

    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        ui.label('Reports').classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-2')
        ui.label('Financial reports for any period').classes('text-slate-400 text-base mb-6')

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
                    apply_filter()
                else:
                    custom_row.set_visibility(True)

            with ui.row().classes('items-center gap-3 flex-wrap'):
                ui.label('Period:').classes('text-sm font-semibold text-slate-500 mr-2')
                for name in PRESETS:
                    is_active = name == state['preset']
                    cls = 'btn-primary h-9 rounded-lg px-4 text-sm' if is_active else 'h-9 rounded-lg px-4 text-sm bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                    btn = ui.button(name, on_click=lambda n=name: set_preset(n)).classes(cls)
                    preset_btns[name] = btn

            with ui.row().classes('items-center gap-4 mt-3') as custom_row:
                custom_row.set_visibility(False)
                from_input = ui.input('From', value=state['from'].strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                to_input   = ui.input('To',   value=state['to'].strftime('%Y-%m-%d')).props('dense outlined').classes('w-40')
                def apply_custom():
                    try:
                        state['from'] = datetime.strptime(from_input.value, '%Y-%m-%d')
                        state['to']   = datetime.strptime(to_input.value,   '%Y-%m-%d')
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
            conf = CompanySettings(legal_name="New Business INC.", address="123 Street, City", phone="514-000-0000")
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
                tel = ui.input('Phone', value=conf.phone).classes('w-full').props('outlined rounded')
                
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
            logger.info(f"HTML preview servido para factura #{inv.number}")
            return HTMLResponse(html_content)
    except Exception as e:
        logger.exception(f"Error al servir preview HTML para factura ID={inv_id}")
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
