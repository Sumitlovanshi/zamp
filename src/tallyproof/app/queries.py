"""The queryable half, with census semantics.

An aggregate over verified data must say what it is made of.  A batch
total here is never one number: it is a certified sum over the cells
arithmetic pinned, an interval over the cells it could not choose
between, and a named exclusion list for the cells nothing constrains —
so "how much did I spend?" cannot silently include a number nobody
proved.  This is the semantics the solver's verdicts exist to feed.
"""

from __future__ import annotations

import csv
import io
from fractions import Fraction

from .store import DocRecord

CERTIFIED = ("PROVEN", "REPAIRED")


def _num(value: str) -> Fraction | None:
    try:
        return Fraction(value.replace(",", "").replace(" ", "").replace("'", ""))
    except (ValueError, ZeroDivisionError):
        return None


def _doc_total(rec: DocRecord) -> dict:
    """The best available 'total' cell for one document, with its status."""
    cells = rec.certificate["cells"]
    for cid in ("totals.total", "totals.subtotal"):
        if cid in cells:
            cell = cells[cid]
            values = [_num(v) for v in (cell["alternatives"] or [cell["value"]])]
            values = [v for v in values if v is not None]
            return {
                "doc_id": rec.doc_id,
                "name": rec.name,
                "cell_id": cid,
                "verdict": cell["verdict"],
                "value": _num(cell["value"]) if cell["value"] else None,
                "lo": min(values) if values else None,
                "hi": max(values) if values else None,
            }
    return {"doc_id": rec.doc_id, "name": rec.name, "cell_id": None,
            "verdict": "ABSENT", "value": None, "lo": None, "hi": None}


def batch_summary(docs: list[DocRecord]) -> dict:
    """Everything the batch page shows: census, certified spend, interval."""
    census = {"PROVEN": 0, "REPAIRED": 0, "AMBIGUOUS": 0, "UNVERIFIED": 0, "UNCONSTRAINED": 0}
    review = total_cells = 0
    for rec in docs:
        for cell in rec.certificate["cells"].values():
            census[cell["verdict"]] += 1
            total_cells += 1
            if cell["verdict"] != "PROVEN":
                review += 1

    totals = [_doc_total(r) for r in docs]
    certified = [t for t in totals if t["verdict"] in CERTIFIED and t["value"] is not None]
    ambiguous = [t for t in totals if t["verdict"] == "AMBIGUOUS" and t["lo"] is not None]
    excluded = [t for t in totals if t not in certified and t not in ambiguous]

    spend = sum((t["value"] for t in certified), Fraction(0))
    lo = spend + sum((t["lo"] for t in ambiguous), Fraction(0))
    hi = spend + sum((t["hi"] for t in ambiguous), Fraction(0))

    return {
        "n_docs": len(docs),
        "total_cells": total_cells,
        "review": review,
        "census": census,
        "spend_certified": spend,
        "spend_interval": (lo, hi) if ambiguous else None,
        "n_certified": len(certified),
        "n_ambiguous": len(ambiguous),
        "excluded": excluded,
        "per_doc": totals,
    }


def _csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection: filenames and OCR'd item
    text are attacker-controlled, and Excel executes cells starting with
    = + - @ (or tab/CR variants) on open."""
    v = str(value)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def batch_csv(docs: list[DocRecord]) -> str:
    """Every cell of every document, verdicts attached — the export IS the
    proof status; a spreadsheet loses nothing this system knew."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["doc", "cell_id", "surface_as_printed", "value", "verdict",
                "repaired_from", "alternatives", "identities"])
    for rec in docs:
        for cid, cell in sorted(rec.certificate["cells"].items()):
            w.writerow([
                _csv_safe(rec.name), cid, _csv_safe(cell["surface"]),
                cell["value"], cell["verdict"],  # solver-rendered, trusted charset
                cell["repaired_from"],
                " | ".join(cell["alternatives"]),
                " | ".join(cell["equations"]),
            ])
    return buf.getvalue()
