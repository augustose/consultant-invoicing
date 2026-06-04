from io import BytesIO
from datetime import timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_ARIAL = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
_ARIAL_BOLD = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")

if _ARIAL.exists() and _ARIAL_BOLD.exists():
    pdfmetrics.registerFont(TTFont("InvoiceArial", str(_ARIAL)))
    pdfmetrics.registerFont(TTFont("InvoiceArial-Bold", str(_ARIAL_BOLD)))
    _FONT = "InvoiceArial"
    _FONT_BOLD = "InvoiceArial-Bold"


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _due_date_text(invoice) -> str:
    due_date = invoice.due_date or (invoice.date + timedelta(days=30))
    return due_date.strftime("%Y-%m-%d")


def _quantity(value) -> str:
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return str(value)


def _draw_text_block(pdf, text, x, y, size=11, leading=14, bold_first=False):
    for index, line in enumerate(str(text or "").splitlines()):
        pdf.setFont(_FONT_BOLD if bold_first and index == 0 else _FONT, size)
        pdf.drawString(x, y, line)
        y -= leading
    return y


def _draw_wrapped(pdf, text, x, y, width, style):
    paragraph = Paragraph(str(text or "").replace("\n", "<br/>"), style)
    _, height = paragraph.wrap(width, 1.5 * inch)
    paragraph.drawOn(pdf, x, y - height)
    return y - height


