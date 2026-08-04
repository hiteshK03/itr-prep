# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Changes to a statutory position get their own entry, with the provision cited.** Someone
reading this in three years needs to know not only that a figure changed but which
notification changed it, because they may be filing an earlier year.

## [Unreleased]

### Added

- **`rules/AY2027-28.json` — the first registry under a different Act.** The Income-tax Act,
  2025 (No. 30 of 2025, assented 21 August 2025) came into force on 1 April 2026 by its
  section 1(3) and repealed the Income-tax Act, 1961 by its section 536(1), so **FY 2026-27
  is the first year assessed under it** and almost every provision this tool cites was
  renumbered. The new registry re-verifies and re-cites all twelve AY 2026-27 entries against
  the Gazette text of the Act of 2025, the Income-tax Rules, 2026 (CBDT Notification No.
  22/2026, G.S.R. 198(E), 20 March 2026) and the Finance Act, 2026 (No. 4 of 2026,
  30 March 2026), and adds sixteen more. It also removes a live hazard: the registry's
  forward guard hard-fails on an assessment year it has no file for, so this had to exist
  before next July regardless.

  Two entries changed in **substance**, not just number, and say so:
  `form_67_deadline` became **`foreign_tax_credit_statement_deadline`** (Form No. 44 under
  rule 76 of the Rules of 2026, twelve months from the end of the tax year, with an
  accountant's verification under rule 76(16) above ₹1,00,000 of foreign tax and a new
  Form No. 45 intimating the settlement of a dispute over foreign tax whose credit was not
  claimed); and `revised_return_deadline` moved to **section 263(5)**
  as substituted by section 66(b) of the Finance Act, 2026, twelve months from the end of
  the tax year, with the section 428(b) fee now measured from the end of the *tax* year — so
  the fee window that section 234-I left unreachable under the 1961 Act is reachable, at
  31 December 2027.

- **An auditable old → new mapping.** Every entry in the new registry carries an
  `act_transition` block naming the AY 2026-27 entry it descends from, the old provision, the
  new provision and one of four classifications: `renumbered_only`,
  `renumbered_and_substantive`, `unchanged_separate_legislation` or `new_entry`.
  [`docs/ANNUAL-REVIEW.md`](docs/ANNUAL-REVIEW.md) renders it as a table. The headline moves:
  s.49(2AA) → s.73(1) Table Sl. No. 4, s.17(2)(vi) → s.17(1)(d), s.48 → s.72(1)(a),
  s.2(42A) → s.2(101), the fourth proviso to s.139(1) → s.263(1)(a)(ix) and 263(1)(b),
  s.139(5) → s.263(5), s.139(8A) → s.263(6)(a), rule 115(2) → rule 206 (as a table, Sl.
  Nos. 6 and 5, where the Rules of 1962 had sub-clauses (f) and (e)), rule 128(9) → rule 76,
  and rule 115(1)'s TT-buying-rate definition → rule 207.

  **The Black Money Act, 2015 is separate legislation and is not renumbered by any of this.**
  Section 43 is still section 43, the penalty is still ₹10,00,000 and the relief threshold is
  still ₹20,00,000. Every `s.43` citation in the tree was checked and left alone.

- **Mutual fund entries in the registry**, cited to the Gazette text: grandfathering
  (s.90(7) cutoff 1 February 2018, s.90(8)(b) valuation 31 January 2018, and the separate
  listed and unlisted fair-value bases), Specified Mutual Funds (s.76(1), s.76(2)(a),
  s.76(5)(b)), the equity-oriented thresholds (s.198(8), reaching short-term gains through
  s.196(5)), holding periods (s.2(101)), LTCG at 12.5% over ₹1,25,000 (s.198(2)(a)), LTCG
  otherwise at 12.5% (s.197(1)(b)), STCG at 20% (s.196(1)(i)), no indexation on units
  (s.197(3) with s.72(8)), FIFO (s.67(7)(c)) and nil cost for bonus units (s.90(6)(d)).
  **No code reads them.** They are research committed in a form a test can check.

  Two of them carry a structured `implementation_trap` block, because both produce a
  plausible wrong number rather than an error. **AMFI's 31 January 2018 NAV file has both a
  *Net Asset Value* column and a *Repurchase Price* column and they differ on 4,756 of its
  9,502 rows**; the statute requires net asset value, so reading the adjacent column
  understates half of all grandfathered cost bases. And **section 76(1) applies
  "Irrespective of anything contained in section 2(101)"**, so a Specified Mutual Fund unit
  acquired on or after 1 April 2023 is short-term however long it was held — any pipeline
  that computes holding days first and classifies second gets every one of them wrong, and a
  single folio routinely holds lots on both sides of that date.
  `tests/test_rules_registry.py` fails if either trap is deleted or hollowed out.

