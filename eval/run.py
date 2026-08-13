"""Regenerate every published number from third-party ground truth.

    .venv/bin/python eval/run.py        # writes eval/report.md

Two kinds of tables, kept deliberately separate:

* THE STUDY — a frozen port of the analysis that motivated this build:
  fixed comma-grouping convention, the Σline=subtotal identity only,
  layered H1→H2→H3 lattice.  These numbers were measured before any
  product code existed and must reproduce forever.  Guarded by
  tests/test_eval_frozen.py.

* THE PRODUCT — the shipping solver (all five identity families,
  per-document convention voting, membership merged into every layer)
  run over the same 200 receipts, plus seeded fault injection for the
  false-repair rate.  The delta between the two is reported, not hidden.

Everything here runs offline from data/cord_gt.json (CORD-v2, CC BY 4.0,
Park et al. 2019).  No model, no network, no image.
"""

from __future__ import annotations

import collections
import io
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tallyproof.core.ledger import Ledger
from tallyproof.core.numerals import (
    CONFUSION,
    candidates,
    parse_with,
    surface_variants,
)
from tallyproof.core.solver import decide
from tallyproof.extract.cord_gt import load_cord

ROOT = Path(__file__).resolve().parents[1]
RAW = json.loads((ROOT / "data" / "cord_gt.json").read_text())
DOCS = [json.loads(s)["gt_parse"] for k in ("test", "validation") for s in RAW[k]]

P = lambda t: None if t is None else parse_with(str(t), ",", ".")  # the study's fixed convention


def rows_of(g):
    m = g.get("menu", [])
    m = m if isinstance(m, list) else [m]
    return [r for r in m if isinstance(r, dict)]


def blk(g, name):
    b = g.get(name, {})
    if isinstance(b, list):
        b = b[0] if b else {}
    return b if isinstance(b, dict) else {}


def study_subset():
    """The 118 receipts with a testable Σline = subtotal under the study convention."""
    out = []
    for g in DOCS:
        rs = rows_of(g)
        ptok = [r.get("price") for r in rs]
        stok = blk(g, "sub_total").get("subtotal_price")
        pv = [P(p) for p in ptok]
        sp = P(stok)
        if not pv or any(v is None for v in pv) or sp is None:
            continue
        out.append((pv, sp, [str(p) for p in ptok], str(stok)))
    return out


# ---------------------------------------------------------------- sections
def sec_ambiguity(w):
    amb = collections.Counter()
    total = 0
    for g in DOCS:
        toks = []
        for r in rows_of(g):
            toks += [r.get(k) for k in ("price", "unitprice", "itemsubtotal", "discountprice")]
        for nm in ("sub_total", "total"):
            toks += list(blk(g, nm).values())
        for t in toks:
            if not isinstance(t, str):
                continue
            c = candidates(t)
            if c:
                total += 1
                amb[len(c)] += 1
    multi = sum(v for k, v in amb.items() if k > 1)
    w("## Numeral ambiguity (readings per money token, grouping-shape-valid)\n")
    w("| tokens | 1 reading | ≥2 readings | ambiguous share |\n|---|---|---|---|\n")
    w(f"| {total} | {amb[1]} | {multi} | **{100*multi/total:.1f}%** |\n")
    w("\nA money token on a real receipt usually does not determine its own value; "
      "the document's arithmetic and convention vote have to.\n\n")
    return {"tokens": total, "ambiguous_pct": round(100 * multi / total, 1)}


