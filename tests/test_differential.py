"""Differential check against an independently-written reference solver.

The reference below re-implements the decision semantics with the dumbest
possible constructs — ``itertools.combinations`` for subsets, dict-merging
for components, straight Fraction sums for residuals — sharing only the
frozen reading model and the equation-applicability rules with the real
solver.  It is written to be obviously correct rather than fast.  The real
solver (bitmask enumeration, per-component search, merged layers) must
agree with it on the document verdict for every one of the 200 CORD
receipts.  Any disagreement is a bug in the fast path or in the reference;
both are worth finding, and integer/rounding-order bugs show up here first.
"""

from itertools import combinations

from tallyproof.core.constraints import build_equations, choose_convention, parse_all
from tallyproof.core.numerals import surface_variants
from tallyproof.core.solver import decide
from tallyproof.extract.cord_gt import load_cord

RANK = {"TIES_OUT": 0, "REPAIRED": 1, "AMBIGUOUS": 2, "UNEXPLAINED": 3}


def _naive_components(eqs):
    groups = []  # list of (cell_set, eq_list)
    for eq in eqs:
        cells = set(eq.cells)
        merged = [g for g in groups if g[0] & cells]
        for g in merged:
            groups.remove(g)
            cells |= g[0]
        groups.append((cells, [eq] + [e for g in merged for e in g[1]]))
    return [g[1] for g in groups]


def _holds(eq, assign, selected):
    total = 0
    if eq.kind == "L1":
        q, u, p = (assign[c] for c in eq.cells)
        return q * u == p
    for cid in eq.members:
        if cid in selected:
            total += assign[cid]
    for coef, cid in eq.terms:
        total += coef * assign[cid]
    return total == 0


def _naive_component_verdict(eqs, assign, surfaces):
    members = ()
    for eq in eqs:
        if eq.members:
            members = eq.members
    if members:
        subsets = [
            frozenset(s)
            for r in range(1, len(members) + 1)
            for s in combinations(members, r)
        ]
    else:
        subsets = [frozenset()]

    def all_hold(a, s):
        return all(_holds(eq, a, s) for eq in eqs)

    layer0 = [s for s in subsets if all_hold(assign, s)]
    if layer0:
        return "TIES_OUT" if len(layer0) == 1 else "AMBIGUOUS"

    cells = sorted({c for eq in eqs for c in eq.cells})
    explanations = set()
    for cid in cells:
        for v in surface_variants(surfaces[cid]):
            if v == assign[cid]:
                continue
            trial = dict(assign)
            trial[cid] = v
            for s in subsets:
                if all_hold(trial, s):
                    explanations.add((cid, v, s))
    if not explanations:
        return "UNEXPLAINED"
    readings = {(c, v) for c, v, _ in explanations}
    masks = {s for _, _, s in explanations}
    if len(readings) == 1 and len(masks) == 1:
        return "REPAIRED"
    return "AMBIGUOUS"


def naive_doc_verdict(ledger) -> str:
    dec, grp = choose_convention(ledger)
    assign = parse_all(ledger, dec, grp)
    eqs = build_equations(ledger, assign)
    if not eqs:
        return "NO_STRUCTURE"
    surfaces = {cid: c.surface for cid, c in ledger.cells().items()}
    verdicts = [
        _naive_component_verdict(comp, assign, surfaces)
        for comp in _naive_components(eqs)
    ]
    return max(verdicts, key=lambda v: RANK[v])


def test_reference_agrees_on_every_cord_receipt():
    for ledger in load_cord():
        want = naive_doc_verdict(ledger)
        got = decide(ledger).doc_verdict
        assert got == want, f"{ledger.doc_id}: solver={got} reference={want}"
