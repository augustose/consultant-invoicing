"""Diagnose the Ollama receipt-extraction pipeline against the live server.

Run on a machine that can reach the Ollama server (i.e. the user's box):

    uv run python scripts/diagnose_ollama.py /path/to/a/real/receipt.jpg

It reads the configured URL + model from the app DB, checks connectivity and
vision capability, then times a real /api/generate call and prints the raw
response plus the mapped expense — or the full error. This shows exactly WHERE
and HOW the flow breaks (slow inference, timeout, 404, bad JSON, …).
"""
import sys, os, time, json, base64, traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from sqlmodel import Session, select
from database import engine, CompanySettings
import ollama_utils
from ollama_utils import (
    list_models, probe_model_is_vision, normalize_to_image,
    parse_extraction_response, map_extraction_to_expense,
    RECEIPT_PROMPT, RECEIPT_SCHEMA,
)


def main():
    if len(sys.argv) < 2:
        print("usage: uv run python scripts/diagnose_ollama.py <receipt-image-or-pdf>")
        return
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return

    with Session(engine) as s:
        conf = s.exec(select(CompanySettings)).first()
    url = (conf.ollama_url if conf else None) or os.getenv("OLLAMA_URL")
    model = (conf.ollama_model if conf else None) or os.getenv("OLLAMA_MODEL")
    print(f"== Config ==\n  url   = {url}\n  model = {model}\n")
    if not url or not model:
        print("No URL/model configured. Set them in Settings first.")
        return

    print("== Connectivity ==")
    try:
        names = list_models(url)
        print(f"  models on server: {names}")
    except Exception as ex:
        print(f"  list_models FAILED: {ex!r}")
        return
    print(f"  '{model}' vision-capable: {probe_model_is_vision(url, model)}\n")

    print("== Prepare image ==")
    with open(path, 'rb') as f:
        raw = f.read()
    img = normalize_to_image(raw, os.path.basename(path))
    b64 = base64.b64encode(img).decode('ascii')
    print(f"  input bytes={len(raw)}  image bytes={len(img)}  b64 chars={len(b64)}\n")

    print("== Calling /api/generate (timeout 300s, this may take a while) ==")
    gen_url = f"{url.rstrip('/')}/api/generate"
    payload = {
        "model": model, "prompt": RECEIPT_PROMPT, "images": [b64],
        "stream": False, "format": RECEIPT_SCHEMA,
    }
    t0 = time.time()
    try:
        resp = ollama_utils._default_http_post_json(gen_url, payload, timeout=300.0)
    except Exception as ex:
        print(f"  REQUEST FAILED after {time.time() - t0:.1f}s: {ex!r}")
        traceback.print_exc()
        return
    elapsed = time.time() - t0
    print(f"  OK in {elapsed:.1f}s")
    print(f"  raw 'response' field:\n    {str(resp.get('response'))[:800]}\n")

    print("== Parse + map ==")
    try:
        parsed = parse_extraction_response(resp)
        print(f"  parsed: {json.dumps(parsed, ensure_ascii=False)[:600]}")
        mapped = map_extraction_to_expense(parsed)
        mapped = {**mapped, 'date': str(mapped['date'])}
        print(f"  mapped: {json.dumps(mapped, ensure_ascii=False)[:600]}")
    except Exception as ex:
        print(f"  PARSE/MAP FAILED: {ex!r}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