def sec_base_rates(w):
    res = {k: [0, 0] for k in (
        "qty x unitprice = price", "sum(lines) = subtotal", "sum(lines) = total",
        "cash - total = change", "subtotal + charges = total", "sum(qty) = item count")}
    conv_votes = collections.Counter()
    CONVS = [(",", "."), (".", ","), (",", " "), (".", " ")]

    def score(g, dec, grp):
        p = lambda t: None if t is None else parse_with(str(t), dec, grp)
        pts = 0
        rs = rows_of(g)
        prices = [p(r.get("price")) for r in rs]
        sp, tp = p(blk(g, "sub_total").get("subtotal_price")), p(blk(g, "total").get("total_price"))
        if prices and all(v is not None for v in prices):
            if sp is not None and sum(prices) == sp:
                pts += 2
            if tp is not None and sum(prices) == tp:
                pts += 1
        cp, ch = p(blk(g, "total").get("cashprice")), p(blk(g, "total").get("changeprice"))
        if None not in (cp, ch, tp) and cp - tp == ch:
            pts += 2
        for r in rs:
            c, u, pr = p(r.get("cnt")), p(r.get("unitprice")), p(r.get("price"))
            if None not in (c, u, pr) and c * u == pr:
                pts += 1
        return pts

    for g in DOCS:
        dec, grp = max(CONVS, key=lambda c: score(g, *c))
        conv_votes[(dec, grp)] += 1
        p = lambda t, dec=dec, grp=grp: None if t is None else parse_with(str(t), dec, grp)
        rs = rows_of(g)
        st, tt = blk(g, "sub_total"), blk(g, "total")
        for r in rs:
            c, u, pr = p(r.get("cnt")), p(r.get("unitprice")), p(r.get("price"))
            if None not in (c, u, pr):
                res["qty x unitprice = price"][1] += 1
                res["qty x unitprice = price"][0] += c * u == pr
        prices = [p(r.get("price")) for r in rs]
        if prices and all(v is not None for v in prices):
            sp = p(st.get("subtotal_price"))
            if sp is not None:
                res["sum(lines) = subtotal"][1] += 1
                res["sum(lines) = subtotal"][0] += sum(prices) == sp
            tp = p(tt.get("total_price"))
            if tp is not None:
                res["sum(lines) = total"][1] += 1
                res["sum(lines) = total"][0] += sum(prices) == tp
        cp, ch, tp = p(tt.get("cashprice")), p(tt.get("changeprice")), p(tt.get("total_price"))
        if None not in (cp, ch, tp):
            res["cash - total = change"][1] += 1
            res["cash - total = change"][0] += cp - tp == ch
        sp, tx = p(st.get("subtotal_price")), p(st.get("tax_price"))
        sv = p(st.get("service_price")) or 0
        dc = p(st.get("discount_price")) or 0
        if None not in (sp, tx, tp):
            res["subtotal + charges = total"][1] += 1
            res["subtotal + charges = total"][0] += sp + tx + sv + dc == tp
        mq = p(tt.get("menuqty_cnt"))
        cnts = [p(r.get("cnt")) for r in rs]
        if mq is not None and cnts and all(c is not None for c in cnts):
            res["sum(qty) = item count"][1] += 1
            res["sum(qty) = item count"][0] += sum(cnts) == mq

    w("## Base rates: how often the HUMAN annotations satisfy each identity\n")
    w("These are the numbers capable of killing the thesis. 85% is not 99%: a naive\n")
    w("verifier that flags every violation is wrong one time in six, which is exactly\n")
    w("why residual *attribution* is the product rather than a red icon.\n\n")
    w("| identity | holds | tested | rate |\n|---|---|---|---|\n")
    out = {}
    for k, (ok, n) in res.items():
        w(f"| `{k}` | {ok} | {n} | **{100*ok/n:.1f}%** |\n")
        out[k] = f"{ok}/{n}"
    votes = ", ".join(f"`{d}{g}` × {n}".replace(" ", "␣") for (d, g), n in conv_votes.most_common())
    w(f"\nDocument convention votes under the STUDY's identity-only rule "
      f"(decimal+group): {votes}. The shipping solver adds a tie-break "
      f"(see the product section), so its votes differ — both are reported.\n\n")
    ok_st, n_st = res["sum(lines) = subtotal"]
    out["subtotal_pct"] = round(100 * ok_st / n_st, 1)
    return out