- **[`docs/KNOWN-ISSUES.md`](docs/KNOWN-ISSUES.md)**, for things established and not solved.
  Three at present: Schedule 112A's JSON schema carries `multipleOf: 0.0001` on five
  per-unit fields, which this repository has never hit because Schedule FA has no such
  constraint — tested with the repo's own `jsonschema` 4.26.0, `12.34` and `99.9999` both
  fail and 27.9% of random legal four-decimal values fail, and passing a `Decimal` raises
  `TypeError` inside the validator. Whether the Finance Act, 2026 amended the Specified
  Mutual Fund definition **could not be established** — Part B of its Chapter III does not
  amend section 76, but secondary commentary describes a 90-day carve-out that appears
  nowhere in the Gazette text and the department's consolidated as-amended PDF returns 403 to
  every automated client. And section 43 of the Black Money Act cures a default by reference
  to sub-sections of **section 139 of the repealed 1961 Act**, while a tax year 2026-27
  return is furnished under section 263 — unresolved, and material.

- **A stated policy on what a language model may do with a real figure.** `AGENTS.md` now
  says it plainly: every arithmetic operation on real financial data happens in deterministic
  Python, and a model may locate and transcribe a figure but may never subtract, total or
  reconcile one. Nothing changes in the code — no model has ever been in that path — so this
  closes a door against drift rather than describing a fix. The three cases that get
  misjudged are spelled out: model extraction from a broker PDF is a fallback behind
  `scripts/pdf_to_csv.py` with every row verified, never the primary path; drafting prose
  that carries personal figures is fine; and reconciling one document against another stays
  manual, because verifying a model's reconciliation costs as much as doing it.
  [`docs/AI-ASSISTANCE.md`](docs/AI-ASSISTANCE.md) carries the evidence — small open-weight
  models score at or near zero on multi-step calculation over financial tables, and a
  deterministic parser with model fallback beats a model working alone — along with the
  tiering the rule sits inside and why a work-owned machine is the wrong host for a personal
  return however much VRAM it has.

- **An explicit platform boundary.** `itrprep/host.py` is now the only module that knows the
  import step needs a Windows Excel, and it detects the *capability* — a Windows Python, or a
  shell with `powershell.exe` and `wslpath` — rather than an operating-system name, because
  the tested host is WSL and reports itself as Linux. Everything else in the package runs on
  macOS, Linux and Windows alike, and `tests/test_doctor_readback.py` asserts both halves:
  every module imports on whatever host the suite runs on, and none but `host.py` mentions
  `win32com`, `powershell.exe` or `Excel.Application`. Running `itr-prep import` where no Excel
  is reachable now exits 2 with an explanation and the alternatives, instead of failing inside
  a subprocess.
- **What the macOS options actually are**, in the README's new *Where this runs*. The
  department's Common Offline Utility covers ITR-2 for AY 2026-27 and is published for macOS
  (v1.2.2, 17 July 2026), and it takes an imported JSON — but its macOS build is Apple Silicon
  only (arm64, minimum macOS 11.0), and this tool's output has not been run through it. Excel
  for Mac and LibreOffice are ruled out with the counts from the utility's own VBA: 1,227
  `Scripting.Dictionary` creations and 24 Windows API `Declare`s, including the `Advapi32`
  CryptoAPI bindings behind `CreationInfo.Digest`. A Windows VM remains the tested fallback.
- **CI on macOS as well as Linux**, for the portable suites, plus a count that fails the build
  if fewer than eight suites are found in the checkout. Deliberately no Windows job: the only
  thing it could add needs Excel and a copy of the department's utility.
