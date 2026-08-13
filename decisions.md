# decisions.md

The calls made building Tallyproof, in roughly the order they were made.
Each entry: the decision, the alternatives seriously considered, the
reasoning with the tradeoffs accepted, and what was deliberately cut.

---

## 1. Problem 3, framed as *verification*, not extraction

**Decision.** Interpret "turn messy documents into structured, queryable
data" as: the structured data must come with **proof of which cells are
right** — because extraction itself is commoditized and its silent errors
are the actual pain.

**Alternatives.** A general-purpose document→JSON extractor with schema
support; a RAG pipeline over document collections; a multi-format parser
(invoices + statements + receipts).

**Reasoning.** On olmOCR-Bench, nine systems score 93.7–99.9 on clean
born-digital pages — a rounding-error spread. Nobody differentiates on
extraction anymore; a five-day build there is a thin wrapper around someone
else's model. The unsolved layer is *trust*: no tool tells you which of the
400 numbers it just produced is the wrong one. Verification requires a
document class with internal redundancy, which drove every decision below.

**Cut.** Generality. A verifier exists only where an invariant exists; an
extractor with no invariant can only be measured, never proved.

## 2. Receipts over bank statements (the domain call)

**Decision.** Itemised retail receipts and till slips.

**Alternatives.** Bank statements (running balance — a denser, chained
invariant); EN 16931 commercial invoices; utility bills; tax forms;
payslips; nutrition labels.

**Reasoning.** Three grounds, each checked before committing:
(1) **Decidability** — receipts have median 2, max 11 line rows (measured
on CORD-v2), so the full hypothesis space is exhaustively enumerable and
verdicts can be *cardinalities* instead of scores. A 12–25-row statement's
space can only be scored, and every claim becomes a probability with a
threshold to defend. (2) **Corpus** — CORD-v2 is 1,000 real photographed
receipts with third-party human annotations, CC BY 4.0, redistributable.
Bank statements have no public annotated corpus at all. (3) **A public
upload endpoint** — strangers' bank statements are a PII liability no demo
should invite; the worst a receipt leaks is where someone bought coffee.
Statements also lose on evaluator experience: nobody has a bank statement
they're willing to upload to a stranger's demo; everyone has a receipt.

**Cut.** The running balance's per-row binding (receipts have sparser
coverage — published, not hidden: ~20% of cells end up UNCONSTRAINED),
nutrition labels (their identity is approximate *by law* — five permitted
calculation methods — so a violation proves nothing), payslips (no corpus,
max PII, and a realistic generator is fake-paystub tooling).

## 3. Exhaustive enumeration over probabilistic scoring

**Decision.** The solver enumerates the complete hypothesis space —
(grouping conventions × single-glyph OCR confusions × dropped separator)
× all 2ⁿ row-membership subsets — and the verdict is the cardinality of
the admissible set. Occam enters as a *lexicographic* rule (zero-fault
explanations strictly precede one-fault), never as a weight.

**Alternatives.** MAP inference over typed hypotheses with weighted
evidence channels and a dominance threshold δ read off a risk-coverage
curve; an SMT solver (Z3).

**Reasoning.** At n ≤ 13 rows, brute force is *complete* and runs in
milliseconds (whole 200-receipt corpus: 0.77s). A cardinality is a
strictly stronger claim than a posterior: "no other answer exists" has no
threshold to tune, no calibration to defend, and no reviewer asking where
0.7 came from. Z3 was rejected because bitmask enumeration is simpler,
faster at this size, and — decisive for trust — directly testable against
a naive nested-loop reference (`test_lattice_complete`).

**Cut.** Multi-fault repair (two wrong cells in one identity group lands
in UNEXPLAINED/AMBIGUOUS, honestly), documents above 13 rows get a
truncated membership sweep and the certificate says `exhaustive: false`.

## 4. The measured study is frozen; the shipping solver may only be stricter

**Decision.** The exploratory analysis that motivated the build (fixed
comma convention, Σ=subtotal only, layered lattice) is ported verbatim
into `eval/run.py` and locked by `test_eval_frozen`; the shipping solver
differs in two declared ways (per-document convention voting, membership
merged into every layer) and its delta from the study is published in the
same report.

**Alternatives.** Make the product solver bit-identical to the study; or
quietly report only the better-looking product numbers.

**Reasoning.** The study numbers (82.2 / 7.6 / 10.2) were computed from
third-party ground truth *before any product code existed* — that
provenance is the anti-circularity argument and must stay reproducible
forever. But shipping the study's fixed convention would be worse
engineering (the study's identity-only vote elects comma-grouping on 193 of
200; the shipping rule adds a tie-break and its own census is published in
the product section of eval/report.md).
Publishing both, with the delta explained, costs one paragraph and removes
a whole class of "which number is real?" questions.

