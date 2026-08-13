"""The published study numbers, frozen.

These are the measurements the build's whole argument rests on (README,
decisions.md, eval/report.md).  They were computed from CORD-v2's human
annotations before any product code existed; if a refactor of the reading
model or the adapters shifts ANY of them, the claim and the code have
diverged and the build must fail until the docs are regenerated to match.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.run import (
    sec_ambiguity,
    sec_base_rates,
    sec_segmentation,
    sec_soundness,
    sec_study_lattice,
)

sink = lambda s: None


def test_ambiguity_census_frozen():
    r = sec_ambiguity(sink)
    assert r["tokens"] == 1312
    assert r["ambiguous_pct"] == 83.5


def test_base_rates_frozen():
    r = sec_base_rates(sink)
    assert r["qty x unitprice = price"] == "46/51"
    assert r["sum(lines) = subtotal"] == "101/120"
    assert r["sum(lines) = total"] == "93/177"
    assert r["cash - total = change"] == "84/96"
    assert r["subtotal + charges = total"] == "66/77"
    assert r["sum(qty) = item count"] == "35/36"


def test_study_lattice_frozen():
    r = sec_study_lattice(sink)
    assert r["n"] == 118
    assert r["unique -> certify"] == 97          # 82.2%
    assert r["multiple -> AMBIGUOUS"] == 9       # 7.6%
    assert r["none -> UNEXPLAINED (paper wrong)"] == 12  # 10.2%


def test_segmentation_frozen():
    assert sec_segmentation(sink)["multi_pct"] == 5.1


def test_soundness_frozen():
    r = sec_soundness(sink)
    assert r["n"] == 97
    assert r["alternatives"] == 0
