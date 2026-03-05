import os
from pathlib import Path
from datetime import datetime, timedelta
from jinja2 import Environment, FileSystemLoader
import log_config  # noqa: F401
from loguru import logger

# Resolve paths relative to this file, not the CWD
_APP_DIR = Path(__file__).parent
_PROJECT_ROOT = _APP_DIR.parent

class TemplateManager:
    DEFAULT_TEMPLATE = _APP_DIR / "templates" / "invoice_default.html"
    CUSTOM_TEMPLATE = _PROJECT_ROOT / "data" / "invoice_template_custom.html"

    @staticmethod
    def get_template_path() -> Path:
        """Returns custom template if exists, else default."""
        if TemplateManager.CUSTOM_TEMPLATE.exists():
            logger.debug(f"Using custom template: {TemplateManager.CUSTOM_TEMPLATE}")
            return TemplateManager.CUSTOM_TEMPLATE
        logger.debug(f"Using default template: {TemplateManager.DEFAULT_TEMPLATE}")
        return TemplateManager.DEFAULT_TEMPLATE

    @staticmethod
    def export_fresh_template() -> str:
        """Returns the content of the default template."""
        return TemplateManager.DEFAULT_TEMPLATE.read_text(encoding="utf-8")

    @staticmethod
    def import_template(content: str):
        """Saves a custom template, replacing any previous one."""
        TemplateManager.CUSTOM_TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
        TemplateManager.CUSTOM_TEMPLATE.write_text(content, encoding="utf-8")
        logger.info(f"Custom template saved: {TemplateManager.CUSTOM_TEMPLATE} ({len(content)} chars)")

    @staticmethod
    def reset_template():
        """Removes the custom template so the default is used again."""
        if TemplateManager.CUSTOM_TEMPLATE.exists():
            TemplateManager.CUSTOM_TEMPLATE.unlink()
            logger.info("Custom template removed; reverting to default.")

    @staticmethod
    def has_custom_template() -> bool:
        return TemplateManager.CUSTOM_TEMPLATE.exists()

    @staticmethod
    def render_invoice(invoice, customer, items, vendor_settings) -> str:
        """Renders the HTML invoice using the active template."""
        logger.info(f"Rendering invoice #{invoice.number}")
        try:
            path = TemplateManager.get_template_path()
            env = Environment(
                loader=FileSystemLoader(str(path.parent)),
                autoescape=False,
            )
            template = env.get_template(path.name)

            items_html = ""
            for it in items:
                items_html += f"""
                <tr>
                    <td><div class="item-description">{it.description}</div></td>
                    <td style="text-align: center;">{it.quantity}</td>
                    <td style="text-align: right;">${it.unit_price:,.2f}</td>
                    <td style="text-align: right;">${it.total:,.2f}</td>
                </tr>"""

            context = {
                "invoice_id": invoice.id,
                "invoice_number": invoice.number,
                "status": invoice.status.upper(),
                "vendor_entity": vendor_settings.legal_name if vendor_settings else "Your Legal Name INC.",
                "vendor_address": vendor_settings.address if vendor_settings else "123 Professional Suite, Montréal, QC",
                "vendor_phone": vendor_settings.phone if vendor_settings else "514-000-0000",
                "issue_date": invoice.date.strftime('%Y-%m-%d'),
                "due_date": (invoice.due_date.strftime('%Y-%m-%d') if invoice.due_date else (invoice.date + timedelta(days=30)).strftime('%Y-%m-%d')),
                "currency": vendor_settings.currency if vendor_settings else "CAD",
                "client_entity": customer.name,
                "client_contact": customer.contact or "Billing Dept",
                "client_address": customer.address or "No Address Provided",
                "client_email": customer.email,
                "client_phone": customer.phone or "N/A",
                "line_items": items_html,
                "subtotal": f"${invoice.subtotal:,.2f}",
                "gst": f"${invoice.subtotal * 0.05:,.2f}",
                "qst": f"${invoice.subtotal * 0.09975:,.2f}",
                "total": f"${invoice.total:,.2f}",
                "balance_due": f"${invoice.total:,.2f}" if invoice.status != "Paid" else "$0.00",
                "notes": invoice.notes or "Thank you for your business.",
            }

            result = template.render(**context)
            logger.info(f"Template rendered successfully for invoice #{invoice.number}")
            return result
        except Exception as e:
            logger.exception(f"Error rendering template for invoice #{invoice.number}")
            raise
