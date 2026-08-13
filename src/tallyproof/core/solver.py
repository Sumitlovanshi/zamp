"""The decision lattice: exhaustive residual attribution, no scores.

Given a Ledger, decide for every printed numeral whether it is

    PROVEN         — pinned by satisfied identities, uniquely within the
                     winning fault layer: at layer 0, the observed reading
                     satisfies everything with a UNIQUE row-membership (all
                     subsets enumerated; re-readings are dominated by the
                     lexicographic prior and not consulted); at layer 1, the
                     full single-cell re-reading space was enumerated,
    REPAIRED       — the observed reading violates the identities, and
                     EXACTLY ONE admissible re-reading of exactly one
                     cell restores them (shown, never silently applied),
    AMBIGUOUS      — two or more explanations fit; the solver refuses to
                     choose and shows all of them,
    UNVERIFIED     — its identities fail and NO admissible explanation
                     exists: the extraction agrees with the pixels and
                     the paper itself does not add up,
    UNCONSTRAINED  — no identity touches it; honesty about the ~third of
                     receipt cells arithmetic cannot reach.

Method — a lexicographic fault-budget search, exhaustive at each layer:

    layer 0   the observed assignment, with row-membership in the subtotal
              sum free (all 2^n subsets enumerated; a unique closing subset
              is a PRECONDITION of PROVEN — 5.1% of real receipts have two)
    layer 1   single-cell re-readings drawn from the declared reading model
              (numerals.surface_variants), crossed with membership

Fewer faults strictly precede more (Occam as a lexicographic prior, not a
weight).  Within a layer the answer is the CARDINALITY of the explanation
set: 1 certifies, ≥2 refuses, 0 proves the document inconsistent.  There
is no threshold anywhere in this file — that is the point.

Independent identities are decided per connected component of the
constraint graph, so a failed line-sum cannot poison a quantity check it
shares no cell with.  Everything is exact Fraction arithmetic; the search
is complete within the declared model (docs/reading_model.md) and the
optimised enumerator is tested against a naive brute force
(tests/test_lattice_complete.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .constraints import Equation, build_equations, choose_convention, parse_all
from .ledger import Ledger
from .numerals import render, surface_variants

# Beyond this many rows the 2^n membership sweep is not exhaustive; only
# the full set is tried and the certificate says so.  CORD's max is 11.
MAX_EXHAUSTIVE_ROWS = 13

DOC_ORDER = ["TIES_OUT", "REPAIRED", "AMBIGUOUS", "UNEXPLAINED", "NO_STRUCTURE"]


@dataclass
class CellReport:
    cell_id: str
    surface: str
    verdict: str  # PROVEN | REPAIRED | AMBIGUOUS | UNVERIFIED | UNCONSTRAINED
    value: str = ""  # certified value (exact decimal string), when one exists
    note: str = ""
    equations: list[str] = field(default_factory=list)  # labels of identities citing this cell
    alternatives: list[str] = field(default_factory=list)  # competing values when AMBIGUOUS
    repaired_from: str = ""  # observed value when verdict == REPAIRED


@dataclass
class ComponentReport:
    verdict: str  # TIES_OUT | REPAIRED | AMBIGUOUS | UNEXPLAINED
    equations: list[str]
    cardinality: int  # size of the winning explanation layer
    layer: int  # 0 = observed reading, 1 = single re-reading
    detail: str = ""
    exhaustive: bool = True


@dataclass
class Certificate:
    doc_id: str
    doc_verdict: str  # TIES_OUT | REPAIRED | AMBIGUOUS | UNEXPLAINED | NO_STRUCTURE
    convention: tuple[str, str]
    cells: dict[str, CellReport]
    components: list[ComponentReport]

    def counts(self) -> dict[str, int]:
        c = {"PROVEN": 0, "REPAIRED": 0, "AMBIGUOUS": 0, "UNVERIFIED": 0, "UNCONSTRAINED": 0}
        for r in self.cells.values():
            c[r.verdict] += 1
        return c

    @property
    def review_count(self) -> int:
        """Cells a human still has to look at: everything not PROVEN."""
        return sum(n for v, n in self.counts().items() if v != "PROVEN")

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "doc_verdict": self.doc_verdict,
            "convention": list(self.convention),
            "counts": self.counts(),
            "review_count": self.review_count,
            "components": [vars(c).copy() for c in self.components],
            "cells": {k: vars(v).copy() for k, v in self.cells.items()},
        }


# --------------------------------------------------------------------------
# explanation search
# --------------------------------------------------------------------------


def _fmt(v: Fraction, dec: str, grp: str) -> str:
    try:
        return render(v, dec, grp)
    except ValueError:  # non-decimal fraction from an exotic reading
        return str(v)


def _residual(eq: Equation, assign: dict[str, Fraction], mask: int) -> Fraction | None:
    """Signed residual of one equation; None if a needed cell is missing."""
    try:
        if eq.kind == "L1":
            q, u, p = (assign[c] for c in eq.cells)
            return q * u - p
        total = Fraction(0)
        for i, cid in enumerate(eq.members):
            if mask >> i & 1:
                total += assign[cid]
        for coef, cid in eq.terms:
            total += coef * assign[cid]
        return total
    except KeyError:
        return None


@dataclass(frozen=True)
class Explanation:
    """One admissible way to satisfy a component: which cell was re-read
    (None at layer 0), to what value, and with which membership mask."""

    cell_id: str | None
    value: Fraction | None
    mask: int


def _closing_masks(
    eqs: list[Equation], assign: dict[str, Fraction], members: tuple[str, ...], exhaustive: bool
) -> list[int]:
    """All member subsets under which every equation holds (mask=0 sentinel
    when no equation enumerates membership).  Empty subsets are excluded:
    a subtotal composed of nothing is not an explanation, it is a shrug."""
    if not members:
        return [0] if all(_residual(eq, assign, 0) == 0 for eq in eqs) else []
    n = len(members)
    masks = range(1, 1 << n) if exhaustive else [(1 << n) - 1]
    out = []
    for m in masks:
        if all(_residual(eq, assign, m) == 0 for eq in eqs):
            out.append(m)
    return out


def _search_component(
    eqs: list[Equation],
    assign: dict[str, Fraction],
    surfaces: dict[str, str],
) -> tuple[int, list[Explanation], bool]:
    """The lattice for one component.  Returns (layer, explanations, exhaustive)."""
    members: tuple[str, ...] = ()
    for eq in eqs:
        if eq.members:
            members = eq.members  # at most one membership equation per component
    exhaustive = len(members) <= MAX_EXHAUSTIVE_ROWS

    # layer 0 — the observed reading
    layer0 = [
        Explanation(None, None, m) for m in _closing_masks(eqs, assign, members, exhaustive)
    ]
    if layer0:
        return 0, layer0, exhaustive

    # layer 1 — exactly one cell re-read within the declared model
    comp_cells = sorted({c for eq in eqs for c in eq.cells})
    out: list[Explanation] = []
    for cid in comp_cells:
        observed = assign[cid]
        for v in surface_variants(surfaces[cid]):
            if v == observed:
                continue
            trial = dict(assign)
            trial[cid] = v
            for m in _closing_masks(eqs, trial, members, exhaustive):
                out.append(Explanation(cid, v, m))
    return 1, out, exhaustive


# --------------------------------------------------------------------------
# verdicts
# --------------------------------------------------------------------------


def _components(eqs: list[Equation]) -> list[list[Equation]]:
    """Connected components of the constraint graph (equations sharing cells)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for eq in eqs:
        root = find(eq.cells[0])
        for c in eq.cells[1:]:
            parent[find(c)] = root
    groups: dict[str, list[Equation]] = {}
    for eq in eqs:
        groups.setdefault(find(eq.cells[0]), []).append(eq)
    return list(groups.values())


