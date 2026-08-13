"""Golden verdicts over all 200 CORD receipts.

Any solver change shows up here as a reviewable diff — which is what makes
silent tuning toward the extractor's habits visible in code review.  If a
change is intentional, regenerate with scripts/make_golden.py in the same
commit and the diff tells the story.
"""

import json
from pathlib import Path

from tallyproof.core.solver import decide
from tallyproof.extract.cord_gt import load_cord

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "cord_verdicts.json").read_text()
)


def test_golden_verdicts_unchanged():
    ledgers = load_cord()
    assert len(ledgers) == len(GOLDEN) == 200
    for led in ledgers:
        cert = decide(led)
        want = GOLDEN[led.doc_id]
        assert cert.doc_verdict == want["doc_verdict"], led.doc_id
        assert cert.counts() == want["counts"], led.doc_id
        for cid, cell in cert.cells.items():
            assert cell.verdict == want["cells"][cid]["verdict"], f"{led.doc_id}:{cid}"
            assert cell.value == want["cells"][cid]["value"], f"{led.doc_id}:{cid}"
