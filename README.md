# itr-prep — Schedule FA from broker exports, for the ITD ITR-2 Excel utility

### Scope today: ITR-2, with Schedule FA and Indian mutual fund capital gains

This produces **Schedule FA** (foreign asset disclosure) and the Schedule CG, OS, FSI and TR
figures that depend on it, for India's **ITR-2**, from US broker exports. Since 25 August
2026 it also computes **capital gains on Indian mutual funds** (Schedule 112A for
equity-oriented funds) from your own scheme declarations and transaction records, for
assessment years from 2027-28 onward — the years governed by the Income-tax Act, 2025, whose
figures live in [`rules/AY2027-28.json`](rules/AY2027-28.json).

It does **not** prepare ITR-1, ITR-3 or ITR-4, and it does **not** cover Indian equities,
salary, house property, regime comparison or Chapter VI-A deductions. The name is
deliberately broader than the tool, because the direction of travel is wider — but the
direction is not the product. [Roadmap](#roadmap) says what is intended, and says plainly
that none of it exists yet.

Indian mutual funds and Indian equities put into `transactions.csv` are **refused** there,
because the alternative was disclosing an Indian asset in Schedule FA and producing a wrong
return with no warning at all. Indian mutual funds have their own input files instead —
`mf_schemes.csv` and `mf_transactions.csv`. See
[Indian securities are refused](docs/COMPUTATION.md#indian-securities-are-refused).

## Quickstart

```bash
git clone https://github.com/hiteshK03/itr-prep.git && cd itr-prep
./setup.sh
# See it work on invented data, before you go looking for your own exports:
.venv/bin/python -m itrprep.cli build --year 2025 --work tests/synthetic --out /tmp/demo.json
# Then with your own: `init` writes the CSV templates; `run` does the whole pipeline.
.venv/bin/python -m itrprep.cli init --work work
.venv/bin/python -m itrprep.cli run --year 2025 --drop ~/Downloads
```

[Setup](#setup) explains what the demo prints and where the schema comes from;
[the workflow guide](docs/WORKFLOW.md) is the real thing step by step. Read
[six things that will bite you](#six-things-that-will-bite-you) before you file on any of
it — `--split-basis` alone is a factor-of-ten error when it is wrong.

## Contents

- [The problem](#the-problem)
- [What this does](#what-this-does)
- [Six things that will bite you](#six-things-that-will-bite-you)
- [Documentation](#documentation)
- [Setup](#setup)
- [Workflow in one screen](#workflow-in-one-screen)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)
- [Licence and contributing](#licence-and-contributing)

## The problem

An Indian resident holding US employer equity — RSUs, an ESPP, shares bought through a
foreign broker — has to file **Schedule FA** as part of ITR-2. Schedule FA is not a summary.
Table A3 wants **one row per holding**, and for each row the *peak* value during the
calendar year as well as the closing value, converted at the **SBI TT-buying rate** for the
relevant date. A few years of quarterly vests is dozens of rows, each needing a peak-value
lookup against daily closes and a daily FX rate.

Three things make this harder than it sounds:

- **No filing route imports foreign broker data.** The e-filing portal's prefill covers
  Indian income; AIS may show foreign-asset information but it is not importable into
  Schedule FA, and the online ITR-2 form has no bulk entry. The default is typing every row
  into a browser form by hand.
- **Schedule FA runs on the calendar year**, while the rest of the return runs on the
  financial year. Everything has to be recomputed on a different period from the capital
  gains figures sitting next to it.
- **The peak value is per holding, per day.** It needs a daily close series and a daily FX
  series, and it is defined per row, so it cannot be derived from a year-end statement.

## The way in

The Income Tax Department's own **offline ITR-2 Excel utility** has an **undocumented JSON
import** on the Schedule FA sheet. It is not described in the utility's help, in the
department's user manuals, or anywhere else public as far as I can find. It calls the
utility's own `AddRows_A3_FA3` macro, so **it grows the table to fit** — there is no row
cap, and no manual "add row" clicking. Feed it a correctly-shaped JSON file and a hundred
lots land in the sheet at once.

That import is the reason this tool exists. It turns Schedule FA from an evening of
transcription into a file you generate, import and verify.

## What this does

Turns E\*TRADE, Fidelity NetBenefits and INDmoney exports into that JSON file: reconstructs
lots from transaction history, computes per-lot peak and closing values against cached daily
closes, converts at SBI TT-buying rates, and emits Schedule FA Tables A3 and A2 in the exact
shape the utility expects. Then imports it into the utility and **reads every cell back** to
prove the import landed.

**The round-trip is verified, not assumed.** The generated JSON was imported into a live
copy of the utility and the resulting sheet cells were read back and checked, on three
assessment years' utilities. See [`docs/ROUNDTRIP_RESULT.md`](docs/ROUNDTRIP_RESULT.md) for
the output. Field names and traps were established by decompiling the utility's VBA — see
[`docs/VERIFIED_FINDINGS.md`](docs/VERIFIED_FINDINGS.md), which cites line numbers.

Filing for AY 2026-27? Follow [`docs/RUNBOOK_AY2026-27.md`](docs/RUNBOOK_AY2026-27.md)
instead of this README. It is a single linear checklist from downloads to a filed return.

---

> ## ⚠️ Not tax advice
>
> This is a tool for preparing data, not a substitute for professional judgement.
>
> - **It is not tax advice**, legal advice, or a statement of what the law requires of you.
>   Schedule FA obligations, valuation bases and disclosure positions are matters for a
>   qualified professional who knows your circumstances.
> - **Check the output before you file.** Every figure is your responsibility once it is on
>   your return. The tool writes an audit CSV for exactly this reason: reconcile it against
>   your own broker statements. Verified round-trips and passing schema validation mean the
>   file was accepted, not that the numbers are right for you.
> - **The author accepts no liability** for anything arising from use of this tool,
>   including incorrect filings, penalties, interest or prosecution. No warranty of any
>   kind — see [`LICENSE`](LICENSE).
> - It works against undocumented behaviour in a government utility that can change without
>   notice. Re-verify against the current year's utility rather than trusting last year's
>   result.

---

> ## 🔒 Your data stays local
>
> `work/` and `out/` — where your broker exports, generated transactions, JSON output and
> audit trails live — are gitignored (see [`.gitignore`](.gitignore)). Nothing you put there
> gets committed or pushed by this tool. Clone it, run it, and your financial data never
> leaves your machine unless you explicitly copy it somewhere.

---

> ### A note on AIS before you start
>
> The department publishes foreign-asset information in the **Annual Information Statement**,
> and it can be useful for reconciliation. Two facts worth knowing before you download it:
>
> - **Downloading it is logged** against the PAN, one calendar year at a time, and cannot be
>   undone. So is AIS feedback, which is acknowledged and cannot be withdrawn.
> - **That log may bear on eligibility to file an updated return.** An updated return is
>   barred in certain circumstances, including where information received under an agreement
>   for the exchange of information has been communicated to the assessee — s.139(8A) of the
>   Income-tax Act, 1961 for AY 2026-27 and earlier, s.263(6) of the Income-tax Act, 2025 for
>   later years.
>
> Whether either matters in a given case depends on facts this tool knows nothing about.
> **Take professional advice before downloading, if there is any chance you may need to file
> or revise a return for an earlier year.** Nothing here requires AIS: the tool reconstructs
> everything from broker statements, which is independently defensible and reproducible
> years later from the audit CSVs.

---

## Six things that will bite you

1. **Schedule FA is on the CALENDAR year, not the financial year.** For AY 2026-27 it
   covers **1 Jan 2025 – 31 Dec 2025**. Schedule CG / OS / FSI / TR stay on FY 2025-26.
   Mixing these up is the single most common Schedule FA error.
2. **Set Part B-TTI item 19 to "Yes"** (validation rule 746). The import works either way
   on v1.2 — the FA cells ship unlocked, which I measured — but the *return* is invalid
   without it.
3. **Importing the same table twice replaces its rows, and rows cannot be deleted.** The
   importer calls `.ClearContents` on the A3 columns and then writes from row 1 again, but
   the *inserted rows* stay. Import 12 rows twice and you get 12 filled rows plus 6 blank
   ones you cannot remove. **Always import into a fresh copy of the utility.** Keep the
   pristine `.xlsm` and copy it per attempt.
4. **The import fails silently.** Every import function in the utility begins with
   `On Error Resume Next`, so a bad value produces no error dialog — just a missing or
   wrong cell. Never trust an import that merely *looks* fine: use `itr-prep import`, which
   reads every cell back and verifies it against the audit trail.
5. **`BENIFICIARY` is misspelled on purpose.** The ITD's own schema enum and VBA both use
   that spelling. Correcting it fails validation. Same for the country code, which must be
   the *string* `"2"`, not the number 2.
6. **A stock split will stop the build**, on purpose. See
   [Stock splits](docs/COMPUTATION.md#stock-splits-the-build-stops-rather-than-guess) — a wrong answer here is
   a factor-of-ten error, not a rounding one.

---

## Documentation

The README stays short on purpose. Everything deep lives in [`docs/`](docs/):

| Read this | When |
|---|---|
| [`docs/RUNBOOK_AY2026-27.md`](docs/RUNBOOK_AY2026-27.md) | **Filing this year.** One linear checklist from downloads to a filed return |
| [`docs/WORKFLOW.md`](docs/WORKFLOW.md) | The step-by-step pipeline, the full command reference, and the repository layout |
| [`docs/PLATFORMS.md`](docs/PLATFORMS.md) | Where this runs; macOS / Linux / Windows; the four routes off Windows |
| [`docs/BROKERS.md`](docs/BROKERS.md) | What to export from E\*TRADE, Fidelity NetBenefits, INDmoney |
| [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md) | Every column of the input CSVs, including the ESPP cost-basis trap |
| [`docs/COMPUTATION.md`](docs/COMPUTATION.md) | How the numbers are computed: lots, FX, peak value, splits, the Indian-securities refusal, Table A2 and cash |
| [`docs/OTHER_SCHEDULES.md`](docs/OTHER_SCHEDULES.md) | Prior-year updated returns; Schedule CG/OS/FSI/TR; Form 67 and Form 44 |
| [`docs/STATUTE_REGISTRY.md`](docs/STATUTE_REGISTRY.md) | Where every statutory figure comes from; the AY 2027-28 change of statute |
| [`docs/VERIFICATION.md`](docs/VERIFICATION.md) | The eleven test suites, the live round-trips, and the supply chain |
| [`docs/KNOWN-ISSUES.md`](docs/KNOWN-ISSUES.md) | Open questions, with the evidence on each side |

## Setup

Needs Python 3.10 or newer (CI covers 3.10 to 3.13) and network access once, to cache
exchange rates and prices:

```bash
git clone https://github.com/hiteshK03/itr-prep.git && cd itr-prep
./setup.sh
```

Then try it on the bundled synthetic dataset — four invented tickers across three
accounts, no broker export or PAN needed:

```bash
.venv/bin/python -m itrprep.cli build --year 2025 --work tests/synthetic --out /tmp/demo.json
```

It prints a Schedule FA summary and writes three files: the importable JSON, an audit CSV
(one row per lot, every figure traced to the export line it came from), and the figures for
the schedules beyond Schedule FA. [The workflow guide](docs/WORKFLOW.md) walks the real thing,
and [`docs/RUNBOOK_AY2026-27.md`](docs/RUNBOOK_AY2026-27.md) is the year's filing checklist.

> **Validation** needs the ITD's own ITR-2 schema, which is not redistributed here. Drop it
> in `schemas/` — [`schemas/README.md`](schemas/README.md) says where to get it. Without it,
> `build` still works but says loudly that its output is unverified.
>
> **On a corporate network** that intercepts TLS, see
> [the troubleshooting note](docs/WORKFLOW.md#on-a-network-that-intercepts-tls) before setup.

## Workflow in one screen

```bash
itr-prep init --work work                 # once; then fill in the three descriptive files
itr-prep run    --year 2025 --drop ~/dl   # rates, normalize, preflight, threshold, build
itr-prep import --year 2025 --json out/schedule_fa_2025.json \
              --utility /path/to/pristine/ITR2_AY_26-27_V1.2.xlsm
```

`run` chains the whole pipeline and stops at the first hard error, naming the stage.
`import` drives the Excel utility and verifies every imported cell against the audit
trail — the one step that needs Windows; on macOS use the department's Common Offline
Utility ([`scripts/macos_import_to_utility.py`](scripts/macos_import_to_utility.py),
verified 25 August 2026) — see [`docs/PLATFORMS.md`](docs/PLATFORMS.md).

Every step, every flag, the password handling and the preflight doctor:
[`docs/WORKFLOW.md`](docs/WORKFLOW.md).

## Known limitations

- **Cash balances must be supplied by hand.** They are now supported
  (`cash_balances.csv`) but cannot be derived, so if you omit the file Table A2 counts
  securities only. Every run tells you which accounts that affects.
- **Splits are detected, not silently corrected.** You still have to tell the tool which
  basis your quantities are on. Only splits Yahoo reports for the ticker are seen; a
  delisting, merger, spin-off or ticker change is **not** detected and will need manual
  handling and a `prices_override.csv`.
- **Fees are not deducted.** `amount_usd` is taken as gross, which is what
  `TotGrossProceeds` asks for. Capital gains cost figures therefore exclude brokerage.
- **A section a profile cannot map is reported, not guessed at.** Multi-section exports and
  multi-sheet workbooks are read per section and per worksheet, but a block whose header
  names no recognisable date column (a grant summary, an unvested-award listing) has all its
  rows listed as dropped and the run stops. That is deliberate — the alternative is reading
  them against another block's columns — but it means an export carrying such a block needs
  either a renamed column or `--allow-dropped-rows` once you have read the list.
- **A cost basis inherited from a sibling row is not verified.** Where a vest tranche's own
  line carries no per-share figure, the award's position line supplies it. That is the
  export's own number for that tranche, but the tool cannot confirm it is the figure the
  perquisite was actually charged on — the run warns, and Form 12BA item 17 is the check.
- **`Market Value` is assumed to be per share.** Real vest records use that name for the
  vest-date FMV, so it is accepted as a price, and every unambiguous per-share name is
  checked ahead of it. If a section's `Market Value` is actually a row total, the run says
  so (it compares the column against the amount column) but does not rewrite it.
- **Prices come from Yahoo**, an unofficial endpoint that can change or rate-limit. Caches
  and `prices_override.csv` are the mitigation.
- **The Indian-securities refusal cannot catch a bare ticker.** All four of its signals — an
  `IN`-prefixed ISIN, an INR row, an NSE or BSE suffix, an `INDIA` issuer country — depend on
  data the tool does not itself produce, and no supported broker export carries an ISIN. An
  Indian holding entered as a plain ticker with nothing else will still be valued and disclosed.
  The refusal says this about itself, and
  [`docs/KNOWN-ISSUES.md`](docs/KNOWN-ISSUES.md) issue 6 records what would actually close it.
- **The threshold report is arithmetic, not advice.** It aggregates your own data against
  ₹20,00,000 on two bases. Which basis a tribunal would accept is unsettled, and the report
  says so rather than resolving it.
- **Only the ITR-2 utility is supported.** ITR-3 shares the VBA but the sheet/codename
  mapping was not checked.
- **The import step needs Windows; the macOS alternative is tested but not wired to the
  CLI.** The pipeline runs anywhere; `itr-prep import` does not, because the department's
  `.xlsm` binds Windows CryptoAPI and Windows COM. The department's Common Offline Utility
  for macOS has been verified to carry this tool's output (178-row Schedule FA intact,
  read back from its own upload JSON — see
  [`docs/MACOS_UTILITY_TEST.md`](docs/MACOS_UTILITY_TEST.md)), but that path is driven by a
  standalone script (`scripts/macos_import_to_utility.py`), not a CLI subcommand, and its
  macOS build is Apple Silicon only.
- **The platform check tests whether Windows is reachable, not whether Excel is installed.**
  A WSL box with `powershell.exe` and `wslpath` but no Excel therefore gets past the boundary
  and fails inside COM instead of being refused up front. A pre-flight probe would mean a
  second COM path — its own timeouts, its own abandoned Excel processes — to gate a step that
  can only be tested on one host, so the failure is made legible instead: the
  `80040154 Class not registered` signature is recognised and explained as a missing Excel,
  in the same terms the up-front refusal uses.

## Roadmap

**Everything in this section is intent, not capability** — except where an item says
otherwise in its own text. Indian mutual funds were built on 25 August 2026 and are marked
as such below; the rest is neither implemented nor scheduled, and none of it should affect
a decision to use this tool. What the tool does today is
[Scope today](#scope-today-itr-2-with-schedule-fa-and-indian-mutual-fund-capital-gains) and the rest of this README; if a claim appears here
and nowhere else, it is not built. Check the code before relying on any of it.

- **Indian mutual funds — built 25 August 2026.** Capital gains on Indian mutual fund
  units now compute end to end: `itrprep/capgain.py` is the FIFO lot engine (grandfathering
  to 31 January 2018 under section 90(7) of the Income-tax Act, 2025, holding periods under
  section 2(101), bonus-unit cost under section 90(6)(d), every figure read from
  `rules/AY2027-28.json`), and `itrprep/mf_input.py` reads `mf_schemes.csv` and
  `mf_transactions.csv`, which `itr-prep init` templates. The engine classifies nothing: a
  fund's equity-oriented status and its valuation-date FMV are caller declarations, and the
  specified-mutual-fund entry stays `contested` and unread until KNOWN-ISSUES.md issue 2 is
  settled. Output: Schedule 112A rows inside the merged return JSON, validated against the
  department's schema, plus the Schedule CG aggregates in the summary file. Two honest
  limits remain: it covers AY 2027-28 onward (earlier years are 1961-Act years whose MF
  entries nobody has written), and ITD has not yet published the AY 2027-28 offline utility,
  so the round-trip through the utility — the verification Schedule FA has — cannot be run
  until they do.
- **Indian equities.** The sibling problem: same Schedule CG/112A destination, grandfathering
  again, INR cost basis, no FX layer, and no `Profile` for any Indian broker's capital-gains
  statement. The MF pipeline's engine is the natural home for most of it, but the broker
  inputs and the equity-oriented declaration story still need building.
- **ITR-1, ITR-3 and ITR-4.** The department's utilities for these share much of the ITR-2
  VBA, so the import mechanism may well carry over — but "may well" is the whole distance
  between this list and [Verification](docs/VERIFICATION.md). Nothing about the sheet
  names, code names or named ranges in those workbooks has been checked here, and the one
  thing this project has learned repeatedly is that an unverified assumption about that
  utility is usually wrong. Each form would need its own round-trip, live, before being
  claimed.

Two things will not change if any of that happens: a statutory figure needs a primary citation
before it enters `rules/`, and the upload file keeps coming out of the department's own
software. See [The line this project will not cross](docs/PLATFORMS.md#the-line-this-project-will-not-cross).

## Licence and contributing

MIT — see [`LICENSE`](LICENSE). Copyright 2026 Hitesh Kandala. No warranty; see the disclaimer
at the top.

Corrections are welcome. [`CONTRIBUTING.md`](CONTRIBUTING.md) has the detail; the two rules
that matter most are that nothing real ever gets committed, and that a statutory claim needs a
primary citation or an admission that you could not verify it. What helps most:

- **Another broker adapter.** A `Profile` in `itrprep/adapters.py` plus a fixture export with
  the figures replaced by invented ones.
- **A newer utility version.** If the ITD ships a version where the named ranges or the
  `ImportScheduleFA` signature have moved, that is worth knowing; `scripts/probe_workbook.ps1`
  dumps what a workbook actually contains.
- **A wrong claim.** Everything in [`docs/VERIFIED_FINDINGS.md`](docs/VERIFIED_FINDINGS.md)
  cites a line number so it can be checked rather than believed.
- **A registry entry that has moved** — especially one of the six marked `annual`.

[`SECURITY.md`](SECURITY.md) covers what this tool does with your data and how document
passwords are handled. [`CHANGELOG.md`](CHANGELOG.md) records every change to a statutory
position with the provision that changed it, which matters if you are filing an earlier year.

Please do not open issues asking whether something is taxable, or attach real broker exports
or account numbers to anything public. The issue templates say the same thing at the point
where it matters, and ask you to tick that you have not — reproduce a bug against
`tests/synthetic/` instead, which is what it is there for. If a PAN or a document password
has already been pushed somewhere, [`SECURITY.md`](SECURITY.md) says what to do first, and
the answer is not "delete the commit".
