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


# Tax labels that map to Québec columns. Anything else is treated as foreign.
_TPS_ALIASES = ("tps", "gst")          # federal goods & services tax
_TVQ_ALIASES = ("tvq", "qst")          # Québec sales tax


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


def reconcile_taxes(tax_lines) -> dict:
    """Split extracted tax lines into Québec tps/tvq columns vs a foreign note.

    Québec receipts itemize TPS/TVQ (a.k.a. GST/QST) → mapped to columns.
    Foreign taxes (VAT, sales tax, …) have no column on ClientExpense, so they
    are preserved as a human-readable note and left inside the tax-inclusive
    total. Nothing is ever back-computed or guessed.
    """
    result = {"tps": 0.0, "tvq": 0.0, "foreign_note": None}
    if not tax_lines:
        return result

    foreign_parts = []
    for line in tax_lines:
        if not isinstance(line, dict):
            continue
        label = str(line.get("label") or "").strip()
        amount = _to_float(line.get("amount"))
        label_lc = label.lower()
        if any(alias in label_lc for alias in _TPS_ALIASES):
            result["tps"] += amount
        elif any(alias in label_lc for alias in _TVQ_ALIASES):
            result["tvq"] += amount
        else:
            foreign_parts.append(f"{label or 'Tax'}: {amount:.2f}")

    if foreign_parts:
        result["foreign_note"] = "Foreign tax — " + "; ".join(foreign_parts)
    return result


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

    amount = _to_float(parsed.get("subtotal"))
    total = _to_float(parsed.get("total"))
    taxes = reconcile_taxes(parsed.get("tax_lines"))
    tps, tvq = taxes["tps"], taxes["tvq"]
    if taxes["foreign_note"]:
        notes_parts.append(taxes["foreign_note"])

    currency = str(parsed.get("currency") or "CAD").strip().upper() or "CAD"
    if currency != "CAD":
        rate = rate_provider(currency, date)
        if rate is not None:
            amount, tps, tvq, total = (v * rate for v in (amount, tps, tvq, total))
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

    # Taxes were not itemized: there is a total but no subtotal/tax split.
    if total and not amount and tps == 0.0 and tvq == 0.0:
        warnings.append("Taxes not detected — fill in or split manually.")
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
        "total": {"type": ["number", "null"]},
        "currency": {"type": ["string", "null"]},
        "tax_lines": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": ["string", "null"]},
                    "amount": {"type": ["number", "null"]},
                },
            },
        },
    },
}

RECEIPT_PROMPT = (
    "You are reading a scanned expense receipt. Extract the vendor name, the "
    "purchase date, the pre-tax subtotal, every tax line (label and amount), the "
    "grand total, and the currency code. Use null for anything not clearly "
    "visible. Do not guess or compute missing values."
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