- **A test kit for the macOS Common Offline Utility**, so its two open questions can be settled
  in about twenty minutes rather than an afternoon.
  `scripts/make_macos_import_test.py` writes both JSON shapes — the partial Schedule FA
  document and the complete return `--merge-into` produces — over one synthetic 178-row Table
  A3, sized to the order a real return reaches and marked up so a truncation is visible by eye: a
  sequential `ROW nnn OF 178` in the entity-name column, an ascending acquisition date, and a
  zero-padded zip. [`docs/MACOS_UTILITY_TEST.md`](docs/MACOS_UTILITY_TEST.md) is the checklist,
  including the quarantine removal the unnotarised app needs and the Windows-VM fallback if the
  import truncates.

- **A cited rules registry.** Every statutory figure, date and convention now lives in
  `rules/AY2026-27.json` with an official source, and `itrprep/rules.py` is the only way code
  reaches one. Twelve entries, six of them classed `annual` because a Finance Act can move
  them. `itr-prep rules` prints them with their authorities.
- **Enforced annual re-verification.** `itr-prep build` refuses to run for an assessment year
  the registry does not cover, rather than falling back to the newest one; building an earlier
  year runs but banners which year's figures it used. `tests/test_rules_registry.py` fails on
  an entry with no official source, on an entry citing a secondary aggregator, on an `annual`
  entry left behind by its own registry, and on an `annual` entry missing from
  `docs/ANNUAL-REVIEW.md`.
- **`docs/ANNUAL-REVIEW.md`** — the human-facing checklist: every `annual` entry, its official
  source, and what specifically to re-check.
- **`AGENTS.md`** — tells any agent opening the repository to re-verify the registry before
  trusting it, and states the primary-source rule.
- **`itr-prep unlock`** — opens password-protected statements using credentials declared in a
  gitignored `.env`, never in a filename. Supports literal `ITRPREP_PW_<LABEL>` passwords and
  derivation from `ITRPREP_PAN` plus `ITRPREP_DOB`, which covers Form 16 and most CAS statements
  without a password per file. Decrypted copies land in `work/unlocked/`, mode 0600, in a 0700
  directory.
- **`tests/test_unlock_credentials.py`** — adversarial proof that a document password cannot
  escape the process: it builds a real encrypted PDF, fails to open it with the wrong
  credential, and searches the error text, the formatted traceback and the CLI's combined
  stdout and stderr for both the right password and the wrong one.
- **Provenance in the audit trail.** The audit CSV now carries `acquisition_source`,
  `proceeds_sources` and `dividend_sources`, tracing every figure back to the `file:line` of
  the export row it came from.
- **Open-source scaffolding** — `CONTRIBUTING.md` with the source-quality rule,
  `SECURITY.md`, this changelog, `pyproject.toml`, and CI running all eight suites on Python
  3.10 to 3.13 with a guard against committed personal data.

### Fixed

- **Corrected what Form No. 45 is for, in four places.** The registry, the README,
  [`docs/ANNUAL-REVIEW.md`](docs/ANNUAL-REVIEW.md) and this changelog all described the new
  Form No. 45 as the intimation for **a later refund of foreign tax**. It is not. Read against
  the notified text, **rule 76(15) of the Income-tax Rules, 2026** requires Form No. 45 for the
  purposes of **rule 76(6)** — the *settlement of a dispute* over foreign tax whose credit was
  not claimed, due within six months from the end of the month in which the dispute is
  settled, and verified by an accountant under rule 76(17) wherever that year's Form No. 44
  needed one. The refund case is **rule 76(14)**, which keeps it on **Form No. 44** itself, in
  its Part C. Anyone who had believed the old description would have gone looking for the
  wrong form on a deadline that does not exist, and would have missed that a refund reopens a
  form already filed rather than starting a new one.
- **`tests/test_unlock_credentials.py` was never committed.** It matched the `*_credentials*`
  line in `.gitignore` written to keep credential files out of the repository, so the suite
  that proves a document password cannot escape existed only on the author's machine — and
  because every runner globs `tests/test_*.py`, its absence passed silently rather than
  failing. `.gitignore` now excepts it, and CI fails the build if it finds fewer than eight
  suites.
- **The suites could not run on a fresh clone**, which is what CI is. Three of them invoked
  `.venv/bin/python` by path — a POSIX venv layout that a checkout does not have and that
  would be `.venv/Scripts/python.exe` on Windows anyway; they use `sys.executable` now. The
  rest read an FX and price cache that `data/` being gitignored means a clone lacks, so CI
  builds one with `fx-update` and two `threshold` runs before the suites.

### Changed