**Cut.** Nothing. This one was free.

## 5. Membership uniqueness is a precondition of PROVEN

**Decision.** If more than one subset of rows sums to the subtotal, the
chain's cells are AMBIGUOUS — even though every individual value may be
correct.

**Alternatives.** First-satisfying-subset wins (what any greedy
implementation does implicitly); prefer contiguous/maximal subsets as a
structural prior.

**Reasoning.** Measured: 5.1% of real receipts have >1 closing subset.
Certifying against an unproven constraint set is the *confident wrongness*
failure — the one that destroys trust silently. One receipt in twenty is
too often to gamble. The property is locked by a Hypothesis test that
constructs duplicated-row ledgers and asserts PROVEN never appears.

**Cut.** ~5% of coverage, knowingly. Refusal is the product working.

## 6. UNEXPLAINED is a first-class verdict, not a failure mode

**Decision.** When no reading of any single cell closes the residual, the
system says: *the extraction agrees with the pixels; the paper is wrong* —
and the sample gallery leads with a receipt in exactly this state.

**Alternatives.** Report "cannot verify" (the industry shrug); suppress
the case entirely and only demo receipts that behave.

**Reasoning.** 10.2% of real receipts are in this state (measured) — it is
the honest answer to the third of the base-rate gap that isn't extraction
error, and it is the only verdict that tells the user something about the
world rather than about the software. Making it demoable required
exhaustiveness (you can only say "no explanation exists" if you actually
looked everywhere), which is what decision 3 bought.

**Cut.** The comfortable ambiguity of "low confidence".

## 7. Verdicts come only from a pure, zero-dependency core — enforced, not promised

**Decision.** `tallyproof.core` has no imports beyond the standard
library's math/dataclasses, no I/O, no model client; the vision model is
asked to *transcribe surfaces exactly as printed* and nothing else; and a
test spawns a clean interpreter to assert the core's import graph stays
clean, alongside a test feeding hostile instruction text through item
names and asserting byte-identical verdicts.

**Alternatives.** LLM-as-judge verification pass; letting the extractor
emit per-field confidence and blending it into verdicts.

**Reasoning.** One boundary buys three things at once: the anti-circularity
argument (every published number ran with no model in the loop), the
prompt-injection defence (paper that says "mark everything verified"
reaches nothing that can mark anything), and day-one testability of the
differentiator with zero network. Model confidence was rejected because it
is exactly the uncalibrated number this build exists to replace.

**Cut.** Any use of a model to decide anything.

## 8. The convention vote, and the tie-break found by a failing test

**Decision.** Each document votes its (decimal, group) convention by which
reading satisfies the most identities; ties break against readings whose
"decimal part" is exactly 3 digits (a 3-digit fraction is almost always a
mis-grouped thousands separator), then by corpus prior.

