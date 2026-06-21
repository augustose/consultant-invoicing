"""Optional Ollama-powered receipt extraction for client expenses.

This module is intentionally free of NiceGUI / DB imports so its logic can be
unit-tested in isolation. HTTP and filesystem boundaries are injected, so tests
never need a live Ollama server or network access.

See docs/plans/2026-06-20-ollama-receipt-extraction-design.md for the design.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime
from typing import Optional

FRANKFURTER_BASE = "https://api.frankfurter.app"


def _default_http_get_json(url: str, timeout: float = 10.0) -> dict:
    """Minimal GET → parsed JSON using the stdlib (no extra dependency)."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _default_http_post_json(url: str, payload: dict, timeout: float = 60.0) -> dict:
    """Minimal POST(JSON) → parsed JSON using the stdlib (no extra dependency)."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _to_float(value, default: float = 0.0) -> float:
    """Coerce a model-supplied number (which may be a string) to float."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        # Tolerate currency symbols, thousands separators and stray spaces.
        cleaned = (
            str(value)
            .replace("$", "")
            .replace("€", "")
            .replace("£", "")
            .replace(",", "")
            .strip()
        )
        return float(cleaned)
    except (TypeError, ValueError):
        return default


# Date formats accepted from receipts, tried in order. Day-first (%d/%m/%Y) is
# tried before month-first so unambiguous Québec/European dates win; ambiguous
# all-numeric dates fall back to month-first only when day-first is invalid.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
)


