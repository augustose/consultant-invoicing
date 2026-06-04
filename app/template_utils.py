import os
from html import escape
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
    def add_print_toolbar(html_content: str, download_url: str = "") -> str:
        """Adds a browser toolbar that is hidden from printed output."""
        download_href = download_url or "#"
        toolbar = """
        <style>
            .print-toolbar {
                position: sticky;
                top: 0;
                z-index: 9999;
                display: flex;
                justify-content: center;
                gap: 12px;
                padding: 12px;
                background: #f8fafc;
                border-bottom: 1px solid #e2e8f0;
                font-family: Arial, Helvetica, sans-serif;
            }
            .print-toolbar a,
            .print-toolbar button {
                border: 0;
                border-radius: 6px;
                background: #414141;
                color: #ffffff;
                cursor: pointer;
                display: inline-block;
                font-size: 14px;
                font-weight: 700;
                padding: 10px 16px;
                text-decoration: none;
            }
            .print-toolbar button.secondary {
                background: #777777;
            }
            @media print {
                .print-toolbar { display: none; }
            }
        </style>
        <div class="print-toolbar">
            <a href="__DOWNLOAD_HREF__" target="_blank" rel="noopener">Download PDF</a>
            <button type="button" class="secondary" onclick="window.print()">Print</button>
            <button type="button" class="secondary" onclick="window.close()">Close</button>
        </div>
        """.replace("__DOWNLOAD_HREF__", download_href)
        if "<body>" in html_content:
            return html_content.replace("<body>", f"<body>{toolbar}", 1)
        return f"{toolbar}{html_content}"

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
                description_lines = str(it.description).splitlines()
                title = escape(description_lines[0]) if description_lines else ""
                detail = "<br>".join(escape(line) for line in description_lines[1:])
                description = title
                if detail:
                    description += f'<div class="item-detail">{detail}</div>'
                items_html += f"""
                <tr>
                    <td><div class="item-description">{description}</div></td>
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
                "vendor_email": vendor_settings.email if vendor_settings and getattr(vendor_settings, "email", None) else "",
                "gst_number": vendor_settings.tps_number if vendor_settings and vendor_settings.tps_number else "",
                "qst_number": vendor_settings.tvq_number if vendor_settings and vendor_settings.tvq_number else "",
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