def sec_study_lattice(w):
    """Frozen port of the exploratory lattice: fixed convention, L2 only, H1→H2→H3."""
    res = collections.Counter()
    layers = collections.Counter()
    for pv, sp, ptok, stok in study_subset():
        n = len(pv)
        subs = [m for m in range(1, 1 << n) if sum(pv[j] for j in range(n) if m >> j & 1) == sp]
        if subs:
            layers["H1 subset"] += 1
            res["unique -> certify" if len(subs) == 1 else "multiple -> AMBIGUOUS"] += 1
            continue
        cells = list(zip(range(n), ptok)) + [(-1, stok)]
        base = pv + [sp]
        fixes = set()
        for k, (idx, tok) in enumerate(cells):
            for v in surface_variants(tok):
                if v == base[k]:
                    continue
                cand = list(base)
                cand[k] = v
                if sum(cand[:-1]) == cand[-1]:
                    fixes.add((idx, str(v)))
        if fixes:
            layers["H2 re-reading"] += 1
            res["unique -> certify" if len(fixes) == 1 else "multiple -> AMBIGUOUS"] += 1
            continue
        joint = set()
        for k, (idx, tok) in enumerate(cells):
            for v in surface_variants(tok):
                if v == base[k]:
                    continue
                cand = list(base)
                cand[k] = v
                pr, s2 = cand[:-1], cand[-1]
                for m in range(1, 1 << n):
                    if sum(pr[j] for j in range(n) if m >> j & 1) == s2:
                        joint.add((idx, str(v), m))
                        break
        if joint:
            layers["H3 joint"] += 1
            res["unique -> certify" if len(joint) == 1 else "multiple -> AMBIGUOUS"] += 1
        else:
            layers["NONE"] += 1
            res["none -> UNEXPLAINED (paper wrong)"] += 1
    n = sum(res.values())
    w("## The study lattice (frozen methodology): Σline=subtotal, fixed convention\n")
    w(f"Over the {n} receipts with a testable line chain:\n\n")
    w("| outcome | docs | share |\n|---|---|---|\n")
    for k, v in res.most_common():
        w(f"| {k} | {v} | **{100*v/n:.1f}%** |\n")
    w("\n| explaining layer | docs |\n|---|---|\n")
    for k, v in layers.most_common():
        w(f"| {k} | {v} |\n")
    w("\n")
    return {
        "n": n,
        **{k: v for k, v in res.items()},
        "certify_pct": round(100 * res["unique -> certify"] / n, 1),
        "ambiguous_pct": round(100 * res["multiple -> AMBIGUOUS"] / n, 1),
        "unexplained_pct": round(100 * res["none -> UNEXPLAINED (paper wrong)"] / n, 1),
    }


def sec_segmentation(w):
    counts = collections.Counter()
    for pv, sp, *_ in study_subset():
        n = len(pv)
        subs = sum(1 for m in range(1, 1 << n) if sum(pv[j] for j in range(n) if m >> j & 1) == sp)
        counts[min(subs, 5)] += 1
    n = sum(counts.values())
    multi = sum(v for k, v in counts.items() if k > 1)
    w("## Segmentation uniqueness (exhaustive over all 2^n row subsets)\n")
    w("| closing subsets | docs | share |\n|---|---|---|\n")
    for k in sorted(counts):
        w(f"| {k} | {counts[k]} | {100*counts[k]/n:.1f}% |\n")
    w(f"\n**{100*multi/n:.1f}%** of receipts have more than one row-grouping that balances.\n")
    w("A unique closing subset is therefore a *precondition* of PROVEN, not an assumption —\n")
    w("without the check, one document in twenty is certified against an unproven constraint set.\n\n")
    return {"multi_pct": round(100 * multi / n, 1)}


def sec_soundness(w):
    n = alt = 0
    for pv, sp, ptok, stok in study_subset():
        if sum(pv) != sp:
            continue
        n += 1
        base = pv + [sp]
        cells = list(zip(range(len(pv)), ptok)) + [(-1, stok)]
        found = False
        for k, (idx, tok) in enumerate(cells):
            for v in surface_variants(tok):
                if v == base[k]:
                    continue
                cand = list(base)
                cand[k] = v
                if sum(cand[:-1]) == cand[-1]:
                    found = True
        alt += found
    w("## Soundness: do balancing receipts admit an ALTERNATIVE balancing re-reading?\n")
    w(f"Of {n} receipts whose human annotation balances, **{alt}** admit any alternative\n")
    w("re-reading (within the declared model) that also balances.\n")
    w("Reported honestly as an exact one-sided bound (Clopper-Pearson, rounded up):\n")
    w(f"at 95% confidence the true rate is **< {pct_ceil(binom_upper(alt, n))}%** on this "
      "sample — never as a flat 0%.\n\n")
    return {"n": n, "alternatives": alt, "bound_pct": pct_ceil(binom_upper(alt, n))}