- **Narrowed the section 43 cross-reference question, and closed half of it.**
  [`docs/KNOWN-ISSUES.md`](docs/KNOWN-ISSUES.md) issue 3 asked whether a return under section
  263 of the Act of 2025 reads onto section 43 of the Black Money Act, whose text names
  section 139 of the repealed 1961 Act. Two findings, both from the enacted text.

  First, the framing was slightly wrong and the correction matters. Section 43 has no "list of
  curing filings". The reference to section 139(1), (4) and (5) sits in the **charging limb** —
  the section applies to a person "who **has furnished** the return of income for any previous
  year under" those sub-sections and omitted the asset "in **such** return". It identifies
  which return the omission is judged in. So nothing cures a section 43 default; a disclosure
  in a return under those sub-sections means no default arose.

  Second, that disposes of the updated return under **either** Act. Section 139(8A) was never
  in the charging limb, so section 263(6)(a) has no reference to be construed onto, and
  **section 8(1) of the General Clauses Act, 1897** — which construes a reference to a repealed
  provision as a reference to the provision re-enacted in its place — cannot supply a reference
  that was never made. An updated return did not displace a section 43 default before
  1 April 2026 and does not displace one after. That limb is settled, and settled against the
  taxpayer.

  What stays open is whether section 263(1), (4) and (5) read onto the charging limb in place
  of section 139(1), (4) and (5). Probably yes, on section 8(1) — but nothing makes it
  explicit, and the search for an instrument that does was exhaustive: the Act of 2025 has
  sixteen schedules and **none amends another enactment**; section 536 carries no bridge for
  other enactments, its sub-section (3) construing references "in this Act" only and its
  sub-section (4) expressly invoking section **6** of the General Clauses Act while saying
  nothing about section 8; and the Finance Act, 2026 had the Black Money Act open — Part III,
  section 160 — and inserted ₹20,00,000 provisos into sections 49 and 50 without touching
  section 43. Section 8(1)'s "unless a different intention appears" also has something to bite
  on, since **section 2(6) of the Black Money Act defines "Income-tax Act" as the Income-tax
  Act, 1961 (43 of 1961)** by name and number. The registry's re-check note on
  `black_money_s43_penalty_inr` now says all of this rather than "UNRESOLVED".

  That the 1961 Act governs AY 2026-27 and earlier is now also on department authority rather
  than inference: CBDT's
  [*FAQs on Interplay and Transition*](https://www.incometaxindia.gov.in/documents/81799/11848482/FAQs-on-Interplay-and-Transition.pdf),
  Q3.9 — "The old Act continues to govern all proceedings relating to tax years before 1st
  April, 2026" — and Q3.10, confirming an updated return for AY 2025-26 or earlier is filed
  under section 139(8A) of the old Act. Q4.22 states the same principle for forms: a relief
  claimed under the old Act stays on the old Act's form, the new form applying only from tax
  year 2026-27. By that reasoning **AY 2026-27 and earlier stay on Form 67, not Form No. 44**,
  which is what the registry already said.

- **Recorded the valuation gap in the ₹20,00,000 proviso as a known issue** rather than
  leaving it in a module docstring. `itrprep/threshold.py` already reports both a peak and a
  31 December basis and warns when they straddle the line; issue 4 in
  [`docs/KNOWN-ISSUES.md`](docs/KNOWN-ISSUES.md) now says why it must. The proviso is an
  *aggregate* test across non-immovable assets, not per asset, and it is a disapplication and
  not a discretion — "this section shall not apply" — but it says "value" without saying when
  or on what basis. The Explanation to section 43 imports the Explanation to section 42, which
  supplies only a currency conversion rule and is written for "the balance in an account
  maintained in foreign currency"; its phrase "as on the date for which the value is to be
  determined" presupposes a date that section 43 never fixes for shares. The proviso was
  substituted by **section 164 of Act 15 of 2024** with effect from 1 October 2024, which
  widened it to all non-immovable assets without extending the valuation machinery to match.

- **Audited every statutory citation in the tree against the change of Act, one at a time.**
  No find-and-replace was used and none should be: the AY 2026-27 return was genuinely filed
  under the Income-tax Act, 1961, and section 536(2)(c) of the Act of 2025 keeps that Act
  applying to any tax year beginning before 1 April 2026. Renumbering the record of a filed
  return would falsify it. So each citation was classified.

  **Kept as 1961-Act, deliberately**, with an explicit note at the top of each file saying so
  where a future reader might "fix" it: [`docs/RUNBOOK_AY2026-27.md`](docs/RUNBOOK_AY2026-27.md)
  in full, [`docs/VERIFIED_FINDINGS.md`](docs/VERIFIED_FINDINGS.md) in full, the dated entries
  in this changelog, the AY 2026-27 registry, and the README's prior-years and Form 67
  passages. Two things in that material look like statutory citations and are not:
  `Part A Gen_139(8A)` is a literal worksheet name inside the department's utility, and
  "validation rule 746" is a rule in the department's validation-rules PDF, unrelated to the
  Income-tax Rules. Both are called out so nobody renumbers them.

  **Re-cited to the Act of 2025**, showing the 1961-Act number alongside wherever a reader
  needs the bridge: the timeless statements in `itrprep/models.py`, `itrprep/adapters.py`,
  `itrprep/positions.py`, `itrprep/rules.py` and `itrprep/host.py`, the runtime warnings the
  adapters print, the README's data dictionary and FX-convention sections, `AGENTS.md`,
  `CONTRIBUTING.md` and the test comments that describe the law rather than the fixture.

- **`itrprep/emit.py` no longer hardcodes a repealed rule.** The other-schedules summary
  ended with four fixed lines naming Form 67, rule 128(9) and sections 139(1), 139(4) and
  139(8A). That text printed on every build for every year, so from AY 2027-28 it would have
  been asserting repealed provisions in a forward-looking document. The paragraph is now
  rendered from the registry for the year being built — Form 67 and rule 128(9) for
  AY 2026-27, Form No. 44 and rule 76 for AY 2027-28 — and `itrprep/cli.py` passes the loaded
  registry through. `rules/AY2026-27.json` gained two descriptive keys on
  `form_67_deadline`, `form` and `rule`, naming the form and rule that entry was already
  about; no figure changed and nothing was renumbered.

- **The registry suite now exercises every registry, not just the newest** (167 checks →
  579). This was a real gap rather than a tidiness one: the citation, review-class and
  staleness blocks all ran against `rules.load()`, which returns the newest file, so adding
  `rules/AY2027-28.json` would have silently retired `rules/AY2026-27.json` from the suite on
  the day it appeared. Two new blocks were added as well. **Act transition** asserts that a
  pre-2027 registry still cites the Income-tax Act, 1961 and a later one cites the Act of
  2025, that every entry in the later registry records an `act_transition` with a known
  classification, that no AY 2026-27 entry went missing across the change, and that the Black
  Money Act entries are marked `unchanged_separate_legislation` rather than renumbered.
  **Encoded traps** asserts both mutual fund traps are present, marked
  `silent_wrong_answer`, and still name the specific facts that make them traps. The
  annual-review checklist check now runs per registry and additionally requires the checklist
  to explain the change of Act and cite section 536(2)(c). The **code reads the registry**
  block gained checks that the other-schedules summary names the form, rule and deadline the
  registry gives, and that a 2025-Act year's summary asserts no repealed provision.

- **Settled the revised-return deadline, and corrected it.** `revised_return_deadline` was
  recorded as **31 December 2026** behind a `contested` flag, because our research memos
  disagreed. It is **31 March 2027**. Section 139(5) of the Income-tax Act, 1961 was
  substituted by **section 5(b) of the Finance Act, 2026 (No. 4 of 2026)**, with effect from
  1 March 2026, to allow a revised return "at any time before the end of the relevant
  assessment year or before the completion of the assessment, whichever is earlier" — three
  months later than the previous "three months prior to the end of the relevant assessment
  year". The Memorandum to the Finance Bill states the amendment applies for AY 2026-27, and
  gives its reason as the revised and belated deadlines having coincided, leaving a late
  belated filer no chance to revise. That matters here because a revised return, unlike an
  updated return under section 139(8A), is in the list of provisions in section 43 of the
  Black Money Act whose filing cures a Schedule FA omission — so the only self-help cure for
  the current year's schedule runs three months longer than recorded. Section 16 of the same
  Finance Act inserts **section 234-I**, a ₹1,000 or ₹5,000 fee on a revised return furnished
  after the nine-month point; as enacted it measures that period from the end of the
  *assessment* year rather than the previous year, so read literally its window opens after
  section 139(5) has already closed. The `contested` flag has been removed and the drafting
  point recorded in the entry's re-check note.
- **Settled the Form 67 to Form 44 question** in `form_67_deadline`'s re-check note, which
  previously flagged it as reported by a single secondary source and unverified. It is real:
  Form No. 67 under rule 128 of the Income-tax Rules, 1962 is succeeded by **Form No. 44
  under rule 76 of the Income-tax Rules, 2026** (CBDT Notification No. 22/2026, G.S.R. 198(E),
  20 March 2026), from tax year 2026-27 — income earned from 1 April 2026. AY 2026-27 is the
  last year on Form 67. Both limbs of the deadline survive: rule 76(12) gives twelve months
  from the end of the tax year, rule 76(13) repeats the updated-return proviso. The
  substantive changes are accountant verification under rule 76(16) where the assessee is a
  company or foreign tax paid is ₹1,00,000 or more, a mandatory foreign TIN, and a new
  Form No. 45 intimating the settlement of a dispute over foreign tax whose credit was not
  claimed.
- **Corrected the Form 67 deadline.** The README, `itrprep/emit.py` and
  `docs/RUNBOOK_AY2026-27.md` all said Form 67 must be filed *before the return*. That was the
  position before rule 128(9) was substituted by **CBDT Notification No. 100/2022 dated
  18 August 2022** (Income-tax (27th Amendment) Rules, 2022), with retrospective effect from
  1 April 2022. The deadline is now the **end of the assessment year** — 31 March 2027 for
  AY 2026-27 — where the return is furnished within the section 139(1) or 139(4) window. For
  an updated return under section 139(8A) the proviso requires Form 67 on or before the date
  that return is furnished, so for that route only, the old ordering still holds. ITAT
  authority treating the requirement as directory rather than mandatory is noted alongside.
- The threshold report now states which registry file and verification date produced the
  ₹20 lakh and ₹10 lakh figures it tests against.
- `ruff` configuration added and the codebase brought clean against it.

### Security

- Document passwords are read from the environment by the code and never enter a log line, an
  exception message, a traceback, a `--list-credentials` listing or a constructed command.
  `Credential` withholds its value from `repr()` and `str()`, and exceptions from `pypdf` and
  `msoffcrypto` are never re-raised or chained, because a library handed the password could
  otherwise put it into a traceback.
- Filename-derived passwords are explicitly rejected as a design, not merely unimplemented.
  See `SECURITY.md`.

## [1.0.0] — 2026-07-31

First working version: Schedule FA generated from broker exports and verified through the
ITD's ITR-2 Excel utility.

### Added

- Schedule FA table A3 and A2 emission in both the `ITR` and prefill JSON shapes, validated
  against the department's own draft-04 schema.
- Broker adapters for E*TRADE, Fidelity and INDmoney, with content-based detection, per-section
  column resolution, and multi-worksheet reading.
- Lot construction, daily valuation timelines, peak and closing values on both a USD and an
  INR maximising basis, and cash-balance valuation.
- SBI telegraphic-transfer buying rates and daily closing prices, both cached, both usable
  offline.
- Corporate action detection with basis inference and restatement.
- The ₹20 lakh Black Money Act section 43 threshold report, on two valuation bases, with an
  explicit straddle warning where they disagree.
- `doctor` preflight, which collects every problem and reports them together.
- Scripted import into the Excel utility over COM, with every imported cell read back and
  verified against the JSON and the audit CSV.
- Prior-year builds for AY 2024-25 and AY 2025-26.

### Fixed

- **ESPP cost basis** taken as the discounted price paid rather than the fair market value
  charged to perquisite under section 17(2)(vi), which section 49(2AA) makes the cost of
  acquisition.
- **Same-day-sell double counting**, which overstated both proceeds and cost whenever two
  sells shared a date — common in fractional-share plans.
- **An IST/ET date shift** that moved transactions across a year boundary.
- **Brokerage not deducted**, though section 48 allows expenditure wholly and exclusively in
  connection with the transfer.
- **The Rule 115 FX convention.** Capital gains and dividend income convert at the last day of
  the *preceding* month under rule 115(2), sub-clauses (f) and (e). Schedule FA uses a
  different convention — the rate on the date each amount relates to — and the two were
  conflated.
- Silent save failure when the utility runs under mandatory Purview sensitivity labelling.
- Whole worksheets silently dropped from multi-sheet exports.
