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


# --- reconcile_taxes ----------------------------------------------------

def test_reconcile_taxes_quebec_tps_tvq():
    from ollama_utils import reconcile_taxes
    out = reconcile_taxes([
        {"label": "TPS", "amount": 5.0},
        {"label": "TVQ", "amount": 9.98},
    ])
    assert out["tps"] == pytest.approx(5.0)
    assert out["tvq"] == pytest.approx(9.98)
    assert out["foreign_note"] is None


def test_reconcile_taxes_gst_qst_aliases():
    from ollama_utils import reconcile_taxes
    out = reconcile_taxes([
        {"label": "GST", "amount": 5.0},
        {"label": "QST", "amount": 9.98},
    ])
    assert out["tps"] == pytest.approx(5.0)
    assert out["tvq"] == pytest.approx(9.98)
    assert out["foreign_note"] is None


def test_reconcile_taxes_foreign_tax_goes_to_note_not_columns():
    from ollama_utils import reconcile_taxes
    out = reconcile_taxes([{"label": "VAT 20%", "amount": 8.33}])
    assert out["tps"] == 0.0
    assert out["tvq"] == 0.0
    assert "VAT 20%" in out["foreign_note"]
    assert "8.33" in out["foreign_note"]


def test_reconcile_taxes_empty_or_none():
    from ollama_utils import reconcile_taxes
    for arg in ([], None):
        out = reconcile_taxes(arg)
        assert out == {"tps": 0.0, "tvq": 0.0, "foreign_note": None}


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


def test_map_quebec_cad_receipt_fills_columns_directly():
    from ollama_utils import map_extraction_to_expense
    parsed = {
        "vendor": "Cafe Parvis", "date": "2026-06-18", "subtotal": 100.0,
        "tax_lines": [{"label": "TPS", "amount": 5.0},
                      {"label": "TVQ", "amount": 9.98}],
        "total": 114.98, "currency": "CAD",
    }
    out = map_extraction_to_expense(parsed, rate_provider=_rate(1.0))
    assert "Cafe Parvis" in out["description"]
    assert out["date"] == datetime(2026, 6, 18)
    assert out["amount"] == pytest.approx(100.0)
    assert out["tps"] == pytest.approx(5.0)
    assert out["tvq"] == pytest.approx(9.98)
    assert out["total"] == pytest.approx(114.98)
    assert out["warnings"] == []


def test_map_foreign_receipt_converts_and_notes_original():
    from ollama_utils import map_extraction_to_expense
    parsed = {
        "vendor": "Hotel Paris", "date": "2026-06-18", "subtotal": 40.0,
        "tax_lines": [{"label": "VAT 20%", "amount": 8.0}],
        "total": 48.0, "currency": "EUR",
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
    assert "VAT 20%" in out["notes"]


def test_map_foreign_receipt_rate_unavailable_falls_back_to_raw_with_warning():
    from ollama_utils import map_extraction_to_expense
    parsed = {
        "vendor": "Hotel Paris", "date": "2026-06-18", "subtotal": 40.0,
        "tax_lines": [], "total": 48.0, "currency": "EUR",
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
        "tax_lines": None, "total": 30.0, "currency": "CAD",
    }
    out = map_extraction_to_expense(parsed, rate_provider=_rate(1.0))
    assert out["total"] == pytest.approx(30.0)
    assert out["amount"] == 0.0
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
