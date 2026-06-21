import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from datetime import datetime

import pytest


# --- parse_receipt_date -------------------------------------------------

def test_parse_receipt_date_iso():
    from ollama_utils import parse_receipt_date
    assert parse_receipt_date("2026-06-18") == datetime(2026, 6, 18)


def test_parse_receipt_date_common_formats():
    from ollama_utils import parse_receipt_date
    assert parse_receipt_date("18/06/2026") == datetime(2026, 6, 18)
    assert parse_receipt_date("06/18/2026") == datetime(2026, 6, 18)
    assert parse_receipt_date("June 18, 2026") == datetime(2026, 6, 18)


def test_parse_receipt_date_unparseable_returns_none():
    from ollama_utils import parse_receipt_date
    assert parse_receipt_date("not a date") is None
    assert parse_receipt_date(None) is None
    assert parse_receipt_date("") is None


# --- _to_float ----------------------------------------------------------

def test_to_float_handles_currency_prefixed_strings():
    from ollama_utils import _to_float
    assert _to_float("CA$112.51") == pytest.approx(112.51)
    assert _to_float("US$1,234.50") == pytest.approx(1234.50)
    assert _to_float("-CA$27.49") == pytest.approx(-27.49)
    assert _to_float("€40") == pytest.approx(40.0)
    assert _to_float(129.36) == pytest.approx(129.36)
    assert _to_float(None) == 0.0
    assert _to_float("n/a") == 0.0


# --- normalize_currency -------------------------------------------------

def test_normalize_currency_variants():
    from ollama_utils import normalize_currency
    assert normalize_currency("CAD$") == "CAD"
    assert normalize_currency("CA$") == "CAD"
    assert normalize_currency("$") == "CAD"        # Québec app default
    assert normalize_currency(None) == "CAD"
    assert normalize_currency("") == "CAD"
    assert normalize_currency("USD") == "USD"
    assert normalize_currency("US$") == "USD"
    assert normalize_currency("€") == "EUR"
    assert normalize_currency("EUR") == "EUR"
    assert normalize_currency("£") == "GBP"


# --- split_qc_tax -------------------------------------------------------

def test_split_qc_tax_splits_combined_rate():
    from ollama_utils import split_qc_tax
    # A combined 14.975% tax of 16.85 splits into TPS (5%) + TVQ (9.975%).
    tps, tvq = split_qc_tax(16.85)
    assert tps == pytest.approx(16.85 * 0.05 / 0.14975)
    assert tvq == pytest.approx(16.85 * 0.09975 / 0.14975)
    assert tps + tvq == pytest.approx(16.85)


def test_split_qc_tax_zero():
    from ollama_utils import split_qc_tax
    assert split_qc_tax(0) == (0.0, 0.0)
    assert split_qc_tax(None) == (0.0, 0.0)


# --- frankfurter_rate_provider ------------------------------------------

def test_frankfurter_rate_provider_parses_rate():
    from ollama_utils import frankfurter_rate_provider
    calls = []

    def fake_get_json(url):
        calls.append(url)
        return {"amount": 1.0, "base": "EUR", "date": "2026-06-18",
                "rates": {"CAD": 1.47}}

    rate = frankfurter_rate_provider("EUR", datetime(2026, 6, 18),
                                     http_get_json=fake_get_json)
    assert rate == pytest.approx(1.47)
    assert "2026-06-18" in calls[0]
    assert "from=EUR" in calls[0] and "to=CAD" in calls[0]


def test_frankfurter_rate_provider_cad_is_identity_without_http():
    from ollama_utils import frankfurter_rate_provider

    def boom(url):
        raise AssertionError("should not call HTTP for CAD")

    assert frankfurter_rate_provider("CAD", None, http_get_json=boom) == 1.0


def test_frankfurter_rate_provider_returns_none_on_error():
    from ollama_utils import frankfurter_rate_provider

    def boom(url):
        raise OSError("network down")

    assert frankfurter_rate_provider("EUR", None, http_get_json=boom) is None


# --- map_extraction_to_expense ------------------------------------------

