"""Soundness regressions from adversarial review rounds 2-3.

Each test is a verified repro of a way the solver once (or nearly) emitted
a certificate that was not literally true.  These are the failures that
would quietly destroy the product's one claim, so each is pinned forever.
"""

from tallyproof.core.ledger import Cell, Ledger, make_row
from tallyproof.core.numerals import render
from tallyproof.core.solver import MAX_EXHAUSTIVE_ROWS, decide


def L(**kw) -> Ledger:
    return Ledger(doc_id="t", **kw)


# --- printed-but-unparseable charges must make identities inapplicable -----
def test_unparseable_tax_never_certifies_false_repair():
    """Arithmetically exact receipt (23+40+5+tax5=73) whose tax prints as
    '5%'.  Building L2b WITHOUT the tax term would 'repair' the correct
    23 into 28 via the 3->8 confusion and stamp the rest PROVEN — a
    certified false repair on a mundane live input."""
    cert = decide(L(
        rows=(make_row(0, price="23"), make_row(1, price="40")),
        service=Cell("totals.service", "5"),
        tax=Cell("totals.tax", "5%"),  # printed, unparseable
        total=Cell("totals.total", "73"),
    ))
    assert cert.doc_verdict in ("NO_STRUCTURE",)  # L2b inapplicable, nothing checkable
    for rep in cert.cells.values():
        assert rep.verdict not in ("REPAIRED", "PROVEN")


def test_unparseable_tax_does_not_poison_the_line_chain():
    """Same disease, other symptom: with a subtotal present, a phantom L3
    (missing its unparseable tax term) would drag the perfectly consistent
    L2 into UNEXPLAINED through the shared subtotal cell."""
    cert = decide(L(
        rows=(make_row(0, price="60"), make_row(1, price="40")),
        subtotal=Cell("totals.subtotal", "100"),
        tax=Cell("totals.tax", "Rp8%"),  # printed, unparseable
        service=Cell("totals.service", "5"),
        total=Cell("totals.total", "113"),
    ))
    assert cert.doc_verdict == "TIES_OUT"  # L2 certifies; L3 honestly inapplicable
    assert cert.cells["row0.price"].verdict == "PROVEN"
    assert cert.cells["totals.subtotal"].verdict == "PROVEN"
    assert cert.cells["totals.tax"].verdict == "UNVERIFIED"  # unreadable, in review
    assert cert.cells["totals.total"].verdict == "UNCONSTRAINED"  # no identity reaches it


# --- truncated membership sweep must refuse, not certify -------------------
def test_truncated_sweep_refuses_to_certify():
    """15 rows incl. a zero-priced one: with 2^15 subsets out of budget only
    the full mask is tried, so 'membership unique' is unknowable — and a
    zero row PROVABLY makes it non-unique.  The solver must refuse."""
    n = MAX_EXHAUSTIVE_ROWS + 2
    prices = [100] * (n - 1) + [0]
    cert = decide(L(
        rows=tuple(make_row(i, price=render(p)) for i, p in enumerate(prices)),
        subtotal=Cell("totals.subtotal", render(sum(prices))),
    ))
    assert cert.doc_verdict == "AMBIGUOUS"
    assert not cert.components[0].exhaustive
    for rep in cert.cells.values():
        assert rep.verdict != "PROVEN"
    assert "refusing to certify" in cert.components[0].detail


# --- ambiguous components: stable cells certified truthfully ---------------
def test_stable_cell_in_ambiguous_component_is_proven_with_true_note():
    """Two competing single-glyph stories (subtotal 6->5 vs row1 5->6) share
    the full-row membership, and row0.price reads 10,000 under both — it is
    pinned no matter which explanation is true, and the note says exactly
    that (previously: forced AMBIGUOUS with a false 'row-grouping not
    unique' note when the grouping never varied)."""
    cert = decide(L(
        rows=(make_row(0, price="10,000"), make_row(1, price="15,000")),
        subtotal=Cell("totals.subtotal", "26,000"),
    ))
    assert cert.doc_verdict == "AMBIGUOUS"
    rep = cert.cells["row0.price"]
    assert rep.verdict == "PROVEN"
    assert "no matter which" in rep.note
    assert cert.cells["totals.subtotal"].verdict == "AMBIGUOUS"
    assert cert.cells["row1.price"].verdict == "AMBIGUOUS"


def test_stably_excluded_member_is_never_certified():
    """rows 5,5,9,100 with subtotal 20: explanations vary in readings but
    every one leaves row3 (100) outside the balancing subset — arithmetic
    never checked it, so certifying it would be a lie."""
    cert = decide(L(
        rows=(make_row(0, price="5"), make_row(1, price="5"),
              make_row(2, price="9"), make_row(3, price="100")),
        subtotal=Cell("totals.subtotal", "20"),
    ))
    if cert.doc_verdict == "AMBIGUOUS":
        assert cert.cells["row3.price"].verdict != "PROVEN"
