"""Diagnose a GEMINI_API_KEY against the exact requests Tallyproof sends.

Run it on any machine where the key is in the environment — the key is
read from env, sent only to Google, and never printed:

    GEMINI_API_KEY=...  .venv/bin/python scripts/check_gemini_key.py

Three probes, cheapest first, each printing PASS/FAIL plus Google's raw
error body on failure (safe to share — it never contains the key):

  1. minimal text call        -> separates key problems from body problems
  2. the app's exact receipt request (image + JSON schema) on the
     configured model (TALLYPROOF_GEMINI_MODEL, default gemini-2.5-flash)
  3. the same on the gemini-flash-latest fallback alias
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx

from tallyproof.extract.vlm import (
    GEMINI_FALLBACK_MODEL,
    GEMINI_MODEL,
    gemini_request_body,
)

KEY = os.environ.get("GEMINI_API_KEY")
if not KEY:
    sys.exit("set GEMINI_API_KEY in the environment first")
HEADERS = {"x-goog-api-key": KEY}
BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def probe(name: str, model: str, body: dict) -> bool:
    try:
        r = httpx.post(f"{BASE}/{model}:generateContent",
                       json=body, headers=HEADERS, timeout=90)
    except httpx.HTTPError as e:
        print(f"[{name}] NETWORK FAIL: {type(e).__name__}: {e}")
        return False
    if r.status_code == 200:
        try:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            print(f"[{name}] PASS — model answered ({len(text)} chars)")
            return True
        except Exception:  # noqa: BLE001 — diagnostic: any shape surprise is reportable
            print(f"[{name}] ODD 200 — no usable candidate: {r.text[:400]}")
            return False
    print(f"[{name}] FAIL {r.status_code} — Google says:")
    try:
        print(json.dumps(r.json(), indent=2)[:1200])
    except ValueError:
        print(r.text[:800])
    return False


print(f"configured model: {GEMINI_MODEL} | fallback: {GEMINI_FALLBACK_MODEL}\n")

ok1 = probe("1: minimal text call     ", GEMINI_MODEL,
            {"contents": [{"parts": [{"text": "Reply with exactly: ok"}]}]})

img = (ROOT / "samples" / "cord-test-004.jpg").read_bytes()
receipt = gemini_request_body(img, "image/jpeg")
ok2 = probe("2: app's receipt request ", GEMINI_MODEL, receipt)
ok3 = probe("3: fallback-alias request", GEMINI_FALLBACK_MODEL, receipt)

print()
if ok2 or ok3:
    print("VERDICT: key and request work — the live 502 is environmental "
          "(check the key VALUE on Render for whitespace, and Render logs).")
elif ok1:
    print("VERDICT: key is fine; the receipt request body is being rejected — "
          "paste probe 2/3's error output back so the request can be fixed.")
else:
    print("VERDICT: the key itself is rejected — re-create it at "
          "aistudio.google.com/apikey and update Render's GEMINI_API_KEY.")
