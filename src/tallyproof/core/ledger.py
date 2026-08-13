"""The Ledger contract: the single boundary between extraction and proof.

A ``Ledger`` is what any extractor must produce and the only thing the
solver ever sees.  Two producers implement it — ``extract.cord_gt``
(third-party human annotations, used for every published number) and
``extract.vlm`` (a vision model, used for live uploads).  The solver
cannot tell them apart, which is the anti-circularity guarantee: nothing
in ``tallyproof.core`` imports an extractor, an HTTP client, or an image
library, and CI fails if that ever changes (tests/test_purity.py).

Cells carry *surfaces* — the numeral exactly as printed, separators and
all — never parsed values.  Parsing is the solver's job, because which
value a surface denotes is precisely what is in dispute.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    """One printed numeral: where it sits in the schema, and its glyphs."""

    cell_id: str  # e.g. "row2.price", "totals.total"
    surface: str  # exactly as printed: "12,000", "(1.50)", "60.000"


@dataclass(frozen=True)
class Row:
    """One line item.  Any cell may be absent — most receipts omit some."""

    index: int
    name: str = ""
    qty: Cell | None = None
    unitprice: Cell | None = None
    price: Cell | None = None  # the line total


@dataclass(frozen=True)
class Ledger:
    """A receipt reduced to its numerals.  The contract, version 1."""

    doc_id: str
    rows: tuple[Row, ...] = ()
    subtotal: Cell | None = None
    tax: Cell | None = None
    service: Cell | None = None
    discount: Cell | None = None  # stored as printed; treated as an addend (CORD prints signed)
    total: Cell | None = None
    cash: Cell | None = None
    change: Cell | None = None
    menuqty: Cell | None = None  # printed count of items, e.g. "3 item(s)"
    merchant: str = ""
    currency_hint: str = ""

    def cells(self) -> dict[str, Cell]:
        """Every present cell, keyed by cell_id."""
        out: dict[str, Cell] = {}
        for row in self.rows:
            for f in ("qty", "unitprice", "price"):
                cell = getattr(row, f)
                if cell is not None:
                    out[cell.cell_id] = cell
        for f in ("subtotal", "tax", "service", "discount", "total", "cash", "change", "menuqty"):
            cell = getattr(self, f)
            if cell is not None:
                out[cell.cell_id] = cell
        return out

    def to_dict(self) -> dict:
        def c(cell: Cell | None) -> dict | None:
            return None if cell is None else {"cell_id": cell.cell_id, "surface": cell.surface}

        return {
            "version": 1,
            "doc_id": self.doc_id,
            "merchant": self.merchant,
            "currency_hint": self.currency_hint,
            "rows": [
                {
                    "index": r.index,
                    "name": r.name,
                    "qty": c(r.qty),
                    "unitprice": c(r.unitprice),
                    "price": c(r.price),
                }
                for r in self.rows
            ],
            **{
                f: c(getattr(self, f))
                for f in (
                    "subtotal",
                    "tax",
                    "service",
                    "discount",
                    "total",
                    "cash",
                    "change",
                    "menuqty",
                )
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> Ledger:
        def c(v: dict | None) -> Cell | None:
            return None if v is None else Cell(cell_id=v["cell_id"], surface=v["surface"])

        return cls(
            doc_id=d["doc_id"],
            merchant=d.get("merchant", ""),
            currency_hint=d.get("currency_hint", ""),
            rows=tuple(
                Row(
                    index=r["index"],
                    name=r.get("name", ""),
                    qty=c(r.get("qty")),
                    unitprice=c(r.get("unitprice")),
                    price=c(r.get("price")),
                )
                for r in d.get("rows", [])
            ),
            **{
                f: c(d.get(f))
                for f in (
                    "subtotal",
                    "tax",
                    "service",
                    "discount",
                    "total",
                    "cash",
                    "change",
                    "menuqty",
                )
            },
        )


def make_row(index: int, name: str = "", qty: str | None = None,
             unitprice: str | None = None, price: str | None = None) -> Row:
    """Convenience constructor used by extractors and tests."""
    return Row(
        index=index,
        name=name,
        qty=Cell(f"row{index}.qty", qty) if qty is not None else None,
        unitprice=Cell(f"row{index}.unitprice", unitprice) if unitprice is not None else None,
        price=Cell(f"row{index}.price", price) if price is not None else None,
    )
