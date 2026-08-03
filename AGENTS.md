# Working on itr-prep

This repository generates India's **Schedule FA** (foreign asset disclosure) and the
Schedule CG, OS, FSI and TR aggregates that depend on it, from US broker exports. Read this
before changing anything.

## Read first, before you assert anything about the law

**Every statutory figure, date and convention is in `rules/AY<year>.json`, with an official
source. Nothing is computed from memory, and nothing is hardcoded at a call site.**

If you need a rate, a limit, a threshold or a deadline:

1. Look for it in the registry: `.venv/bin/python -m itrprep.cli rules`.
2. If it is there, read it through `itrprep/rules.py`. Never inline the value.
3. If it is not there, **add it with a primary citation** rather than writing the number
   into the code. `tests/test_rules_registry.py` fails on an entry with no official source.

**Entries marked `annual` may be out of date.** They are set or revised by each Finance
Act. Before trusting one, check its `applies_to` against the assessment year in question,
and re-verify it against the source if it is behind:

```bash
.venv/bin/python -m itrprep.cli rules --annual-only
```

`docs/ANNUAL-REVIEW.md` is the checklist and explains what specifically to re-check for
each entry. One entry is currently marked `contested` —
`specified_mf_debt_threshold_pct` in `rules/AY2027-28.json` — and a `contested` entry must
not be relied on without being settled first. Do not clear the flag without a primary
source; see `docs/KNOWN-ISSUES.md`.

The tool refuses to build a filing for an assessment year the registry does not cover, and
warns loudly when it is asked for an earlier one than the registry describes. Do not
"fix" either behaviour by loosening it.

## The Act changed. Do not renumber anything without deciding.

The **Income-tax Act, 2025** came into force on 1 April 2026 and repealed the Income-tax
Act, 1961 (s.536(1)). Almost every section number in this repository moved. But s.536(2)(c)
keeps the old Act applying to any tax year beginning before that date, so **AY 2026-27 is
permanently a 1961-Act year** and the return this tool actually filed was filed under the
old Act.

That makes a blanket find-and-replace of section numbers a way of falsifying the record.
Every citation needs a decision:

- **Historical** — describing what was filed for AY 2026-27, or the AY 2026-27 registry
  itself. **Keep the 1961-Act citation.** `docs/RUNBOOK_AY2026-27.md` and the dated entries
  in `CHANGELOG.md` are historical throughout.
- **Forward-looking** — guidance for AY 2027-28 onward, or a statement written as a timeless
  truth. **Cite the Act of 2025**, and give the 1961-Act number alongside it where a reader
  needs the bridge.

The **Black Money Act, 2015 is separate legislation and is not renumbered by any of this.**
Section 43 is still section 43. Do not touch those citations.

`rules/AY2027-28.json` records the old → new mapping on every entry in an `act_transition`
block, and `docs/ANNUAL-REVIEW.md` has the readable table. `tests/test_rules_registry.py`
fails if the old registry stops citing the Income-tax Act, 1961, if the new one stops
recording its transitions, or if an AY 2026-27 entry goes missing from AY 2027-28.

## Source discipline

Primary sources only for any statutory claim: the Income-tax Act or Finance Act text, a
CBDT notification or circular, or the department's own site (`incometaxindia.gov.in`,
`incometax.gov.in`). ClearTax, TaxGuru, Taxmann, Quicko and practitioner blogs are fine for
*finding* a provision and may be quoted in prose, but must never be the cited authority for
a rate, a limit or a date. The registry test enforces the domain rule.

Do not add a rule because it sounds right. If you cannot cite it, say so in the pull
request instead of committing it.

## Never put real data in this repository

Treat this repository as published, whatever its current visibility. It must contain no PAN,
no account numbers, and no real holdings, quantities, prices or dates from anyone's actual
filing.

- Fixtures and examples use invented data. The established placeholders are tickers like
  `CSCO` and grant numbers like `RU100001`. Follow them.
- `work/`, `out/`, `.env` and unlocked documents are gitignored. Keep them that way.
- Document passwords come from `.env`, are read by the code, and must never appear in a log
  line, an exception message, a dry-run listing or a command an agent constructs. See
  `SECURITY.md`. `tests/test_unlock_credentials.py` asserts a failed unlock's output does
  not contain the secret; do not weaken it.

## A model may locate a figure. It may never compute one.

**Every arithmetic operation on real financial data happens in deterministic Python. A
language model may locate and transcribe a figure; it may never subtract, total or reconcile
one.**

This is already how the tool is built. Lot construction, FIFO and same-day matching, peak
values, FX conversion and every rupee figure are computed in `itrprep/`, and no model has ever
been in that path. Writing the rule down closes a door against future drift rather than
describing a change.

It is not a preference. Benchmarks built from real financial filings put small open-weight
models **at or near zero on multi-step calculation**, while the same models handle direct
lookup and transcription far better — and even frontier models carry a 4–8% error rate on
lookup. A 2026 study of document extraction found a deterministic parser with a model
fallback reaching 0.99–1.00 exact match, while the model working alone did *worse than the
parser by itself*. [`docs/AI-ASSISTANCE.md`](docs/AI-ASSISTANCE.md) has the citations and the
tiering this rule sits inside.

Three consequences, spelled out because they are the ones that get misjudged:

- **Extracting figures from a broker PDF with a model is acceptable only as a fallback
  behind the deterministic parser, never as the primary path.** `scripts/pdf_to_csv.py` goes
  first. A model may attempt a layout its regexes cannot read, and then every extracted row
  is verified against the source document — the same check that script already demands of
  its own output.
- **Drafting prose that happens to contain personal figures is fine**, and is the job a
  local model is genuinely good for. The failure mode is a transposed digit, and reading the
  draft catches it.
- **Reconciling one document against another is done by hand** — a Form 16 against the audit
  CSV, for instance. Verifying a model's reconciliation costs as much as performing it, so
  the model adds nothing but risk. Let it find the line on the page; do the subtraction
  yourself.

A change that puts a model anywhere in the arithmetic does not belong here, however well it
performs in a demonstration. No test can catch this one — it is a rule about how the work is
done rather than about what is in the tree — which is exactly why it is written down.

## Scope

Foreign asset disclosure and the schedules that depend on it. **Not** regime comparison,
Chapter VI-A deductions, presumptive taxation, crypto, portal browser automation or general
ITR form selection. If a change is not about foreign assets, it does not belong here.

The README's Roadmap names Indian mutual funds and the other ITR forms as directions the
author may take. That is intent and it does not widen this rule: until one of them is actually
built, verified and documented, a change reaching outside foreign assets still does not belong
here.

One qualification, added with `rules/AY2027-28.json`. That registry carries **cited entries
for Indian mutual fund capital gains** — grandfathering, Specified Mutual Funds, both rates,
holding periods and FIFO — because the research was done and a cited entry is cheaper to
keep than to re-derive. **No code reads them and no pipeline computes them.** They are
research committed in a form a test can check, not a feature. Building the pipeline is still
a scope decision that has not been taken.

## Tests

Eight suites, plain scripts rather than pytest, all runnable offline and all of which must
pass before every commit:

```bash
for t in tests/test_*.py; do .venv/bin/python "$t" || break; done
```

CI runs the same set. Check counts are quoted in the README's Verification section — update
them when you add checks.
