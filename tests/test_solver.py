"""Hand-built scenarios: one per verdict, plus the structural guarantees."""

from tallyproof.core.ledger import Cell, Ledger, make_row
from tallyproof.core.solver import decide


def L(**kw) -> Ledger:
    return Ledger(doc_id="t", **kw)


def test_ties_out_and_proven():
    cert = decide(L(
        rows=(make_row(0, price="10,000"), make_row(1, price="15,000")),
        subtotal=Cell("totals.subtotal", "25,000"),
        tax=Cell("totals.tax", "2,500"),
        total=Cell("totals.total", "27,500"),
        cash=Cell("totals.cash", "30,000"),
        change=Cell("totals.change", "2,500"),
    ))
    assert cert.doc_verdict == "TIES_OUT"
    assert cert.cells["totals.total"].verdict == "PROVEN"
    # total sits in two independent identities: the totals block and the cash anchor
    assert len(cert.cells["totals.total"].equations) == 2
    assert cert.review_count == 0


def test_convention_vote_continental_receipt():
    # printed consistently in dot-grouping (continental): the vote must pick
    # the convention under which the whole document balances
    cert = decide(L(
        rows=(make_row(0, price="39.000"), make_row(1, price="48.000")),
        subtotal=Cell("totals.subtotal", "87.000"),
        cash=Cell("totals.cash", "100.000"),
        change=Cell("totals.change", "13.000"),
        total=Cell("totals.total", "87.000"),
    ))
    assert cert.doc_verdict == "TIES_OUT"
    assert cert.convention == (",", ".")


def test_repair_pinned_by_cross_equation_evidence():
    """Residual -1,000 in the line chain admits two single-glyph stories
    (subtotal 26->25 or row1 15->16).  The totals block is what breaks the
    tie: only the subtotal repair satisfies BOTH identities.  This is the
    product's whole argument in one receipt."""
    cert = decide(L(
        rows=(make_row(0, price="10,000"), make_row(1, price="15,000")),
        subtotal=Cell("totals.subtotal", "26,000"),
        tax=Cell("totals.tax", "2,500"),
        total=Cell("totals.total", "27,500"),
    ))
    assert cert.doc_verdict == "REPAIRED"
    rep = cert.cells["totals.subtotal"]
    assert rep.verdict == "REPAIRED"
    assert rep.value == "25,000"
    assert rep.repaired_from == "26,000"
    # the line cells were part of the proof, not the fault
    assert cert.cells["row0.price"].verdict == "PROVEN"
    assert cert.cells["totals.total"].verdict == "PROVEN"


def test_ambiguous_without_the_tiebreaker():
    """Same receipt WITHOUT the totals block: both stories survive and the
    solver must refuse to choose — this pair of tests is the dominance
    argument made executable."""
    cert = decide(L(
        rows=(make_row(0, price="10,000"), make_row(1, price="15,000")),
        subtotal=Cell("totals.subtotal", "26,000"),
    ))
    assert cert.doc_verdict == "AMBIGUOUS"
    assert cert.cells["totals.subtotal"].verdict == "AMBIGUOUS"
    assert cert.components[0].cardinality >= 2
    for r in cert.cells.values():
        assert r.verdict != "REPAIRED"


def test_unexplained_paper_is_wrong():
    # residual 3 is reachable by no glyph confusion / separator fault
    cert = decide(L(
        rows=(make_row(0, price="10,000"), make_row(1, price="15,000")),
        subtotal=Cell("totals.subtotal", "25,003"),
    ))
    assert cert.doc_verdict == "UNEXPLAINED"
    assert cert.cells["totals.subtotal"].verdict == "UNVERIFIED"
    assert cert.components[0].cardinality == 0


def test_membership_void_row_excluded_not_flagged():
    # a voided line printed but not part of the subtotal: unique closing
    # subset excludes it; it must come back UNCONSTRAINED, not as an error
    cert = decide(L(
        rows=(make_row(0, price="10,000"), make_row(1, price="15,000"),
              make_row(2, name="VOID", price="4,000")),
        subtotal=Cell("totals.subtotal", "25,000"),
    ))
    assert cert.doc_verdict == "TIES_OUT"
    rep = cert.cells["row2.price"]
    assert rep.verdict == "UNCONSTRAINED"
    assert "not part of the subtotal" in rep.note


def test_independent_components_fail_separately():
    # money chain broken beyond repair; quantity anchor intact — the qty
    # component must still certify
    cert = decide(L(
        rows=(make_row(0, qty="1", price="10,000"), make_row(1, qty="2", price="15,000")),
        subtotal=Cell("totals.subtotal", "99,999"),
        menuqty=Cell("totals.menuqty", "3"),
    ))
    verdicts = {c.verdict for c in cert.components}
    assert "UNEXPLAINED" in verdicts  # the money chain
    assert cert.cells["row0.qty"].verdict == "PROVEN"  # the quantity anchor
    assert cert.doc_verdict == "UNEXPLAINED"  # worst component wins the headline


def test_no_structure():
    cert = decide(L(rows=(make_row(0, price="4,000"),)))
    assert cert.doc_verdict == "NO_STRUCTURE"
    assert cert.cells["row0.price"].verdict == "UNCONSTRAINED"


def test_unparseable_cell_lands_in_review():
    cert = decide(L(
        rows=(make_row(0, price="1O,OOO"), make_row(1, price="15,000")),
        subtotal=Cell("totals.subtotal", "25,000"),
    ))
    assert cert.cells["row0.price"].verdict == "UNVERIFIED"
    assert cert.review_count >= 1


def test_certificate_serialises():
    cert = decide(L(
        rows=(make_row(0, price="10,000"),),
        subtotal=Cell("totals.subtotal", "10,000"),
    ))
    d = cert.to_dict()
    assert d["doc_verdict"] == "TIES_OUT"
    assert d["cells"]["totals.subtotal"]["verdict"] == "PROVEN"