def _rate(value):
    """A fake rate provider returning a fixed rate (or None)."""
    return lambda currency, on_date: value


def test_map_quebec_cad_receipt_splits_combined_tax():
    from ollama_utils import map_extraction_to_expense
    # The real Anthropic CA invoice: one combined 14.975% tax line.
    parsed = {
        "vendor": "Anthropic, PBC", "date": "March 27, 2026",
        "subtotal": 112.51, "tax_total": 16.85, "total": 129.36, "currency": "CAD",
    }
    out = map_extraction_to_expense(parsed, rate_provider=_rate(1.0))
    assert "Anthropic" in out["description"]
    assert out["date"] == datetime(2026, 3, 27)
    assert out["amount"] == pytest.approx(112.51)
    assert out["tps"] == pytest.approx(16.85 * 0.05 / 0.14975, abs=0.01)
    assert out["tvq"] == pytest.approx(16.85 * 0.09975 / 0.14975, abs=0.01)
    assert out["total"] == pytest.approx(129.36)
    assert out["warnings"] == []


def test_map_derives_subtotal_and_tax_from_total_when_model_inconsistent():
    from ollama_utils import map_extraction_to_expense
    # Real minicpm-v output: total is right, subtotal/tax are garbage (negative tax).
    parsed = {
        "vendor": "Anthropic, PBC", "date": "March 27, 2026",
        "subtotal": 149, "tax_total": -25.38, "total": 129.36, "currency": "CAD",
    }
    out = map_extraction_to_expense(parsed, rate_provider=_rate(1.0))
    assert out["total"] == pytest.approx(129.36)
    assert out["amount"] == pytest.approx(129.36 / 1.14975, abs=0.01)   # 112.51
    assert out["tps"] + out["tvq"] == pytest.approx(129.36 - 129.36 / 1.14975, abs=0.01)
    assert any("deriv" in w.lower() for w in out["warnings"])


def test_map_reconstructs_missing_total_from_subtotal_and_tax():
    from ollama_utils import map_extraction_to_expense
    parsed = {
        "vendor": "Shop", "date": "2026-06-18", "subtotal": 100.0,
        "tax_total": 14.98, "total": None, "currency": "CAD",
    }
    out = map_extraction_to_expense(parsed, rate_provider=_rate(1.0))
    assert out["total"] == pytest.approx(114.98)


def test_map_foreign_receipt_converts_and_notes_original():
    from ollama_utils import map_extraction_to_expense
    parsed = {
        "vendor": "Hotel Paris", "date": "2026-06-18", "subtotal": 40.0,
        "tax_total": 8.0, "total": 48.0, "currency": "EUR",
    }
    out = map_extraction_to_expense(parsed, rate_provider=_rate(1.5))
    # amounts converted to CAD
    assert out["amount"] == pytest.approx(60.0)
    assert out["total"] == pytest.approx(72.0)
    # foreign tax never lands in QC columns
    assert out["tps"] == 0.0 and out["tvq"] == 0.0
    # original currency + rate + foreign tax preserved in notes
    assert "EUR" in out["notes"]
    assert "1.5" in out["notes"]


def test_map_foreign_receipt_rate_unavailable_falls_back_to_raw_with_warning():
    from ollama_utils import map_extraction_to_expense
    parsed = {
        "vendor": "Hotel Paris", "date": "2026-06-18", "subtotal": 40.0,
        "tax_total": 0.0, "total": 48.0, "currency": "EUR",
    }
    out = map_extraction_to_expense(parsed, rate_provider=_rate(None))
    # not converted — raw figures kept
    assert out["amount"] == pytest.approx(40.0)
    assert out["total"] == pytest.approx(48.0)
    assert any("exchange rate" in w.lower() for w in out["warnings"])
    assert "EUR" in out["notes"]


