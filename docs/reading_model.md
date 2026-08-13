# The declared reading model

Every claim Tallyproof makes has the form *"within the declared reading
model, exactly N explanations exist."*  This file **is** that model.  The
word "complete" anywhere in this repo means complete over this space —
nothing more.  Anything outside it (two-glyph errors, digit transposition,
unmodelled grouping conventions) is deliberately out, and the fault-injection
study measures what happens when reality steps outside the model anyway
(`eval/report.md`, out-of-model table: the large majority flagged, and the
~1% that slip through as false repairs are published, not hidden).

## 1. Grouping conventions

A numeral is parsed under a `(decimal, group)` separator pair.  Six pairs
are admitted per token, four may win a document vote:

| decimal | group | example | reads as |
|---|---|---|---|
| `.` | `,` | `1,234.56` | 1234.56 |
| `,` | `.` | `1.234,56` | 1234.56 |
| `,` | ` ` (incl. NBSP U+00A0, NNBSP U+202F) | `1 234,56` | 1234.56 |
| `.` | ` ` | `1 234.56` | 1234.56 |
| `.` | `'` | `1'234.56` | 1234.56 (token-level only) |
| `,` | `'` | `1'234,56` | 1234.56 (token-level only) |

**Shape validity** prunes: leading group 1–3 digits, interior groups exactly
3, digit-only fraction part, at most one decimal separator, no stray
characters.  Negatives: leading minus or full parentheses.  `--5` is junk.

The killer consequence, measured on CORD-v2: **83.5% of real money tokens
admit ≥2 readings** (`60.000` is sixty thousand in Jakarta and sixty in
Boston, both shape-valid).  A document-level *vote* picks the convention
that satisfies the most identities; ties break against readings whose
"decimal part" is exactly 3 digits (almost always a mis-grouped thousands
separator), then by corpus prior (comma-grouping first).

**Deliberately excluded:** the South Asian 2-2-3 grouping (`12,34,567`),
Arabic-Indic digits, and lakh/crore words.  Excluded because the measured
corpora don't exercise them, and an unmeasured convention in the model
would be a claim without evidence.  Adding one = adding it here + rows in
the frozen tests + regenerated eval, in one commit.

## 2. Single-glyph OCR confusion

One glyph per variant, from the thermal-print confusion set:

```
0→8,O   1→7   2→7   3→8   4→9   5→6,S   6→5,8   7→1,2   8→3,0,6   9→4
```

Letter outputs (`O`, `S`) never parse — they model *unreadability*, not
alternative values.

## 3. Separator faults

One separator (`.` or `,`) dropped anywhere — thermal fade.  Spurious
separators are not modelled (measured as unnecessary on CORD).

## Fault budget

**One faulty cell per identity group** (connected component of the
constraint graph).  Layer 0 (zero faults, row-membership free) strictly
precedes layer 1 (one re-read cell × membership) — Occam as a lexicographic
prior, not a weight.  Two-fault windows are out of scope and land in
UNEXPLAINED or AMBIGUOUS, never in a guess; the eval's multi-error honesty
is inherited from this rule.

## Size of the space

For a receipt with n ≤ 13 line rows and m cells:
`2^n` memberships × `m × |variants|` re-readings — under 10⁶ evaluations,
exact `Fraction` arithmetic, milliseconds in practice.  Above 13 rows the
membership sweep degrades to the full set and the certificate says
`exhaustive: false`.  Enumerability is the entire reason receipts were
chosen over bank statements: **a cardinality is a stronger claim than a
posterior**, and it is only available when the space is small enough to
finish.
