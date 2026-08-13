"""Seeded fault injection as a CI gate (subset of eval/run.py's full study).

The one outcome that destroys trust is a FALSE REPAIR — a re-reading that
satisfies every identity but is not what the receipt said.  Within the
declared fault model the full study measures 0 false repairs (see eval/report.md); this test locks the
property on a fast deterministic subset so a regression in the textual
channel fails the build, not the demo.
"""

import random
import sys
from pathlib import Path

from tallyproof.core.solver import decide
from tallyproof.extract.cord_gt import load_cord

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.run import _glyph_corrupt, inject


def test_no_false_repairs_in_model():
    rng = random.Random(7)
    trials = 0
    for led in load_cord()[:80]:
        base = decide(led)
        if base.doc_verdict != "TIES_OUT":
            continue
        proven = [
            (cid, r.surface, r.value)
            for cid, r in base.cells.items()
            if r.verdict == "PROVEN" and not cid.endswith(".qty")
        ]
        for cid, surface, true_value in proven[:2]:
            bad = _glyph_corrupt(surface, rng)
            if bad is None or bad == surface:
                continue
            trials += 1
            cert = decide(inject(led, cid, bad))
            for other_id, rep in cert.cells.items():
                if rep.verdict == "REPAIRED":
                    # any repair must restore the original value on the
                    # corrupted cell — never invent one anywhere else
                    assert other_id == cid, f"{led.doc_id}: repaired wrong cell"
                    assert rep.value == true_value, (
                        f"{led.doc_id}:{cid} FALSE REPAIR "
                        f"{surface}->{bad} gave {rep.value}, truth {true_value}"
                    )
    assert trials >= 40, f"only {trials} trials ran; corpus subset too small"
