# Tallyproof — measured evidence

Every number below is computed from third-party ground truth (CORD-v2, Park et al. 2019, CC BY 4.0 — 200 real photographed receipts, human-annotated by Naver Clova) with **no model, no network and no image in the loop**. Regenerate with `make eval`; CI fails if this file drifts from the code that claims it.

## Numeral ambiguity (readings per money token, grouping-shape-valid)
| tokens | 1 reading | ≥2 readings | ambiguous share |
|---|---|---|---|
| 1312 | 216 | 1096 | **83.5%** |

A money token on a real receipt usually does not determine its own value; the document's arithmetic and convention vote have to.

## Base rates: how often the HUMAN annotations satisfy each identity
These are the numbers capable of killing the thesis. 85% is not 99%: a naive
verifier that flags every violation is wrong one time in six, which is exactly
why residual *attribution* is the product rather than a red icon.

| identity | holds | tested | rate |
|---|---|---|---|
| `qty x unitprice = price` | 46 | 51 | **90.2%** |
| `sum(lines) = subtotal` | 101 | 120 | **84.2%** |
| `sum(lines) = total` | 93 | 177 | **52.5%** |
| `cash - total = change` | 84 | 96 | **87.5%** |
| `subtotal + charges = total` | 66 | 77 | **85.7%** |
| `sum(qty) = item count` | 35 | 36 | **97.2%** |

Document convention votes under the STUDY's identity-only rule (decimal+group): `,.`␣×␣193, `.,`␣×␣7. The shipping solver adds a tie-break (see the product section), so its votes differ — both are reported.

## The study lattice (frozen methodology): Σline=subtotal, fixed convention
Over the 118 receipts with a testable line chain:

| outcome | docs | share |
|---|---|---|
| unique -> certify | 97 | **82.2%** |
| none -> UNEXPLAINED (paper wrong) | 12 | **10.2%** |
| multiple -> AMBIGUOUS | 9 | **7.6%** |

| explaining layer | docs |
|---|---|
| H1 subset | 100 |
| NONE | 12 |
| H2 re-reading | 6 |

## Segmentation uniqueness (exhaustive over all 2^n row subsets)
| closing subsets | docs | share |
|---|---|---|
| 0 | 18 | 15.3% |
| 1 | 94 | 79.7% |
| 2 | 3 | 2.5% |
| 4 | 3 | 2.5% |

**5.1%** of receipts have more than one row-grouping that balances.
A unique closing subset is therefore a *precondition* of PROVEN, not an assumption —
without the check, one document in twenty is certified against an unproven constraint set.

## Soundness: do balancing receipts admit an ALTERNATIVE balancing re-reading?
Of 97 receipts whose human annotation balances, **0** admit any alternative
re-reading (within the declared model) that also balances.
Reported honestly as an exact one-sided bound (Clopper-Pearson, rounded up):
at 95% confidence the true rate is **< 3.1%** on this sample — never as a flat 0%.

## The shipping solver, all five identity families, all 200 receipts
Differences from the study are deliberate and favourable: the solver votes the
convention per document (the study fixed comma-grouping) and merges membership
into every layer (the study tried re-readings against the full row set first).
Both changes find strictly more explanations, so fewer documents are declared
UNEXPLAINED and uniqueness is demanded across a *larger* space before certifying.

| document verdict | docs | share |
|---|---|---|
| TIES_OUT | 134 | 67.0% |
| REPAIRED | 9 | 4.5% |
| AMBIGUOUS | 16 | 8.0% |
| UNEXPLAINED | 29 | 14.5% |
| NO_STRUCTURE | 12 | 6.0% |

| cell verdict | cells | share |
|---|---|---|
| PROVEN | 957 | 54.0% |
| REPAIRED | 9 | 0.5% |
| AMBIGUOUS | 104 | 5.9% |
| UNVERIFIED | 348 | 19.6% |
| UNCONSTRAINED | 353 | 19.9% |

Convention votes under the SHIPPING rule (identities, then the 3-digit-fraction tie-break): `.,`␣×␣129, `,.`␣×␣71. Ties are common because additive identities are scale-blind (degree-1 homogeneous), so the tie-break — not the identities — decides many documents' display scale.

## Seeded fault injection (the false-repair rate)
One corruption per trial, injected into receipts the solver fully certifies,
on cells it had marked PROVEN. `in_model` = single-glyph OCR confusion (the
declared fault model); `out_of_model` = adjacent-digit transposition, which the
reading model deliberately excludes — the solver must abstain or flag, never guess.

Scope, disclosed: trials run only on documents the solver certifies end-to-end
(TIES_OUT), only on money cells it marked PROVEN (qty cells excluded — a
single-glyph qty corruption usually just breaks parsing), at most 2 per document.
Corruptions of already-flagged cells would measure nothing: they are flagged.

**in_model** (266 trials):

| outcome | trials | share |
|---|---|---|
| repaired correctly | 105 | 39.5% |
| abstained (ambiguous) | 80 | 30.1% |
| flagged unreadable (in review queue) | 64 | 24.1% |
| flagged unexplained | 17 | 6.4% |

False repairs: **0/266** — exact one-sided 95% upper bound on the true rate: **< 1.2%** (Clopper-Pearson, rounded up).

**out_of_model** (232 trials):

| outcome | trials | share |
|---|---|---|
| flagged unexplained | 224 | 96.6% |
| abstained (ambiguous) | 5 | 2.2% |
| FALSE REPAIR | 3 | 1.3% |

False repairs: **3/232** — exact one-sided 95% upper bound on the true rate: **< 3.4%** (Clopper-Pearson, rounded up).