def decide(ledger: Ledger) -> Certificate:
    """Attribute every residual; certify what survives.  Pure, exhaustive."""
    dec, grp = choose_convention(ledger)
    assign = parse_all(ledger, dec, grp)
    surfaces = {cid: cell.surface for cid, cell in ledger.cells().items()}
    eqs = build_equations(ledger, assign)

    cells: dict[str, CellReport] = {}
    for cid, cell in ledger.cells().items():
        if cid in assign:
            cells[cid] = CellReport(
                cell_id=cid,
                surface=cell.surface,
                verdict="UNCONSTRAINED",
                value=_fmt(assign[cid], dec, grp),
                note="no identity on this receipt reaches this cell",
            )
        else:
            cells[cid] = CellReport(
                cell_id=cid,
                surface=cell.surface,
                verdict="UNVERIFIED",
                note="no admissible reading under the document's convention",
            )

    comp_reports: list[ComponentReport] = []
    for comp in _components(eqs):
        report = _decide_component(comp, assign, surfaces, cells, dec, grp)
        comp_reports.append(report)

    if not comp_reports:
        doc_verdict = "NO_STRUCTURE"
    else:
        rank = {"TIES_OUT": 0, "REPAIRED": 1, "AMBIGUOUS": 2, "UNEXPLAINED": 3}
        doc_verdict = max((c.verdict for c in comp_reports), key=lambda v: rank[v])

    return Certificate(
        doc_id=ledger.doc_id,
        doc_verdict=doc_verdict,
        convention=(dec, grp),
        cells=cells,
        components=comp_reports,
    )


