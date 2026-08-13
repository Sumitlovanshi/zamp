"""Build the constraint graph a receipt's own arithmetic imposes on itself.

Five families, in the order they were measured (eval/report.md):

    L1  qty × unitprice = price                 per row, where all three print
    L2  Σ_{i∈S} price_i = subtotal              S ⊆ rows, membership UNKNOWN
    L2b Σ_{i∈S} price_i + tax + service + discount = total   (when no subtotal)
    L3  subtotal + tax + service + discount = total
    L4  cash − total = change
    L5  Σ qty_i = menuqty

Membership in L2 is unknown because receipts print rows that are *not*
addends — voided lines, modifiers folded into a parent, section repeats.
That unknown is the reason the solver enumerates subsets rather than
summing everything and calling a mismatch an error.

``discount`` is treated as a printed addend (CORD prints it signed, e.g.
``-2.000``), so all linear identities are sums.  An equation is only
*applicable* when every cell it names is present and parseable under the
document's voted convention — an identity you cannot evaluate is not
evidence of anything, and inapplicability is reported, never hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .ledger import Ledger
from .numerals import DOC_CONVENTIONS, parse_with


@dataclass(frozen=True)
class Equation:
    """One applicable identity.  ``terms`` are (coefficient, cell_id) pairs
    summing to zero for linear kinds; L1 is multiplicative and handled by
    kind.  For L2/L2b, ``members`` are the price cells whose membership in
    the sum is the unknown the solver enumerates."""

    eq_id: str
    kind: str  # "L1" | "L2" | "L2b" | "L3" | "L4" | "L5"
    label: str
    cells: tuple[str, ...]
    terms: tuple[tuple[int, str], ...] = ()
    members: tuple[str, ...] = ()  # subset-enumerable price cells (L2/L2b only)


def choose_convention(ledger: Ledger) -> tuple[str, str]:
    """Vote a document-level (decimal, group) convention.

    Scores each convention by how many identities it makes true, exactly
    as measured: Σlines=subtotal +2, Σlines=total +1, cash−total=change +2,
    each row identity +1.  Identity ties (nothing balances yet) are broken
    by penalising readings whose fractional part is exactly 3 digits — a
    3-digit "decimal" is almost always a mis-grouped thousands separator —
    and remaining ties resolve in DOC_CONVENTIONS order.  (The exploratory
    study's identity-only vote elected comma-grouping on 193 of 200 CORD
    documents; the shipping rule's own census is in eval/report.md's product
    section — the tie-break decides most documents, because additive
    identities are scale-blind.)
    """

    def three_digit_fraction_penalty(dec: str, grp: str) -> int:
        n = 0
        for cell in ledger.cells().values():
            if parse_with(cell.surface, dec, grp) is None:
                continue
            tail = cell.surface.rsplit(dec, 1)
            if len(tail) == 2 and len(tail[1].strip()) == 3 and tail[1].strip().isdigit():
                n += 1
        return n

    def score(dec: str, grp: str) -> int:
        p = lambda c: None if c is None else parse_with(c.surface, dec, grp)
        pts = 0
        prices = [p(r.price) for r in ledger.rows]
        sub, tot = p(ledger.subtotal), p(ledger.total)
        if prices and all(v is not None for v in prices):
            if sub is not None and sum(prices) == sub:
                pts += 2
            if tot is not None and sum(prices) == tot:
                pts += 1
        cash, change = p(ledger.cash), p(ledger.change)
        if None not in (cash, change, tot) and cash - tot == change:
            pts += 2
        for r in ledger.rows:
            q, u, pr = p(r.qty), p(r.unitprice), p(r.price)
            if None not in (q, u, pr) and q * u == pr:
                pts += 1
        return pts

    return max(
        DOC_CONVENTIONS,
        key=lambda c: (score(*c), -three_digit_fraction_penalty(*c)),
    )


def parse_all(ledger: Ledger, dec: str, grp: str) -> dict[str, Fraction]:
    """Observed assignment x⁰: every cell that parses under the convention."""
    out: dict[str, Fraction] = {}
    for cell_id, cell in ledger.cells().items():
        v = parse_with(cell.surface, dec, grp)
        if v is not None:
            out[cell_id] = v
    return out


def build_equations(ledger: Ledger, assign: dict[str, Fraction]) -> list[Equation]:
    """Every identity the document makes applicable.

    Applicability requires all named cells present AND parsed; the sole
    exception is that tax/service/discount default to 0 *when absent*
    (an absent charge is a printed fact, an unparseable one is not).
    """
    eqs: list[Equation] = []
    ok = lambda cell: cell is not None and cell.cell_id in assign

    # L1 — per-row multiplicative identity
    for r in ledger.rows:
        if ok(r.qty) and ok(r.unitprice) and ok(r.price):
            eqs.append(
                Equation(
                    eq_id=f"L1.row{r.index}",
                    kind="L1",
                    label=f"qty × unit price = line total  (row {r.index + 1})",
                    cells=(r.qty.cell_id, r.unitprice.cell_id, r.price.cell_id),
                )
            )

    price_cells = [r.price.cell_id for r in ledger.rows if r.price is not None]
    all_prices_parse = bool(price_cells) and all(c in assign for c in price_cells)

    # A charge cell that is PRINTED but unparseable must make the equation
    # inapplicable, not silently vanish from it — an identity missing one of
    # its printed terms is a different (and wrong) identity.
    charge_cells = [c for c in (ledger.tax, ledger.service, ledger.discount) if c is not None]
    charges_parse = all(c.cell_id in assign for c in charge_cells)
    charges = [(1, c.cell_id) for c in charge_cells if c.cell_id in assign]

    # L2 / L2b — the line chain, with unknown membership
    if all_prices_parse and ok(ledger.subtotal):
        eqs.append(
            Equation(
                eq_id="L2",
                kind="L2",
                label="Σ line totals = subtotal  (over the rows that are addends)",
                cells=(*price_cells, ledger.subtotal.cell_id),
                terms=((-1, ledger.subtotal.cell_id),),
                members=tuple(price_cells),
            )
        )
    elif all_prices_parse and ledger.subtotal is None and ok(ledger.total) and charges_parse:
        eqs.append(
            Equation(
                eq_id="L2b",
                kind="L2b",
                label="Σ line totals + charges = total",
                cells=(*price_cells, *(cid for _, cid in charges), ledger.total.cell_id),
                terms=(*charges, (-1, ledger.total.cell_id)),
                members=tuple(price_cells),
            )
        )

    # L3 — the totals block.  Only applicable when at least one charge
    # between subtotal and total is printed (with none printed, both
    # inclusive-tax and unprinted-tax receipts are legitimate, so equality
    # is not an identity there) AND every printed charge parses.
    if ok(ledger.subtotal) and ok(ledger.total) and charges_parse and charges:
        eqs.append(
            Equation(
                eq_id="L3",
                kind="L3",
                label="subtotal + tax + service + discount = total",
                cells=(
                    ledger.subtotal.cell_id,
                    *(cid for _, cid in charges),
                    ledger.total.cell_id,
                ),
                terms=((1, ledger.subtotal.cell_id), *charges, (-1, ledger.total.cell_id)),
            )
        )

    # L4 — the payment anchor: independent of every line item
    if ok(ledger.cash) and ok(ledger.change) and ok(ledger.total):
        eqs.append(
            Equation(
                eq_id="L4",
                kind="L4",
                label="cash − total = change",
                cells=(ledger.cash.cell_id, ledger.total.cell_id, ledger.change.cell_id),
                terms=(
                    (1, ledger.cash.cell_id),
                    (-1, ledger.total.cell_id),
                    (-1, ledger.change.cell_id),
                ),
            )
        )

    # L5 — the quantity anchor: constrains cells money equations barely touch
    qty_cells = [r.qty.cell_id for r in ledger.rows if r.qty is not None]
    if (
        ok(ledger.menuqty)
        and ledger.rows
        and len(qty_cells) == len(ledger.rows)
        and all(c in assign for c in qty_cells)
    ):
        eqs.append(
            Equation(
                eq_id="L5",
                kind="L5",
                label="Σ qty = item count",
                cells=(*qty_cells, ledger.menuqty.cell_id),
                terms=(*((1, c) for c in qty_cells), (-1, ledger.menuqty.cell_id)),
            )
        )

    return eqs
