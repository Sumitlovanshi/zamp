"""Build samples/manifest.json — the precomputed gallery.

Six tiles, one per designed experience, all decided offline from CORD-v2's
human annotations so the landing page needs zero model calls, zero network
and zero luck.  Tile 6 is the only synthetic step: ONE glyph of a real
receipt's annotation is swapped (searched, within the declared confusion set)
to demonstrate an extraction-error repair deterministically; the tile says
exactly that.  Run: .venv/bin/python scripts/make_samples.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tallyproof.core.ledger import Ledger
from tallyproof.core.solver import decide
from tallyproof.extract.cord_gt import load_cord

TILES = [
    {
        "doc_id": "cord-test-085",
        "slug": "proven",
        "title": "26 of 27 cells proven — and the 27th is honest",
        "blurb": "Line chain, totals block and item count interlock to pin 26 "
                 "cells. The cash line has no printed change to check against — "
                 "so it is labelled unconstrained, not decorated.",
    },
    {
        "doc_id": "cord-test-070",
        "slug": "repaired",
        "title": "A real annotation error, caught and repaired",
        "blurb": "The human-written ground truth for this receipt breaks the "
                 "chain at row 5. Exactly one re-reading closes it — pinned by "
                 "four row identities plus the totals block. Nothing was guessed.",
    },
    {
        "doc_id": "cord-test-031",
        "slug": "ambiguous",
        "title": "Two row-groupings balance. It refuses to choose",
        "blurb": "Two identical-priced rows, a subtotal equal to one of them: "
                 "arithmetic cannot say which row is the addend, so nothing "
                 "here is certified. Refusal is the correct answer.",
    },
    {
        "doc_id": "cord-test-004",
        "slug": "unexplained",
        "title": "This receipt does not add up — and that's proven",
        "blurb": "No reading of any single cell closes the residual; the search "
                 "was exhaustive. The extraction agrees with the pixels. "
                 "The paper is wrong.",
    },
    {
        "doc_id": "cord-test-024",
        "slug": "no-structure",
        "title": "Nothing here can be proven, and it says so",
        "blurb": "No subtotal, no cash line, no item count: this receipt "
                 "carries no redundancy, so every number is honestly labelled "
                 "unconstrained instead of decorated with fake confidence.",
    },
    {
        "doc_id": "cord-validation-048",
        "slug": "misread",
        "title": "Simulated OCR misread: one glyph swapped",
        "blurb": "Same real receipt, one glyph corrupted the way thermal paper "
                 "does it (the exact swap is declared on the page). Exactly one "
                 "re-reading closes the residual, so it is repaired — original shown.",
        "corrupt": True,
    },
]


def corrupt_one_glyph(ledger: Ledger) -> tuple[Ledger, str]:
    """Find a single-glyph corruption of one line price whose UNIQUE repair
    is the original value — i.e. a corruption the solver provably undoes.
    Deterministic: first (row, position, confusion) in reading order wins.
    Ambiguous corruptions (two stories fit) are skipped, which is itself
    the thesis: whether a misread is recoverable is a property of the
    receipt's redundancy, not of anyone's optimism."""
    from tallyproof.core.numerals import CONFUSION

    base = decide(ledger)
    d = ledger.to_dict()
    for row in d["rows"]:
        cell = row.get("price")
        if not cell or base.cells[cell["cell_id"]].verdict != "PROVEN":
            continue
        before = cell["surface"]
        for i, ch in enumerate(before):
            for sub in CONFUSION.get(ch, ""):
                candidate = before[:i] + sub + before[i + 1 :]
                cell["surface"] = candidate
                trial = Ledger.from_dict(d)
                cert = decide(trial)
                rep = cert.cells[cell["cell_id"]]
                if (
                    cert.doc_verdict == "REPAIRED"
                    and rep.verdict == "REPAIRED"
                    and rep.value == base.cells[cell["cell_id"]].value
                ):
                    return trial, f"{before} → {candidate} (glyph {ch}→{sub})"
        cell["surface"] = before
    raise SystemExit("no uniquely-repairable corruption found in sample")


def main() -> None:
    by_id = {led.doc_id: led for led in load_cord()}
    manifest = []
    for tile in TILES:
        ledger = by_id[tile["doc_id"]]
        note = ""
        if tile.get("corrupt"):
            ledger, note = corrupt_one_glyph(ledger)
        cert = decide(ledger)
        manifest.append(
            {
                "slug": tile["slug"],
                "title": tile["title"],
                "blurb": tile["blurb"],
                "doc_id": tile["doc_id"],
                "image": f"{tile['doc_id']}.jpg",
                "injected": note,
                "ledger": ledger.to_dict(),
                "certificate": cert.to_dict(),
            }
        )
        print(f"{tile['slug']:14s} {cert.doc_verdict:14s} review "
              f"{cert.review_count}/{len(cert.cells)}  {note}")
    (ROOT / "samples" / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print("wrote samples/manifest.json")


if __name__ == "__main__":
    main()
