"""Regenerate tests/golden/cord_verdicts.json — the committed per-document
verdicts over all 200 CORD receipts. Any solver change surfaces as a
reviewable diff here; silent drift toward the extractor's habits cannot
hide. Run: .venv/bin/python scripts/make_golden.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tallyproof.core.solver import decide
from tallyproof.extract.cord_gt import load_cord

out = {}
for led in load_cord():
    cert = decide(led)
    out[led.doc_id] = {
        "doc_verdict": cert.doc_verdict,
        "counts": cert.counts(),
        "cells": {cid: {"verdict": r.verdict, "value": r.value}
                  for cid, r in sorted(cert.cells.items())},
    }
path = Path(__file__).resolve().parents[1] / "tests" / "golden" / "cord_verdicts.json"
path.write_text(json.dumps(out, indent=1, sort_keys=True))
print(f"wrote {path} ({len(out)} documents)")
