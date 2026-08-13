"""The two properties the whole product stands on.

Soundness: a ledger whose numbers genuinely balance must NEVER be
"repaired" or declared inconsistent — a verifier that flags correct
documents is worse than no verifier.

Uniqueness-as-precondition: PROVEN must never be emitted when more than
one row-grouping closes the subtotal (5.1% of real receipts) — that is
the confident-wrongness trap, certifying against an unproven constraint
set.
"""

from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from tallyproof.core.ledger import Cell, Ledger, make_row
from tallyproof.core.numerals import render
from tallyproof.core.solver import decide


def money(v: int) -> str:
    return render(Fraction(v), ".", ",")


amounts = st.lists(st.integers(min_value=1, max_value=10**7), min_size=1, max_size=8)


def balanced_ledger(vals: list[int], with_cash: bool, cash_extra: int) -> Ledger:
    sub = sum(vals)
    tax = sub // 10
    total = sub + tax
    kw = {}
    if with_cash:
        kw = {
            "cash": Cell("totals.cash", money(total + cash_extra)),
            "change": Cell("totals.change", money(cash_extra)),
        }
    return Ledger(
        doc_id="prop",
        rows=tuple(make_row(i, name=f"item {i}", price=money(v)) for i, v in enumerate(vals)),
        subtotal=Cell("totals.subtotal", money(sub)),
        tax=Cell("totals.tax", money(tax)),
        total=Cell("totals.total", money(total)),
        **kw,
    )


@given(amounts, st.booleans(), st.integers(min_value=0, max_value=10**6))
@settings(max_examples=150, deadline=None)
def test_soundness_balanced_never_flagged(vals, with_cash, cash_extra):
    cert = decide(balanced_ledger(vals, with_cash, cash_extra))
    assert cert.doc_verdict in ("TIES_OUT", "AMBIGUOUS")  # never REPAIRED/UNEXPLAINED
    counts = cert.counts()
    assert counts["REPAIRED"] == 0
    assert counts["UNVERIFIED"] == 0


@given(amounts)
@settings(max_examples=100, deadline=None)
def test_proven_requires_unique_segmentation(vals):
    """Duplicate the row list and set subtotal to one copy's sum: at least
    two subsets now close, so nothing in the chain may be PROVEN."""
    doubled = vals + vals
    ledger = Ledger(
        doc_id="prop-seg",
        rows=tuple(make_row(i, price=money(v)) for i, v in enumerate(doubled)),
        subtotal=Cell("totals.subtotal", money(sum(vals))),
    )
    cert = decide(ledger)
    assert cert.doc_verdict == "AMBIGUOUS"
    for rep in cert.cells.values():
        assert rep.verdict != "PROVEN"


@given(amounts, st.integers(min_value=1, max_value=6))
@settings(max_examples=100, deadline=None)
def test_detection_single_balance_break(vals, delta):
    """Perturb the subtotal by a value no admissible re-reading can absorb
    silently: the document must never come back fully certified."""
    sub = sum(vals)
    ledger = Ledger(
        doc_id="prop-broken",
        rows=tuple(make_row(i, price=money(v)) for i, v in enumerate(vals)),
        subtotal=Cell("totals.subtotal", money(sub + delta)),
    )
    cert = decide(ledger)
    assert cert.doc_verdict in ("REPAIRED", "AMBIGUOUS", "UNEXPLAINED")


@given(amounts)
@settings(max_examples=60, deadline=None)
def test_scale_homogeneity_limitation_is_stable(vals):
    """Encodes the published limitation: additive identities are homogeneous
    of degree 1, so a uniform x1000 rescale of a balanced ledger still
    balances.  A contributor who 'fixes' this breaks the declared semantics
    and this test tells them so."""
    cert_a = decide(balanced_ledger(vals, False, 0))
    cert_b = decide(balanced_ledger([v * 1000 for v in vals], False, 0))
    assert cert_a.doc_verdict == cert_b.doc_verdict