def test_map_total_only_receipt_warns_taxes_not_detected():
    from ollama_utils import map_extraction_to_expense
    parsed = {
        "vendor": "Corner Shop", "date": None, "subtotal": None,
        "tax_total": None, "total": 30.0, "currency": "CAD",
    }
    out = map_extraction_to_expense(parsed, rate_provider=_rate(1.0))
    assert out["total"] == pytest.approx(30.0)
    assert out["tps"] == 0.0 and out["tvq"] == 0.0
    assert out["date"] is None
    assert any("tax" in w.lower() for w in out["warnings"])


# --- Ollama HTTP boundary -----------------------------------------------

def test_parse_models_response_extracts_names():
    from ollama_utils import parse_models_response
    resp = {"models": [{"name": "llava:latest"}, {"name": "mistral:7b"}]}
    assert parse_models_response(resp) == ["llava:latest", "mistral:7b"]


def test_parse_models_response_empty_or_malformed():
    from ollama_utils import parse_models_response
    assert parse_models_response({}) == []
    assert parse_models_response({"models": []}) == []


def test_probe_model_is_vision_true_false_and_unreachable():
    from ollama_utils import probe_model_is_vision

    def show(url, payload):
        assert "/api/show" in url
        if payload["model"] == "llava":
            return {"capabilities": ["completion", "vision"]}
        return {"capabilities": ["completion"]}

    assert probe_model_is_vision("http://h:11434", "llava", http_post_json=show) is True
    assert probe_model_is_vision("http://h:11434", "mistral", http_post_json=show) is False

    def down(url, payload):
        raise OSError("unreachable")

    assert probe_model_is_vision("http://h:11434", "llava", http_post_json=down) is None


def test_parse_extraction_response_plain_json():
    from ollama_utils import parse_extraction_response
    gen = {"response": '{"vendor": "Cafe", "total": 12.5}'}
    out = parse_extraction_response(gen)
    assert out["vendor"] == "Cafe"
    assert out["total"] == 12.5


def test_parse_extraction_response_strips_markdown_fences():
    from ollama_utils import parse_extraction_response
    gen = {"response": '```json\n{"vendor": "Cafe", "total": 12.5}\n```'}
    out = parse_extraction_response(gen)
    assert out["vendor"] == "Cafe"


def test_parse_extraction_response_invalid_raises():
    from ollama_utils import parse_extraction_response
    with pytest.raises(ValueError):
        parse_extraction_response({"response": "I could not read the receipt."})


def test_ollama_is_ready_requires_url_and_model():
    from ollama_utils import ollama_is_ready
    assert ollama_is_ready("http://h:11434", "llava") is True
    assert ollama_is_ready("", "llava") is False
    assert ollama_is_ready("http://h:11434", "") is False
    assert ollama_is_ready(None, None) is False


# --- image normalization (PDF -> PNG) -----------------------------------

def _tiny_pdf_bytes():
    from io import BytesIO
    from reportlab.pdfgen import canvas
    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, "RECEIPT TOTAL 12.50")
    c.showPage()
    c.save()
    return buf.getvalue()


def test_pdf_first_page_to_png_returns_png_bytes():
    from ollama_utils import pdf_first_page_to_png
    png = pdf_first_page_to_png(_tiny_pdf_bytes())
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic number


def test_normalize_to_image_converts_pdf():
    from ollama_utils import normalize_to_image
    out = normalize_to_image(_tiny_pdf_bytes(), "scan.pdf")
    assert out[:8] == b"\x89PNG\r\n\x1a\n"


def test_normalize_to_image_passes_images_through_unchanged():
    from ollama_utils import normalize_to_image
    fake_png = b"\x89PNG\r\n\x1a\n" + b"not really an image"
    assert normalize_to_image(fake_png, "photo.png") == fake_png


# --- read_upload_file: locks the NiceGUI 3.x FileUpload API contract --------

def test_read_upload_file_returns_name_and_bytes():
    import asyncio
    from nicegui.elements.upload_files import SmallFileUpload
    from ollama_utils import read_upload_file

    # The exact object NiceGUI hands to on_upload as e.file (3.x API).
    f = SmallFileUpload("receipt.png", "image/png", b"PNGDATA")
    name, data = asyncio.run(read_upload_file(f))
    assert name == "receipt.png"
    assert data == b"PNGDATA"
