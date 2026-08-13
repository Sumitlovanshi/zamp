"""CORD-v2 human annotations → Ledger.

CORD-v2 (Park et al., 2019 — naver-clova-ix/cord-v2, CC BY 4.0) is 1,000
real photographed Indonesian receipts with third-party, human-written
ground truth.  This adapter turns one ``gt_parse`` record into the same
``Ledger`` contract the vision extractor produces, which is what lets
every published number in eval/report.md be computed with **no model and
no image anywhere in the loop**: third-party photos, third-party labels,
our solver.

Field mapping is frozen to what was measured (see sec_base_rates in eval/run.py): a
block that is a list contributes its first element; a value that is not a
string is passed through ``str()`` and simply fails to parse, exactly as
in the measurement scripts, so the published base rates reproduce.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.ledger import Cell, Ledger, Row

DATA = Path(__file__).resolve().parents[3] / "data" / "cord_gt.json"


def _rows_of(g: dict) -> list[dict]:
    menu = g.get("menu", [])
    menu = menu if isinstance(menu, list) else [menu]
    return [r for r in menu if isinstance(r, dict)]


def _blk(g: dict, name: str) -> dict:
    b = g.get(name, {})
    if isinstance(b, list):
        b = b[0] if b else {}
    return b if isinstance(b, dict) else {}


def _cell(cell_id: str, value) -> Cell | None:
    if value is None:
        return None
    return Cell(cell_id, value if isinstance(value, str) else str(value))


def ledger_from_gt(gt_parse: dict, doc_id: str) -> Ledger:
    rows = []
    for i, r in enumerate(_rows_of(gt_parse)):
        name = r.get("nm", "")
        rows.append(
            Row(
                index=i,
                name=name if isinstance(name, str) else str(name),
                qty=_cell(f"row{i}.qty", r.get("cnt")),
                unitprice=_cell(f"row{i}.unitprice", r.get("unitprice")),
                price=_cell(f"row{i}.price", r.get("price")),
            )
        )
    st, tt = _blk(gt_parse, "sub_total"), _blk(gt_parse, "total")
    return Ledger(
        doc_id=doc_id,
        rows=tuple(rows),
        subtotal=_cell("totals.subtotal", st.get("subtotal_price")),
        tax=_cell("totals.tax", st.get("tax_price")),
        service=_cell("totals.service", st.get("service_price")),
        discount=_cell("totals.discount", st.get("discount_price")),
        total=_cell("totals.total", tt.get("total_price")),
        cash=_cell("totals.cash", tt.get("cashprice")),
        change=_cell("totals.change", tt.get("changeprice")),
        menuqty=_cell("totals.menuqty", tt.get("menuqty_cnt")),
    )


def load_cord(splits: tuple[str, ...] = ("test", "validation")) -> list[Ledger]:
    """The 200 evaluation receipts (test + validation), as Ledgers."""
    raw = json.loads(DATA.read_text())
    out = []
    for split in splits:
        for i, s in enumerate(raw[split]):
            gt = json.loads(s)["gt_parse"]
            out.append(ledger_from_gt(gt, doc_id=f"cord-{split}-{i:03d}"))
    return out
