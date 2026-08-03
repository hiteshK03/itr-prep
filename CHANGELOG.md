# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Changes to a statutory position get their own entry, with the provision cited.** Someone
reading this in three years needs to know not only that a figure changed but which
notification changed it, because they may be filing an earlier year.

## [Unreleased]

### Added

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
  Form No. 45 for a later refund of foreign tax.
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