def sec_product(w):
    dist = collections.Counter()
    cell_counts = collections.Counter()
    ship_votes = collections.Counter()
    for led in load_cord():
        cert = decide(led)
        ship_votes[cert.convention] += 1
        dist[cert.doc_verdict] += 1
        for k, v in cert.counts().items():
            cell_counts[k] += v
    n = sum(dist.values())
    w("## The shipping solver, all five identity families, all 200 receipts\n")
    w("Differences from the study are deliberate and favourable: the solver votes the\n")
    w("convention per document (the study fixed comma-grouping) and merges membership\n")
    w("into every layer (the study tried re-readings against the full row set first).\n")
    w("Both changes find strictly more explanations, so fewer documents are declared\n")
    w("UNEXPLAINED and uniqueness is demanded across a *larger* space before certifying.\n\n")
    w("| document verdict | docs | share |\n|---|---|---|\n")
    for k in ("TIES_OUT", "REPAIRED", "AMBIGUOUS", "UNEXPLAINED", "NO_STRUCTURE"):
        w(f"| {k} | {dist[k]} | {100*dist[k]/n:.1f}% |\n")
    total_cells = sum(cell_counts.values())
    w("\n| cell verdict | cells | share |\n|---|---|---|\n")
    for k in ("PROVEN", "REPAIRED", "AMBIGUOUS", "UNVERIFIED", "UNCONSTRAINED"):
        w(f"| {k} | {cell_counts[k]} | {100*cell_counts[k]/total_cells:.1f}% |\n")
    votes = ", ".join(
        f"`{d}{g}` × {n}".replace(" ", "␣") for (d, g), n in ship_votes.most_common()
    )
    w(f"\nConvention votes under the SHIPPING rule (identities, then the "
      f"3-digit-fraction tie-break): {votes}. Ties are common because additive "
      f"identities are scale-blind (degree-1 homogeneous), so the tie-break — "
      f"not the identities — decides many documents' display scale.\n\n")
    return {"docs": dict(dist), "cells": dict(cell_counts),
            "ship_votes": {f"{d}{g}": n for (d, g), n in ship_votes.items()}}


CORRUPTIBLE = ("row", "totals.")


def _glyph_corrupt(surface: str, rng: random.Random) -> str | None:
    pos = [i for i, ch in enumerate(surface) if CONFUSION.get(ch)]
    if not pos:
        return None
    i = rng.choice(pos)
    return surface[:i] + rng.choice(CONFUSION[surface[i]]) + surface[i + 1 :]


def _transpose_corrupt(surface: str, rng: random.Random) -> str | None:
    pos = [i for i in range(len(surface) - 1)
           if surface[i].isdigit() and surface[i + 1].isdigit() and surface[i] != surface[i + 1]]
    if not pos:
        return None
    i = rng.choice(pos)
    return surface[:i] + surface[i + 1] + surface[i] + surface[i + 2 :]


def inject(led: Ledger, cell_id: str, new_surface: str) -> Ledger:
    d = led.to_dict()
    for r in d["rows"]:
        for f in ("qty", "unitprice", "price"):
            if r[f] and r[f]["cell_id"] == cell_id:
                r[f]["surface"] = new_surface
    for f in ("subtotal", "tax", "service", "discount", "total", "cash", "change", "menuqty"):
        if d[f] and d[f]["cell_id"] == cell_id:
            d[f]["surface"] = new_surface
    return Ledger.from_dict(d)