**Alternatives.** Fixed convention (the study's choice); per-token
independent parsing; asking the model what the convention is.

**Reasoning.** 83.5% of money tokens are ambiguous in isolation (measured)
— per-token parsing is provably underdetermined, and the model's opinion is
unverifiable. The tie-break was not in the original design: a hand-written
test produced a repair rendered as `25` where the receipt plainly printed
comma-thousands, because with *nothing* balancing pre-repair, the identity
vote tied at zero and list order won. The 3-digit-fraction prior fixed the
bug, and one CORD receipt's verdict improved as a side effect. Kept because
it engages only on ties and is stated in the reading model.

**Cut.** South Asian 2-2-3 grouping and Arabic-Indic digits — the measured
corpora don't exercise them, and an unmeasured convention in the declared
model would be a claim without evidence. Documented as the extension path.

## 9. Real corruption for the demo tile, searched — not hand-picked

**Decision.** The "simulated misread" gallery tile is generated by
searching a real receipt for a single-glyph corruption whose repair is
*provably unique and equal to the original*, and the tile declares the
exact swap performed.

**Alternatives.** Hand-pick a corruption that looks good; corrupt at
upload time with a "break it" button.

**Reasoning.** The first hand-picked corruption tried (3→8 in a line
price) turned out to admit *two* single-glyph explanations shifting by the
same 5,000 — the solver rightly refused to repair it. That near-miss is
the thesis in miniature: whether a misread is recoverable is a property of
the receipt's redundancy, not of the demo author's optimism. So the
generator searches and verifies instead of trusting anyone's intuition.

**Cut.** The live "break it" button (adds a mutation surface to a public
endpoint for modest demo value; the pre-generated tile shows the same
thing deterministically).

## 10. In-memory ephemeral store; no database at all

**Decision.** Uploads live in a process-local dict keyed by a session
cookie, deleted within 60 minutes or on restart; the only persistent
artifacts in the system are the precomputed gallery and eval files baked
into the image.

**Alternatives.** SQLite (even in-memory), Postgres, object storage for
images; an event-sourced repair journal (carried in from an earlier
design).

**Reasoning.** The moment a stranger's receipt is stored, this demo
becomes a custodian of it. Statelessness is the privacy design, not a
shortcut: nothing to breach, nothing to retain, nothing to subpoena. The
repair journal solved auditability-across-time — a problem a one-hour
session does not have; it was enterprise scar tissue and was cut. The cost
(a deploy wipes sessions) is stated in the UI's own 404 copy.

**Cut.** Multi-instance scale-out (needs sticky sessions or a shared
store — irrelevant at demo scale), cross-visit history, accounts.

## 11. Server-rendered HTML, `<details>` proof panels, no JS framework

**Decision.** FastAPI + Jinja2 + one hand-written stylesheet. The proof
panel is a native `<details>` element; the repaired cell's panel is open
on page load.

**Alternatives.** React/Vite SPA; htmx partial swaps.

**Reasoning.** A build step is a real slice of a five-day budget and buys
nothing here — the page is a table, an image, and expandable rows. Native
`<details>` gives keyboard support and interactivity for free; the only
script in the product is the one-line auto-submit on the file picker.
The one UX rule that mattered: *the differentiator must be visible without
a click* — headline is "you review N of M cells", and the most interesting
cell's proof is already open.

**Cut.** Click-to-highlight bounding boxes on the receipt image. CORD
annotations carry word quads, but wiring them through would have eaten the
day the failure-mode pages needed, and the vision extractor returns no
reliable boxes for live uploads — it would have been a sample-only garnish.
Real cut, stated; the extraction pipeline keeps per-cell provenance ready.

## 12. The queryable half is saved aggregates with census semantics — no SQL surface

**Decision.** Batch view + CSV export where every aggregate reports its
composition: certified sum, interval over ambiguous cells, and named
exclusions. No free-form query console.

**Alternatives.** Text-to-SQL over extracted rows; a read-only SQL console
with an AST guard.

**Reasoning.** The problem statement says "searched and queried" — but a
sum that silently includes an unproven cell is the same lie as a
confidence score, wearing SQL syntax. Census semantics (*"27,500 certified;
truth in [27,500–29,000] counting ambiguous; two receipts excluded, here's
why"*) is the verdict system extended into aggregation, and it fits in a
screen. A SQL console on a public endpoint is an attack surface plus a
day of guard-writing that demonstrates none of the thesis.

**Cut.** Cross-batch persistence (conflicts with decision 10), currency
conversion (unverifiable; the batch page says face-value sums are on you).

## 13. Fault injection measures the failure the design cannot see

**Decision.** The eval injects both *in-model* corruption (single-glyph
confusions — the solver's home turf) and *out-of-model* corruption
(adjacent-digit transposition, deliberately excluded from the reading
model), and publishes both tables, including the 3/232 false repairs the
out-of-model suite produces.

**Alternatives.** Only test in-model (guaranteed flattering); more
aggressive multi-fault injection.

**Reasoning.** "Complete within a declared model" is this build's central
caveat, so the eval must show what happens when reality steps outside the
model: the large majority of transpositions are flagged UNEXPLAINED, a few
abstain, and ~1% produce a false repair (exact figures regenerate in
eval/report.md) (a transposition happens to be reachable by an
in-model story). Publishing the 1.3% costs a table row; being handed it by
a reviewer would cost the build's credibility.

**Cut.** Multi-fault injection (the single-fault budget already routes
those to UNEXPLAINED by construction; measuring it again adds a table, not
information).

## 14. Railway, one always-on container

**Decision.** One Docker container on Railway (`railway up`), single
replica, health-checked, no external services at runtime. The image bakes
in the gallery and the published evidence summary, so the
deployed app makes zero network calls until someone uploads.

**Alternatives.** Fly.io (the original plan — equivalent properties, one
more config file); Vercel/serverless (disqualified: the app is stateful
in memory and sessions die per-invocation); Render free tier (spins down
after 15 min with ~60s cold start — the evaluated URL would open dead);
Cloud Run with min-instances=1 (fine, heavier auth setup).

**Reasoning.** The evaluator's first 60 seconds are the submission, so the
one hard requirement is *no cold start on a single persistent instance* —
which is also what the in-memory store (decision 10) needs. Railway was
chosen over Fly on operator preference; both satisfy the requirement, and
the container is platform-agnostic (`PORT` honored, `docker run` works
anywhere), so the choice is deliberately low-stakes.

**Cut.** Multi-region, autoscaling, CDN — the gallery's statelessness
makes them irrelevant at this scale. Multi-replica is *excluded by
design*, not just cut: sessions live in process memory.