def build_invoice_pdf(invoice, customer, items, vendor_settings) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    page_width, page_height = letter
    currency = getattr(vendor_settings, "currency", "CAD") or "CAD"

    subtotal = float(invoice.subtotal)
    gst = subtotal * 0.05
    qst = subtotal * 0.09975
    total = float(invoice.total)
    balance_due = 0.0 if invoice.status == "Paid" else total

    # Header
    pdf.setFillColor(colors.HexColor("#414141"))
    pdf.rect(0, page_height - 1.35 * inch, page_width * 0.67, 1.35 * inch, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#777777"))
    pdf.rect(page_width * 0.67, page_height - 1.35 * inch, page_width * 0.33, 1.35 * inch, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont(_FONT, 31)
    pdf.drawString(0.35 * inch, page_height - 0.82 * inch, "INVOICE")
    pdf.setFont(_FONT, 14)
    pdf.drawCentredString(page_width * 0.835, page_height - 0.48 * inch, f"Amount Due ({currency})")
    pdf.setFont(_FONT, 30)
    pdf.drawCentredString(page_width * 0.835, page_height - 0.93 * inch, _money(balance_due))

    # Bill-to and metadata
    y = page_height - 2.1 * inch
    pdf.setFillColor(colors.HexColor("#9aa1a7"))
    pdf.setFont(_FONT_BOLD, 11)
    pdf.drawString(0.35 * inch, y, "BILL TO")
    pdf.setFillColor(colors.HexColor("#4f565d"))
    y -= 15
    pdf.setFont(_FONT_BOLD, 11)
    pdf.drawString(0.35 * inch, y, customer.name)
    y -= 14
    y = _draw_text_block(pdf, f"{customer.contact}\n{customer.address}\n\n{customer.phone}\n{customer.email}", 0.35 * inch, y, size=11)

    meta_x = 4.45 * inch
    meta_y = page_height - 2.1 * inch
    meta_rows = [
        ("Invoice Number:", invoice.number),
        ("Invoice Date:", invoice.date.strftime("%Y-%m-%d")),
        ("Payment Due:", _due_date_text(invoice)),
        (f"Amount Due ({currency}):", _money(balance_due)),
    ]
    for label, value in meta_rows:
        pdf.setFont(_FONT_BOLD, 11)
        pdf.drawRightString(meta_x + 1.6 * inch, meta_y, label)
        pdf.setFont(_FONT, 11)
        pdf.drawString(meta_x + 1.75 * inch, meta_y, str(value))
        meta_y -= 24

    # Items header
    table_y = page_height - 4.25 * inch
    pdf.setFillColor(colors.HexColor("#b2b8bc"))
    pdf.setFont(_FONT_BOLD, 11)
    pdf.drawString(0.35 * inch, table_y, "ITEMS")
    pdf.drawCentredString(4.65 * inch, table_y, "QUANTITY")
    pdf.drawRightString(6.35 * inch, table_y, "PRICE")
    pdf.drawRightString(7.85 * inch, table_y, "AMOUNT")
    pdf.setStrokeColor(colors.HexColor("#dddddd"))
    pdf.line(0, table_y - 12, page_width, table_y - 12)

    # Items
    row_top = table_y - 12
    row_height = 0.95 * inch
    pdf.setFillColor(colors.HexColor("#f2f2f2"))
    pdf.rect(0, row_top - row_height, page_width, row_height, fill=1, stroke=0)
    item_y = row_top - 24
    style = ParagraphStyle("item", fontName=_FONT, fontSize=11, leading=14, textColor=colors.HexColor("#4f565d"))
    for item in items:
        lines = str(item.description).splitlines()
        pdf.setFillColor(colors.HexColor("#4f565d"))
        pdf.setFont(_FONT_BOLD, 11)
        pdf.drawString(0.35 * inch, item_y, lines[0] if lines else "")
        if len(lines) > 1:
            _draw_wrapped(pdf, "\n".join(lines[1:]), 0.35 * inch, item_y - 16, 3.2 * inch, style)
        pdf.setFont(_FONT, 11)
        pdf.drawCentredString(4.65 * inch, item_y, _quantity(item.quantity))
        pdf.drawRightString(6.35 * inch, item_y, _money(item.unit_price))
        pdf.drawRightString(7.85 * inch, item_y, _money(item.total))
        break
    pdf.setStrokeColor(colors.HexColor("#dddddd"))
    pdf.line(0, row_top - row_height, page_width, row_top - row_height)

    # Totals
    totals_y = row_top - row_height - 0.45 * inch
    totals = [
        ("Subtotal:", _money(subtotal), True),
        (f"GST 5% ({vendor_settings.tps_number}):", _money(gst), False),
        (f"QST 9.975% ({vendor_settings.tvq_number}):", _money(qst), False),
        ("Total:", _money(total), True),
        (f"Amount Due ({currency}):", _money(balance_due), True),
    ]
    for index, (label, value, bold) in enumerate(totals):
        if index in {3, 4}:
            pdf.setStrokeColor(colors.HexColor("#dddddd"))
            pdf.line(3.9 * inch, totals_y + 12, 7.85 * inch, totals_y + 12)
        pdf.setFont(_FONT_BOLD if bold else _FONT, 11)
        pdf.drawRightString(6.4 * inch, totals_y, label)
        pdf.drawRightString(7.85 * inch, totals_y, value)
        totals_y -= 26

    # Notes
    notes_y = 1.55 * inch
    pdf.setFillColor(colors.HexColor("#4f565d"))
    pdf.setFont(_FONT_BOLD, 11)
    pdf.drawString(0.35 * inch, notes_y, "Notes / Terms")
    pdf.setFont(_FONT, 11)
    pdf.drawString(0.35 * inch, notes_y - 18, invoice.notes or "Thank you for your business.")

    # Footer
    pdf.setStrokeColor(colors.HexColor("#dddddd"))
    pdf.line(0.35 * inch, 0.92 * inch, page_width - 0.35 * inch, 0.92 * inch)
    pdf.setFillColor(colors.HexColor("#f8f8f3"))
    pdf.rect(0.65 * inch, 0.25 * inch, 0.65 * inch, 0.65 * inch, fill=1, stroke=1)
    pdf.setFillColor(colors.HexColor("#2f3740"))
    pdf.setFont(_FONT_BOLD, 18)
    pdf.drawCentredString(0.975 * inch, 0.52 * inch, "ASE")
    pdf.setFillColor(colors.black)
    _draw_text_block(pdf, f"{vendor_settings.legal_name}\n{vendor_settings.address}", 1.9 * inch, 0.72 * inch, size=9, leading=11, bold_first=True)
    pdf.setFont(_FONT_BOLD, 9)
    pdf.drawRightString(7.85 * inch, 0.68 * inch, "Contact Information")
    pdf.setFont(_FONT, 9)
    pdf.drawRightString(7.85 * inch, 0.55 * inch, vendor_settings.phone or "")
    pdf.drawRightString(7.85 * inch, 0.42 * inch, getattr(vendor_settings, "email", "") or "")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