def parse_receipt_date(value: Optional[str]) -> Optional[datetime]:
    """Parse a receipt date string into a datetime, or None if unparseable."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


# Québec sales-tax rates (kept local so this module stays DB-import-free).
QC_TPS_RATE = 0.05
QC_TVQ_RATE = 0.09975
QC_COMBINED_RATE = QC_TPS_RATE + QC_TVQ_RATE  # 0.14975


def split_qc_tax(tax_total) -> tuple:
    """Split a combined Québec tax amount into (TPS, TVQ) by the standard ratio.

    Works whether the receipt itemized TPS/TVQ separately or charged the single
    combined 14.975% line — both sum to the same total and split the same way.
    """
    amount = _to_float(tax_total)
    if not amount:
        return 0.0, 0.0
    return (amount * QC_TPS_RATE / QC_COMBINED_RATE,
            amount * QC_TVQ_RATE / QC_COMBINED_RATE)


def frankfurter_rate_provider(
    currency: str,
    on_date: Optional[datetime],
    *,
    http_get_json=_default_http_get_json,
) -> Optional[float]:
    """Return the CAD-per-`currency` rate, or None if it can't be fetched.

    Uses frankfurter.app (free, no API key, ECB daily rates). `on_date` selects
    the historical rate (the receipt date); None uses the latest rate. CAD is an
    identity with no network call. Any failure returns None so callers can fall
    back to manual entry rather than blocking.
    """
    if not currency or currency.upper() == "CAD":
        return 1.0
    cur = currency.upper()
    path = on_date.strftime("%Y-%m-%d") if on_date else "latest"
    url = f"{FRANKFURTER_BASE}/{path}?from={cur}&to=CAD"
    try:
        data = http_get_json(url)
        rate = data.get("rates", {}).get("CAD")
        return float(rate) if rate is not None else None
    except Exception:
        return None


def map_extraction_to_expense(parsed: dict, *, rate_provider=frankfurter_rate_provider) -> dict:
    """Turn a parsed receipt into form-ready ClientExpense values.

    Returns a dict with: description, date (datetime|None), amount, tps, tvq,
    total (all CAD), currency, notes (str), warnings (list[str]). Amounts are
    never auto-saved — these only pre-fill the form for user confirmation.
    """
    parsed = parsed or {}
    warnings: list[str] = []
    notes_parts: list[str] = []

    vendor = str(parsed.get("vendor") or "").strip()
    description = vendor or "Expense from receipt"
    date = parse_receipt_date(parsed.get("date"))

    amount = _to_float(parsed.get("subtotal"))      # pre-tax
    tax_total = _to_float(parsed.get("tax_total"))
    total = _to_float(parsed.get("total"))

    # Reconstruct any one missing figure from the other two (subtotal + tax = total).
    if not total and (amount or tax_total):
        total = amount + tax_total
    if not amount and total:
        amount = total - tax_total

    currency = str(parsed.get("currency") or "CAD").strip().upper() or "CAD"
    if currency != "CAD":
        rate = rate_provider(currency, date)
        if rate is not None:
            amount, tax_total, total = (v * rate for v in (amount, tax_total, total))
            rate_day = date.strftime("%Y-%m-%d") if date else "latest"
            notes_parts.append(
                f"Converted from {currency} · rate {rate:g} CAD/{currency} "
                f"@ {rate_day} (frankfurter.app)"
            )
        else:
            notes_parts.append(f"Currency: {currency} (not converted)")
            warnings.append(
                f"Couldn't fetch exchange rate — amounts are in {currency}, "
                "please convert/enter manually."
            )

    # Québec receipts: split the combined tax into TPS/TVQ. Foreign receipts have
    # no QC columns, so leave tps/tvq at 0 and note the foreign tax (in CAD).
    if currency == "CAD":
        tps, tvq = split_qc_tax(tax_total)
    else:
        tps, tvq = 0.0, 0.0
        if tax_total:
            notes_parts.append(f"Foreign tax (converted): {tax_total:.2f} CAD")

    if total and not tax_total:
        warnings.append("No tax detected — verify the tax amount.")
    if date is None:
        warnings.append("Date not detected — please enter it.")

    return {
        "description": description,
        "date": date,
        "amount": round(amount, 2),
        "tps": round(tps, 2),
        "tvq": round(tvq, 2),
        "total": round(total, 2),
        "currency": currency,
        "notes": " · ".join(notes_parts),
        "warnings": warnings,
    }


# --- Ollama HTTP boundary ------------------------------------------------

# JSON schema requested from Ollama so the model returns structured data, not
# prose. `null` is allowed everywhere so the model never has to invent a value.
RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor": {"type": ["string", "null"]},
        "date": {"type": ["string", "null"]},
        "subtotal": {"type": ["number", "null"]},
        "tax_total": {"type": ["number", "null"]},
        "total": {"type": ["number", "null"]},
        "currency": {"type": ["string", "null"]},
    },
}

RECEIPT_PROMPT = (
    "You are extracting data from a single purchase receipt or invoice. "
    "Return only values that are printed; use null when something is not present. "
    "Do not guess.\n"
    "- vendor: the business that ISSUED the invoice (the seller / company at the "
    "top, e.g. next to the logo). This is NOT the 'Bill to' / 'Sold to' customer.\n"
    "- date: the invoice or purchase date (date of issue).\n"
    "- subtotal: the pre-tax amount (often labelled 'Subtotal' or 'Total "
    "excluding tax').\n"
    "- tax_total: the total of ALL taxes charged. If TPS/GST and TVQ/QST are "
    "listed separately, add them; if a single combined tax line is shown, use it.\n"
    "- total: the final grand total actually due (often labelled 'Total' or "
    "'Amount due'), taxes included.\n"
    "- currency: the ISO currency code (CAD, USD, EUR, …). 'CA$' or 'C$' means CAD; "
    "a plain '$' on a Canadian invoice usually means CAD."
)


def parse_models_response(tags_json: dict) -> list:
    """Extract model names from an Ollama /api/tags response."""
    models = (tags_json or {}).get("models") or []
    return [m["name"] for m in models if isinstance(m, dict) and m.get("name")]


def list_models(base_url: str, *, http_get_json=_default_http_get_json) -> list:
    """Fetch the list of installed model names from an Ollama server."""
    url = f"{base_url.rstrip('/')}/api/tags"
    return parse_models_response(http_get_json(url))


def probe_model_is_vision(
    base_url: str, model: str, *, http_post_json=_default_http_post_json
) -> Optional[bool]:
    """Return True/False if `model` is vision-capable, or None if unreachable."""
    url = f"{base_url.rstrip('/')}/api/show"
    try:
        data = http_post_json(url, {"model": model})
    except Exception:
        return None
    caps = data.get("capabilities") or []
    return "vision" in caps


def ollama_is_ready(url: Optional[str], model: Optional[str]) -> bool:
    """Cheap render-time gate: a URL and a model must both be configured.

    Vision-capability is enforced at model-selection time (non-vision models are
    disabled in the picker); reachability is handled with a graceful fallback at
    extraction time. This keeps page renders free of network calls.
    """
    return bool(url and model)


def parse_extraction_response(generate_json: dict) -> dict:
    """Parse Ollama's /api/generate response into the receipt dict.

    The model's payload is in the "response" field as a JSON string. Tolerates
    markdown code fences. Raises ValueError if no JSON object can be recovered.
    """
    text = (generate_json or {}).get("response", "")
    if not isinstance(text, str):
        raise ValueError("Ollama response had no text payload")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Drop the opening fence (``` or ```json) and the trailing fence.
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.lstrip().lower().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except (ValueError, TypeError):
        # Last resort: grab the first {...} block.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except ValueError:
                pass
        raise ValueError("Ollama did not return valid receipt JSON")


def extract_receipt(
    base_url: str,
    model: str,
    image_b64: str,
    *,
    http_post_json=_default_http_post_json,
) -> dict:
    """Send a base64 image to Ollama and return the mapped expense values.

    Raises on transport/parse failure so the caller can fall back to manual entry.
    """
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": RECEIPT_PROMPT,
        "images": [image_b64],
        "stream": False,
        "format": RECEIPT_SCHEMA,
    }
    parsed = parse_extraction_response(http_post_json(url, payload))
    return map_extraction_to_expense(parsed)


# --- image normalization -------------------------------------------------

def pdf_first_page_to_png(pdf_bytes: bytes, *, zoom: float = 2.0) -> bytes:
    """Render the first page of a PDF to PNG bytes (vision models need images).

    `zoom` upscales the render so small receipt text stays legible to the model.
    """
    import fitz  # PyMuPDF — imported lazily so the rest of the module stays light

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return pix.tobytes("png")
    finally:
        doc.close()


def normalize_to_image(file_bytes: bytes, filename: str) -> bytes:
    """Return image bytes ready for Ollama: PDFs → first-page PNG, images as-is."""
    if (filename or "").lower().endswith(".pdf"):
        return pdf_first_page_to_png(file_bytes)
    return file_bytes


async def read_upload_file(file) -> tuple:
    """Extract (filename, bytes) from a NiceGUI 3.x FileUpload (the `e.file` of
    an upload event). Centralized + tested so the NiceGUI API contract — where
    `read()` is a coroutine and the name lives on `file.name` — can't silently
    regress (it did: the 2.x `e.name`/`e.content` API was removed)."""
    return file.name, await file.read()