def _decide_component(
    comp: list[Equation],
    assign: dict[str, Fraction],
    surfaces: dict[str, str],
    cells: dict[str, CellReport],
    dec: str,
    grp: str,
) -> ComponentReport:
    layer, expls, exhaustive = _search_component(comp, assign, surfaces)
    labels = [eq.label for eq in comp]
    comp_cells = sorted({c for eq in comp for c in eq.cells})
    members: tuple[str, ...] = next((eq.members for eq in comp if eq.members), ())

    def eq_labels_for(cid: str) -> list[str]:
        return [eq.label for eq in comp if cid in eq.cells]

    if members and not exhaustive:
        # The membership sweep was truncated, so neither uniqueness ("no other
        # grouping balances") nor inconsistency ("no explanation exists") is
        # actually established.  Certifying anything here would be the exact
        # confident-wrongness this product exists to refuse — so refuse.
        for cid in comp_cells:
            rep = cells[cid]
            rep.equations = eq_labels_for(cid)
            rep.verdict = "UNVERIFIED"
            rep.note = (
                f"too many rows for the exhaustive membership sweep "
                f"(> {MAX_EXHAUSTIVE_ROWS}); uniqueness cannot be established, "
                "so nothing in this identity group is certified — a deliberate "
                "refusal, not a failure"
            )
        return ComponentReport(
            verdict="AMBIGUOUS",
            equations=labels,
            cardinality=len(expls),
            layer=layer,
            detail=(
                f"membership sweep truncated above {MAX_EXHAUSTIVE_ROWS} rows; "
                "refusing to certify rather than claim an unchecked uniqueness"
            ),
            exhaustive=False,
        )

    if not expls:
        # UNEXPLAINED — enumeration is the proof: within the declared model,
        # no single re-reading and no membership makes this paper add up.
        residuals = ", ".join(
            f"{eq.eq_id}: residual {_fmt(_residual(eq, assign, (1 << len(eq.members)) - 1), dec, grp)}"
            for eq in comp
            if _residual(eq, assign, (1 << len(eq.members)) - 1 if eq.members else 0) not in (0, None)
        )
        for cid in comp_cells:
            cells[cid].verdict = "UNVERIFIED"
            cells[cid].equations = eq_labels_for(cid)
            cells[cid].note = (
                "the document itself does not add up: no reading of any single "
                "cell closes the residual, and that was checked exhaustively"
            )
        return ComponentReport(
            verdict="UNEXPLAINED",
            equations=labels,
            cardinality=0,
            layer=layer,
            detail=residuals or "no admissible explanation within the declared reading model",
            exhaustive=exhaustive,
        )

    # distinct re-readings (layer 1) and distinct memberships (either layer)
    readings = {(e.cell_id, e.value) for e in expls}
    masks = {e.mask for e in expls}
    member_stable = {
        cid: len({bool(e.mask >> i & 1) for e in expls}) == 1
        for i, cid in enumerate(members)
    }

    def certify(chosen: Explanation, verdict_repaired: str | None, proven_note: str) -> None:
        trial = dict(assign)
        if chosen.cell_id is not None:
            trial[chosen.cell_id] = chosen.value  # type: ignore[assignment]
        for cid in comp_cells:
            rep = cells[cid]
            rep.equations = eq_labels_for(cid)
            rep.value = _fmt(trial[cid], dec, grp)
            if cid == chosen.cell_id:
                rep.verdict = "REPAIRED"
                rep.repaired_from = _fmt(assign[cid], dec, grp)
                rep.note = verdict_repaired or ""
            elif cid in members and not (chosen.mask >> members.index(cid) & 1):
                if len(rep.equations) <= 1:  # only the membership equation touches it
                    rep.verdict = "UNCONSTRAINED"
                    rep.note = (
                        "printed but not part of the subtotal sum "
                        "(void, modifier, or repeated line)"
                    )
                else:
                    rep.verdict = "PROVEN"
                    rep.note = "outside the subtotal sum; pinned by its other identities"
            else:
                rep.verdict = "PROVEN"
                rep.note = proven_note

    # Note wording is layer-accurate — the certificate must never assert a
    # check that did not run.  At layer 0 the zero-fault reading wins by the
    # lexicographic prior and re-readings are not consulted; at layer 1 the
    # full single-fault re-reading space genuinely was enumerated.
    # (truncated-sweep components were already handled above, so from here on
    # every enumeration claim below is literally true)
    PROVEN_L0 = (
        "the observed reading satisfies every identity with a unique "
        "row-membership (all subsets enumerated); zero-fault readings take "
        "precedence over re-readings, so none were consulted"
    )
    PROVEN_L1 = (
        "exactly one re-reading in the whole component closes the residual — "
        "every alternative single-cell reading was enumerated and fails"
    )

    if len(readings) == 1 and len(masks) == 1:
        e = expls[0]
        if layer == 0:
            certify(e, None, PROVEN_L0)
            return ComponentReport(
                verdict="TIES_OUT",
                equations=labels,
                cardinality=1,
                layer=0,
                detail="observed reading satisfies every identity; membership unique",
                exhaustive=exhaustive,
            )
        certify(
            e,
            "exactly one admissible re-reading closes the residual; "
            "original shown, nothing silently overwritten",
            PROVEN_L1,
        )
        return ComponentReport(
            verdict="REPAIRED",
            equations=labels,
            cardinality=1,
            layer=1,
            detail=f"unique repair: {e.cell_id} → {_fmt(e.value, dec, grp)}",  # type: ignore[arg-type]
            exhaustive=exhaustive,
        )

    # AMBIGUOUS — several explanations fit; show, never choose.
    per_cell_values: dict[str, set[Fraction]] = {}
    for e in expls:
        trial = dict(assign)
        if e.cell_id is not None:
            trial[e.cell_id] = e.value  # type: ignore[assignment]
        for cid in comp_cells:
            per_cell_values.setdefault(cid, set()).add(trial[cid])
    for cid in comp_cells:
        rep = cells[cid]
        rep.equations = eq_labels_for(cid)
        values = per_cell_values[cid]
        membership_varies = cid in members and not member_stable[cid]
        if len(values) > 1:
            rep.verdict = "AMBIGUOUS"
            rep.alternatives = sorted(_fmt(v, dec, grp) for v in values)
            rep.note = "these readings all satisfy the identities; a human must choose"
        elif membership_varies:
            rep.verdict = "AMBIGUOUS"
            rep.note = "more than one grouping of the rows balances; membership unproven"
        else:
            # value stable and membership stable: certified only if every
            # admissible explanation actually has arithmetic TOUCH the cell —
            # a member stably OUTSIDE the balancing subset was never checked
            included = cid not in members or bool(
                next(iter(masks)) >> members.index(cid) & 1
            )
            rep.value = _fmt(next(iter(values)), dec, grp)
            if len(masks) == 1 and included:
                rep.verdict = "PROVEN"
                rep.note = (
                    "identical value and membership across every admissible "
                    "explanation — pinned no matter which one is true"
                )
            elif len(masks) > 1:
                rep.verdict = "AMBIGUOUS"
                rep.note = "value stable, but the balancing row-grouping is not unique"
            else:
                rep.verdict = "AMBIGUOUS"
                rep.note = (
                    "value stable, but every explanation leaves it outside the "
                    "balancing subset; arithmetic never checked it"
                )
    kind = "row-groupings" if layer == 0 else "explanations"
    return ComponentReport(
        verdict="AMBIGUOUS",
        equations=labels,
        cardinality=len(readings) if layer == 1 else len(masks),
        layer=layer,
        detail=f"{max(len(readings), len(masks))} {kind} satisfy the identities; refusing to choose",
        exhaustive=exhaustive,
    )
