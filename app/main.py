from datetime import datetime, timedelta
from nicegui import app, ui
from sqlmodel import Session, select
from starlette.responses import HTMLResponse
from database import engine, Account, TaxRate, AccountType, Customer, Service, Invoice, InvoiceItem, RecurringProfile, CompanySettings
from template_utils import TemplateManager
import log_config  # noqa: F401 — initializes logging on import
from loguru import logger
import os, json, csv

# --- i18n System ---
TRANSLATIONS = {
    'en': {
        'dashboard': 'Dashboard', 'invoices': 'Invoices', 'recurring': 'Subscription',
        'customers': 'Customers', 'services': 'Services', 'accounts': 'Accounts',
        'settings': 'Settings', 'welcome': 'Welcome back, Consultant',
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
        'settings': 'Configuración', 'welcome': 'Bienvenido de nuevo, Consultor',
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
def mark_invoice_as_paid_action(iid):
    logger.info(f"Marcar factura ID={iid} como pagada")
    try:
        with Session(engine) as s:
            inv = s.get(Invoice, iid)
            if inv:
                inv.status = 'Paid'; s.add(inv); s.commit()
                logger.info(f"Factura #{inv.number} marcada como pagada exitosamente")
                ui.notify('Payment registered!', color='emerald-500'); ui.navigate.to('/invoices')
            else:
                logger.warning(f"Factura ID={iid} no encontrada para marcar como pagada")
                ui.notify('Factura no encontrada', color='red-500')
    except Exception as e:
        logger.exception(f"Error al marcar factura ID={iid} como pagada")
        ui.notify(f'Error: {e}', color='red-500')

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
            table.add_slot('body-cell-status', '''<q-td :props="props"><q-badge :color="props.row.status == 'Paid' ? 'emerald-500' : (props.row.status == 'Overdue' ? 'red-500' : 'slate-400')" :style="{padding:'8px 16px',borderRadius:'100px',fontWeight:'700',fontSize:'10px'}">{{ props.row.status }}</q-badge></q-td>''')
            table.add_slot('body-cell-actions', '''<q-td :props="props"><q-btn flat round icon="visibility" @click="$parent.$emit('preview', props.row.id)" /><q-btn flat round color="indigo-600" icon="print" @click="$parent.$emit('print', props.row.id)" /><q-btn v-if="props.row.status !== 'Paid'" flat round color="emerald-500" icon="check" @click="$parent.$emit('paid', props.row.id)" /></q-td>''')
            table.on('preview', lambda e: open_invoice_preview(e.args)); table.on('paid', lambda e: mark_invoice_as_paid_action(e.args)); table.on('print', lambda e: ui.run_javascript(f'window.open("/preview/{e.args}", "_blank")'))

@ui.page('/')
def dashboard_page():
    logger.debug("Cargando página: / (dashboard)")
    inject_premium_styles(); create_menu('/')
    with Session(engine) as s: invs = s.exec(select(Invoice)).all()
    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        ui.label(_('welcome')).classes('text-5xl font-extrabold text-slate-900 dark:text-slate-100 mb-2')
        ui.label('Consultant AI - Real-time Insight').classes('text-slate-400 text-xl font-medium mb-16')
        with ui.row().classes('w-full gap-8 mb-16'):
            for label, border, icon, color, val in [(_('overdue'),'stat-overdue','error','red-500',sum(i.total for i in invs if i.status=='Overdue')),(_('draft'),'stat-pending','history_toggle_off','amber-500',sum(i.total for i in invs if i.status=='Draft')),(_('paid'),'stat-paid','auto_awesome','emerald-500',sum(i.total for i in invs if i.status=='Paid'))]:
                with ui.card().classes(f'flex-1 p-10 premium-card {border} flex justify-center'):
                    with ui.row().classes('items-center gap-4 w-full mb-6'): ui.icon(icon, color=color, size='32px'); ui.label(label).classes('text-[10px] font-black text-slate-400 uppercase tracking-widest')
                    ui.label(f'${val:,.2f}').classes('text-5xl font-black text-slate-900 dark:text-slate-100')
        with ui.row().classes('w-full gap-8'):
            with ui.column().classes('flex-[2] gap-6'):
                ui.label(_('recent_activity')).classes('text-2xl font-bold text-slate-800 dark:text-slate-200')
                with ui.card().classes('w-full p-0 premium-card h-96 overflow-hidden'): ui.table(columns=[{'name':'n','field':'number','label':'#'},{'name':'t','field':'total','label':'Total'}], rows=[{'number':i.number,'total':f'${i.total:,.2f}'} for i in invs[:8]]).classes('w-full border-none shadow-none')
            with ui.column().classes('flex-1 gap-6'):
                ui.label(_('cashflow')).classes('text-2xl font-bold text-slate-800 dark:text-slate-200')
                with ui.card().classes('w-full p-10 premium-card h-96 flex items-center justify-center bg-indigo-50 dark:bg-slate-800'): ui.icon('monitoring', size='64px', color='indigo-200'); ui.label('Analytics ready in Phase 5').classes('text-slate-400 mt-6 italic')

@ui.page('/accounts')
def accounts_page():
    inject_premium_styles(); create_menu('/accounts')
    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        with ui.row().classes('w-full justify-between items-end mb-10'):
            ui.label(_('accounts')).classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100')
            with ui.row().classes('gap-3'):
                ui.button('JSON', icon='download', on_click=lambda: export_accounting_data('json')).classes('btn-primary h-12 rounded-xl')
        with ui.card().classes('w-full p-0 premium-card overflow-hidden'):
            with Session(engine) as s: ui.table(columns=[{'name':'c','label':'CODE','field':'code','align':'left'},{'name':'n','label':'NAME','field':'name','align':'left'}], rows=[a.model_dump() for a in s.exec(select(Account)).all()]).classes('w-full border-none shadow-none')

@ui.page('/customers')
def customers_page():
    inject_premium_styles(); create_menu('/customers')
    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        ui.label(_('customers')).classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-10')
        with ui.card().classes('w-full p-0 premium-card overflow-hidden'):
             with Session(engine) as s: ui.table(columns=[{'name':'n','field':'name','label':'NAME','align':'left'},{'name':'e','field':'email','label':'EMAIL','align':'left'}], rows=[c.model_dump() for c in s.exec(select(Customer)).all()]).classes('w-full border-none shadow-none')

@ui.page('/services')
def services_page():
    inject_premium_styles(); create_menu('/services')
    with ui.column().classes('w-full p-8 max-w-7xl mx-auto animate-fade-in'):
        ui.label(_('services')).classes('text-4xl font-extrabold text-slate-900 dark:text-slate-100 mb-10')
        with ui.card().classes('w-full p-0 premium-card overflow-hidden'):
             with Session(engine) as s: ui.table(columns=[{'name':'n','field':'name','label':'NAME','align':'left'},{'name':'p','field':'unit_price','label':'PRICE','align':'right'}], rows=[ser.model_dump() for ser in s.exec(select(Service)).all()]).classes('w-full border-none shadow-none')

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

                    def handle_upload(e):
                        try:
                            content = e.content.read().decode('utf-8')
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