def run_faults(seed: int = 20260811, per_doc: int = 2):
    """Seeded single-fault injection into receipts the solver fully certifies."""
    rng = random.Random(seed)
    stats = {
        "in_model": collections.Counter(),
        "out_of_model": collections.Counter(),
    }
    for led in load_cord():
        base = decide(led)
        if base.doc_verdict != "TIES_OUT":
            continue
        proven = [
            (cid, rep.surface, rep.value)
            for cid, rep in base.cells.items()
            if rep.verdict == "PROVEN" and not cid.endswith(".qty")
        ]
        if not proven:
            continue
        for kind, corrupt in (("in_model", _glyph_corrupt), ("out_of_model", _transpose_corrupt)):
            for cid, surface, true_value in rng.sample(proven, min(per_doc, len(proven))):
                bad = corrupt(surface, rng)
                if bad is None or bad == surface:
                    continue
                cert = decide(inject(led, cid, bad))
                rep = cert.cells[cid]
                s = stats[kind]
                s["injected"] += 1
                if cert.doc_verdict == "TIES_OUT":
                    if rep.verdict == "UNVERIFIED":
                        # corruption produced glyphs with no admissible reading;
                        # the identity became inapplicable but the cell itself is
                        # flagged and sits in the review queue — caught, not missed
                        s["flagged unreadable (in review queue)"] += 1
                    else:
                        # the one genuinely bad outcome short of a false repair:
                        # a different value that still satisfies every identity
                        s["UNDETECTED (balances under a different value)"] += 1
                elif any(
                    r.verdict == "REPAIRED"
                    and not (r.cell_id == cid and r.value == true_value)
                    for r in cert.cells.values()
                ):
                    # ANY repair that is not exactly "the corrupted cell back to
                    # its true value" is a false repair — checked before crediting
                    s["FALSE REPAIR"] += 1
                elif rep.verdict == "REPAIRED" and rep.value == true_value:
                    s["repaired correctly"] += 1
                elif cert.doc_verdict == "AMBIGUOUS":
                    s["abstained (ambiguous)"] += 1
                else:
                    s["flagged unexplained"] += 1
    return stats


def binom_upper(k: int, n: int, conf: float = 0.95) -> float:
    """Exact one-sided Clopper-Pearson upper bound on p, given k failures
    in n trials: the p where P(X <= k) = 1 - conf.  Reduces to the familiar
    1 - alpha^(1/n) at k = 0.  Pure stdlib, bisection."""
    from math import comb

    alpha = 1 - conf

    def cdf(p: float) -> float:
        return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))

    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if cdf(mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def pct_ceil(p: float) -> float:
    """Percent, rounded UP to one decimal — a published '< x%' must be true."""
    from math import ceil

    return ceil(p * 1000) / 10


def sec_faults(w):
    stats = run_faults()
    w("## Seeded fault injection (the false-repair rate)\n")
    w("One corruption per trial, injected into receipts the solver fully certifies,\n")
    w("on cells it had marked PROVEN. `in_model` = single-glyph OCR confusion (the\n")
    w("declared fault model); `out_of_model` = adjacent-digit transposition, which the\n")
    w("reading model deliberately excludes — the solver must abstain or flag, never guess.\n\n")
    w("Scope, disclosed: trials run only on documents the solver certifies end-to-end\n")
    w("(TIES_OUT), only on money cells it marked PROVEN (qty cells excluded — a\n")
    w("single-glyph qty corruption usually just breaks parsing), at most 2 per document.\n")
    w("Corruptions of already-flagged cells would measure nothing: they are flagged.\n\n")
    out = {}
    for kind, s in stats.items():
        n = s["injected"]
        w(f"**{kind}** ({n} trials):\n\n| outcome | trials | share |\n|---|---|---|\n")
        for k, v in s.most_common():
            if k != "injected":
                w(f"| {k} | {v} | {100*v/n:.1f}% |\n")
        fr = s["FALSE REPAIR"]
        bound = pct_ceil(binom_upper(fr, n))
        s["bound_pct"] = bound
        w(f"\nFalse repairs: **{fr}/{n}** — exact one-sided 95% upper bound on the "
          f"true rate: **< {bound}%** (Clopper-Pearson, rounded up).\n\n")
        out[kind] = dict(s)
    return out


def main() -> dict:
    buf = io.StringIO()
    w = buf.write
    w("# Tallyproof — measured evidence\n\n")
    w("Every number below is computed from third-party ground truth "
      "(CORD-v2, Park et al. 2019, CC BY 4.0 — 200 real photographed receipts, "
      "human-annotated by Naver Clova) with **no model, no network and no image "
      "in the loop**. Regenerate with `make eval`; CI fails if this file drifts "
      "from the code that claims it.\n\n")
    summary = {}
    summary["ambiguity"] = sec_ambiguity(w)
    summary["base_rates"] = sec_base_rates(w)
    summary["study"] = sec_study_lattice(w)
    summary["segmentation"] = sec_segmentation(w)
    summary["soundness"] = sec_soundness(w)
    summary["product"] = sec_product(w)
    summary["faults"] = sec_faults(w)
    (ROOT / "eval" / "report.md").write_text(buf.getvalue())
    (ROOT / "eval" / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(buf.getvalue())
    return summary


if __name__ == "__main__":
    main()
