"""Exhaustiveness: the solver's enumerator vs a naive nested-loop search.

A pruning bug that silently drops one competing hypothesis would turn an
AMBIGUOUS into a false REPAIRED — the worst possible regression, and one
no example-based test would notice.  So we brute-force the entire
(cell re-reading × row subset) space with the dumbest possible loops and
assert the solver reaches exactly the same explanation set.
"""

from fractions import Fraction
from itertools import combinations

from hypothesis import given, settings
from hypothesis import strategies as st

from tallyproof.core.constraints import build_equations, choose_convention, parse_all
from tallyproof.core.ledger import Cell, Ledger, make_row
from tallyproof.core.numerals import render, surface_variants
from tallyproof.core.solver import _search_component


def naive_explanations(prices: list[Fraction], sub: Fraction,
                       surfaces: list[str]) -> tuple[int, set]:
    """(layer, explanations) by unoptimised definition-following search."""
    n = len(prices)
    subsets = [s for r in range(1, n + 1) for s in combinations(range(n), r)]
    layer0 = {("obs", None, s) for s in subsets if sum(prices[i] for i in s) == sub}
    if layer0:
        return 0, layer0
    out = set()
    vals = prices + [sub]
    for k in range(n + 1):
        for v in surface_variants(surfaces[k]):
            if v == vals[k]:
                continue
            trial = list(vals)
            trial[k] = v
            for s in subsets:
                if sum(trial[i] for i in s) == trial[n]:
                    out.add((k, v, s))
    return 1, out


small_ledgers = st.lists(
    st.integers(min_value=1, max_value=99999), min_size=1, max_size=5
).flatmap(
    lambda vals: st.integers(min_value=0, max_value=sum(vals) + 9000).map(
        lambda sub: (vals, sub)
    )
)


@given(small_ledgers)
@settings(max_examples=120, deadline=None)
def test_solver_matches_naive_brute_force(case):
    vals, sub = case
    surfaces = [render(Fraction(v), ".", ",") for v in vals] + [
        render(Fraction(sub), ".", ",")
    ]
    ledger = Ledger(
        doc_id="bf",
        rows=tuple(make_row(i, price=surfaces[i]) for i in range(len(vals))),
        subtotal=Cell("totals.subtotal", surfaces[-1]),
    )
    dec, grp = choose_convention(ledger)
    assign = parse_all(ledger, dec, grp)
    eqs = build_equations(ledger, assign)
    if not eqs:  # a surface failed to parse under the voted convention
        return
    cell_surfaces = {cid: c.surface for cid, c in ledger.cells().items()}
    layer, expls, exhaustive = _search_component(eqs, assign, cell_surfaces)
    assert exhaustive

    # naive search needs values under the same convention
    from tallyproof.core.numerals import parse_with

    prices = [parse_with(s, dec, grp) for s in surfaces[:-1]]
    subv = parse_with(surfaces[-1], dec, grp)
    n_layer, naive = naive_explanations(prices, subv, surfaces)

    assert layer == n_layer
    got = {
        (
            "obs" if e.cell_id is None else int(e.cell_id.split(".")[0][3:])
            if e.cell_id.startswith("row")
            else len(prices),
            e.value,
            tuple(i for i in range(len(prices)) if e.mask >> i & 1),
        )
        for e in expls
    }
    want = set(naive)
    assert got == want
