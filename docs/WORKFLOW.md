# The workflow

*Part of [itr-prep](../README.md) — the step-by-step pipeline, the command reference and the repository layout.*

Two stages, so you can start before every export is in hand.

```
broker exports ──(stage 1: normalize)──> transactions.csv ─┐
                                          issuers.csv ─────┼──(stage 2: build)──> JSON ──> Excel utility
                                          accounts.csv ────┘
```

## The short version

```bash
itr-prep init --work work                 # once; then fill in the three descriptive files
itr-prep run    --year 2025 --drop ~/dl   # rates, normalize, preflight, threshold, build
itr-prep import --year 2025 --json out/schedule_fa_2025.json \
              --utility /path/to/pristine/ITR2_AY_26-27_V1.2.xlsm
```

`run` chains the whole pipeline and stops at the first hard error, naming the stage. `import`
drives the Excel utility over COM and verifies every imported cell against the audit trail;
it is the only command that needs Windows, and [Platform guide](PLATFORMS.md) covers
what to do on a Mac. Each stage below still works on its own; `run` composes them, it does
not replace them.

## 0a. If a statement is password-protected

Form 16, CAS statements and a few broker exports arrive encrypted. Put the credential in a
gitignored `.env` and let the code use it — **never in the filename**, which is where the
obvious tools look. A filename lives in shell history, in `ls` output, in a backup index, in
a screenshot and in whatever got pasted into a chat window; a password there is a password in
a dozen places you did not choose.

```bash
cp .env.example .env && chmod 600 .env   # then fill it in
.venv/bin/python -m pip install -r requirements-unlock.txt

itr-prep unlock --list-credentials         # names and set/unset only, never a value
itr-prep unlock --input ~/dl/Form16.pdf    # -> work/unlocked/Form16.pdf, mode 0600
```

Most of these documents are not protected by an arbitrary secret but by a formula: the
e-filing portal's convention, which most payroll providers follow, is the PAN in lower case
followed by the date of birth as DDMMYYYY. Set `ITRPREP_PAN` and `ITRPREP_DOB` once and the
candidates are derived, so you need no password per file. For the ones that do have an
arbitrary secret, declare `ITRPREP_PW_<LABEL>` — `ITRPREP_PW_FORM16`, `ITRPREP_PW_ETRADE`, whatever
you like. Every `ITRPREP_PW_*` variable is tried against every file, which is precisely why a
file never needs to be named after its password.

**The password is read by the code and goes nowhere else.** Not into a log line, an exception
message, a traceback, a `--list-credentials` listing or a constructed command. `Credential`
withholds its value from `repr()` and `str()`; the libraries that are handed the password
never have their message text propagated, because a library that quoted the attempt back
would put it in a traceback; and a failure names the *variable* that did not work, never its
value. `tests/test_unlock_credentials.py` builds a genuinely encrypted PDF, fails to open it
with the wrong credential, and asserts that the error text, the traceback and everything the
CLI writes to stdout and stderr contain neither the right password nor the wrong one.

If an agent is helping you, its job is to run `itr-prep unlock --input <path>`. It should never
see, ask for, or handle the password — the point of this repository is that your financial
data flows through deterministic Python rather than through a model, and a document password
sitting in a model's context window would be a straightforward regression against that.

Decrypted copies are personal documents. They land together in `work/unlocked/` (owner-only,
each file 0600) rather than beside the encrypted originals, so one `rm -rf work/unlocked`
removes all of them.

## 0. Create the working files

```bash
itr-prep init --work work
```

Writes `work/transactions.csv`, `work/issuers.csv`, `work/accounts.csv`,
`work/cash_balances.csv`, `work/prices_override.csv`, and the two mutual fund files —
`work/mf_schemes.csv` and `work/mf_transactions.csv` — each with example rows marked
`example row - delete me`. Delete those before building.

## 1. Normalize each broker export

Point `run` at a folder and each file is classified by its **header row**, not its filename,
because broker filenames are unpredictable and `Download (3).csv` is the normal case. CSV,
TSV and XLSX are all read directly:

```bash
itr-prep run --year 2025 --drop ~/dl
```

It prints what it matched each file to and the evidence it used, so a misdetection is visible
rather than silent. A file it cannot classify is **named and the run stops** — guessing a
broker profile would produce plausible-looking wrong rows. Detection uses headers only one
provider emits (`Vest Date FMV`, `Offering Period`, `Price (USD)`) plus brand strings in the
preamble, and requires a clear winner.

Each export is matched to an account by looking for the broker's name in `accounts.csv`'s
`institution_name`. Override when that is ambiguous: `--account etrade=etrade_stockplan`.

Or drive it per file:

```bash
itr-prep normalize --broker etrade   --input ~/dl/etrade_benefit_history.csv \
                 --account-id etrade_stockplan    --out work/transactions.csv
itr-prep normalize --broker fidelity --input ~/dl/fidelity_espp.csv \
                 --account-id fidelity_espp --out work/transactions.csv --append
itr-prep normalize --broker indmoney --input ~/dl/indmoney_us.csv \
                 --account-id indmoney_us   --out work/transactions.csv --append
```

`--append` keeps rows already in the file for *other* accounts, and replaces the rows for
the account you name, so re-running is safe and never duplicates.

If an export's columns aren't recognised, the adapter tells you exactly which concept it
couldn't find and lists the headers it did see. You can then rename one column, or skip
Stage 1 entirely and fill `transactions.csv` by hand — the [data dictionary](DATA_DICTIONARY.md) defines
every field, and hand-filled data produces identical output.

Always review the normalized file. Sale rows, vest-date fair market values and dividend
withholding are the fields brokers most often export oddly.

**Multi-section exports.** An E\*TRADE / StockPlan Connect Benefit History is normally one
block per plan type or per grant, each with its own header row, column order and width. The
adapter re-resolves the column mapping for **every** section, and prints a census of what
each one contributed:

```
line 12 (Restricted Stock Units - Net Share Settlement): 2 data row(s) -> 2 read as
  4 transaction(s), 0 DROPPED, 0 ignored (titles/totals)
  columns: date='Vest Date', ticker='Symbol', type='Transaction Type',
           lot='Grant Number', withheld_qty='Tax Collection Shares',
           net_qty='Net Shares', quantity='Shares Issued', price='Vest Date FMV'
```

Read that census. Every row the file contained is either imported, ignored as a title or
totals line, or **listed as dropped with the reason** — and a dropped row stops the run,
because a Schedule FA missing a vest is a s.43 exposure of ₹10,00,000 per assessment year.
Once you have checked each dropped row really is not a transaction, `--allow-dropped-rows`
proceeds anyway.

**If your export has both a gross and a net quantity column** (e.g. `Shares Issued`
alongside `Tax Collection Shares` and `Net Shares`), all three are read as three different
numbers. The **gross** count is reported as the acquisition, because that is what the
perquisite is charged on — s.17(1)(d) of the Income-tax Act, 2025, s.17(2)(vi) of the 1961
Act — and what Form 12BA item 17 states, and the
withheld shares become a **disposal on the same date** — a sell-to-cover is a real transfer
of a foreign share, so it belongs in Schedule FA as acquired-then-disposed and in
Schedule CG as a near-nil-gain sale. Reporting only the net count understates both.

Where a section states a net count but has no withheld-share column, gross cannot be
recovered and the run says so: those rows are a **floor**, not an answer. Re-export with the
withheld-share column to close the reconciliation against Form 12BA.

`Sellable Quantity` is deliberately not treated as an acquired quantity: it is 0 for a vest
already sold to cover, which is how such rows used to disappear entirely.

**Multi-sheet workbooks.** A "By Benefit Type" export puts ESPP purchases on one worksheet
and restricted stock on another. Every worksheet is read, each mapped on its own header, and
the census names all of them with their row counts — including the ones nothing was read
from:

```
ByBenefitType.xlsx -- 'etrade' profile, 2 worksheet(s), 2 section(s)
  worksheet 1 'ESPP': 5 non-empty row(s), 3 data row(s) in 1 section(s)
  worksheet 2 'Restricted Stock': 26 non-empty row(s), 24 data row(s) in 1 section(s)
```

Check those counts against the tabs in Excel. Reading only the first sheet is what dropped
an entire `Restricted Stock` worksheet — a whole RSU vest, along with the shares sold to
cover the withholding tax on it — out of a real Schedule FA, and it did so without one
warning. An instructions or disclaimer tab is reported as `SKIPPED` with
its reason and row count and does not stop the run; a hidden tab is read like any other.
But a sheet whose rows *do* parse as transactions while its header does not can never be
skipped quietly: those rows are listed as dropped and the run stops.

**Nested stock-plan sheets.** A restricted-stock tab reads as one record per line —
`Grant`, then `Vest Schedule` per tranche, then `Tax Withholding` per jurisdiction, then
`Sellable Shares` — tied together by grant number. Only a vested tranche is a share event;
the rest state positions or plans and are named in the census as ignored. An unvested
tranche produces nothing at all, because a contingent right to future shares is not a
foreign asset held. Where a tranche's own line carries no per-share figure, the basis is
taken from that award's position line and both the note and a warning say so, for checking
against Form 12BA.

Three per-share concepts are kept apart, because conflating them is a misstatement in a
specific direction each time: the **FMV** an acquisition is charged on (the cost of
acquisition under s.73(1) of the Income-tax Act, 2025, s.49(2AA) of the 1961 Act), the
**price a sale executed at** (what a disposal is
valued at, never an FMV), and the **price paid** on a discounted purchase (evidence of the
perquisite, never a basis — see the ESPP note in the data dictionary). `Est. Market Value`
and `Est. Taxable Gain/Loss` are refused outright as either: the first is a snapshot at the
export's run date and includes unvested shares, the second is an unrealised gain against it.

## 2. Fill in issuers and accounts

These cannot be derived from a transaction export. `issuers.csv` needs one row per ticker
with the **company's** name and address; `accounts.csv` needs one row per brokerage account.
See the [data dictionary](DATA_DICTIONARY.md).

## 3. Build

```bash
itr-prep build --year 2025 --work work --out out/schedule_fa_2025.json
```

Prints a summary, validates against the official ITD schema, and writes three files:

| File | What it is |
|---|---|
| `schedule_fa_2025.json` | the file you import into the utility |
| `schedule_fa_2025_audit.csv` | every row's working: quantities, prices, exchange rates, dates, and the export row each figure came from |
| `schedule_fa_2025_other_schedules.txt` | Schedule CG and dividend figures (see below) |

For earlier years, just change `--year`:

```bash
itr-prep build --year 2024 --work work --out out/schedule_fa_2024.json
itr-prep build --year 2023 --work work --out out/schedule_fa_2023.json
```

The same transaction history serves every year — a lot acquired in 2023 and still held
produces a row in 2023, 2024 and 2025 with different peak and closing values. Nothing is
hardcoded to 2025.

**Every figure in the audit CSV names the export row it came from.** Three columns —
`acquisition_source`, `proceeds_sources` and `dividend_sources` — hold `file:line`
references back to the broker export each number was read out of, so "where did this come
from?" is answered from the CSV years later rather than by working out which download it
must have been. A dividend is apportioned across the lots that held the stock on the
payment date, so several rows legitimately cite the same dividend line. Only the file's
basename is recorded, never the path it happened to sit at.

## 3b. The ₹20 lakh threshold report

If any year's Schedule FA was **omitted from a return already filed**, run this before
anything else. It is the most consequential number the tool produces.

```bash
itr-prep threshold --work work --years 2022-2025 --out work/threshold_report.txt
```

Black Money Act **s.43** penalises an omitted foreign-asset disclosure at **₹10,00,000 per
assessment year**. A proviso inserted by the Finance (No.2) Act 2024, with effect from
1 October 2024, disapplies that penalty where the **aggregate value of foreign assets other
than immovable property does not exceed ₹20,00,000**. So one number per year decides
whether an omission costs nothing or ₹10 lakh, and whether paying for an amnesty scheme is
worth it.

For each calendar year the report gives:

- the aggregate on a **peak** basis (the sum of each holding's own peak, plus cash),
- the same on the conservative `--peak-basis inr` variant,
- the aggregate on a **closing (31 December)** basis,
- an **OVER / UNDER ₹20,00,000 verdict** for each, with the excess or headroom in rupees,
- the per-account and per-holding breakdown behind every total,
- and a **STRADDLE WARNING** where the two bases fall on opposite sides of the line.

Both bases are always shown because **the valuation date is genuinely unresolved**.
Parliament widened the proviso to all non-immovable assets without extending the Act's
valuation machinery (s.3 with Rule 3) to match, so for shares neither peak nor 31 December
is settled. Where a year straddles the line, that ambiguity is worth ₹10 lakh and is the
point at which professional advice pays for itself. The report says so, loudly, rather than
picking a basis and hiding the other.

Two things it does deliberately:

- **A year with no data says `NO DATA`, never `0`.** A spurious zero would read as "under
  the threshold" when it actually means "you have not given me that year's transactions".
  The reason names the earliest transaction it *does* have.
- **Cash counts.** Accounts listed in `cash_balances.csv` have their cash included; accounts
  missing from it are flagged in the notes as securities-only and understated.

Start at **2022**, not 2023: if an account predates 2023 then AY 2023-24 may be in default
too, and the additional-tax rate for an updated return is higher the older the year.

Output goes to stdout, to `--out`, and to a per-lot audit CSV alongside it.

## 3c. Preflight — `doctor`

```bash
itr-prep doctor --work work
```

Reports everything actionable in **one pass** rather than failing on one error at a time.
Exits non-zero on errors, zero with warnings, and prints `READY TO BUILD` when clean. It is
run automatically as stage 3 of `run`.

Errors, which block a build:

- template **example rows** still present, or a `REPLACE-WITH-REAL` account number. Filing
  these would disclose holdings and account numbers that do not exist;
- a ticker with no `issuers.csv` row, or an `account_id` with no `accounts.csv` row;
- a `SELL` with no shares to sell;
- an acquisition or sale with a zero price — that is the cost basis;
- an FX cache that does not cover the years asked for;
- an **Indian security**, which Schedule FA cannot disclose at all — see
  [Indian securities are refused](COMPUTATION.md#indian-securities-are-refused). `build` and `threshold`
  refuse it independently, so skipping `doctor` does not get past it.

Warnings, which do not block but each cost you something real:

- accounts **missing from `cash_balances.csv`**, named — Table A2 is understated by whatever
  uninvested cash they held;
- **splits** affecting a holding, so the basis decision surfaces now rather than mid-build;
- prices far from that day's market close (a clean 10x usually means a split-basis problem);
- dividends with no withholding tax — that is your Schedule TR credit;
- duplicate transaction rows, which is usually a double import;
- an account with no transactions at all, which is usually a typo in `account_id`.

## 4. Import into the utility — scripted and verified

> **This is the one step that needs Windows.** It runs on Windows itself or from WSL, and
> nowhere else. On macOS or plain Linux it stops immediately and points at the alternatives —
> see the [platform guide](PLATFORMS.md), which also covers the department's macOS utility.

```bash
itr-prep import --year 2025 --json out/schedule_fa_2025.json \
              --utility /path/to/pristine/ITR2_AY_26-27_V1.2.xlsm
```

About 45 seconds, unattended, from WSL. It drives Excel over COM via `powershell.exe` and:

1. takes a **fresh copy** of the pristine utility, refusing to overwrite an existing working
   copy — re-importing leaves blank rows that cannot be deleted;
2. clears the modal splash UserForm that blocks COM until dismissed;
3. sets **Part B-TTI item 19** to `Yes` (validation rule 746);
4. imports by calling `ParseJson` then `ImportScheduleFA`, the two functions
   `Sub ImportJson()` calls internally, bypassing its modal file picker;
5. repairs **leading-zero zip codes**, which the utility's numeric cell format silently
   truncates (`02210` → `2210`);
6. **reads every cell back and verifies it** — see [Verification](VERIFICATION.md);
7. saves, choosing a Purview sensitivity label if the tenant demands one (`--label`,
   default `Non-Business`).

Requires `C:\temp\itrprep` to be an Excel **Trusted Location**, or macros will not run; the
script says so plainly if they do not. Works for the prior-year utilities too — pass
`--utility` and the matching `--year`.

What remains manual, because it needs judgement rather than transcription: your personal
details, Schedule CG's share-by-share structure, Schedule OS/FSI/TR, then **Validate** and
**Generate JSON** in the utility, and uploading to the portal.

<details>
<summary>Manual import, if COM is not available</summary>

1. **Copy** the pristine `ITR2_AY_26-27_V1.2.xlsm` to a new filename and work in the copy.
2. Open it and click **Enable Content / Enable Macros**. Dismiss the splash form.
3. Fill in your personal details, or import your portal prefill JSON first.
4. Go to **Part B-TTI** and set **item 19** ("Do you at any time during the previous year
   hold... any asset located outside India") to **Yes**.
5. Click the **Import Draft ITR / Import JSON** button (the one wired to `Sub ImportJson()`).
   Acknowledge the message box, then pick your `schedule_fa_2025.json`.
6. Go to the **TR_FA** sheet and check by hand everything the verifier checks: row counts,
   `2-UNITED STATES OF AMERICA` in the country column, DD/MM/YYYY dates, the **last** row
   populated, leading-zero zip codes intact, and every rupee figure against
   `schedule_fa_2025_audit.csv`.
7. Enter the Schedule CG and Schedule OS/FSI/TR figures from
   `..._other_schedules.txt` by hand.
8. **Validate**, then **Generate JSON**, then upload to the portal.
</details>

If you already have a return in progress and don't want to re-enter it, build with
`--merge-into` instead, which injects Schedule FA into your existing JSON so one import
restores everything:

```bash
itr-prep build --year 2025 --work work \
             --merge-into ~/dl/my_prefill.json \
             --out out/complete_2025.json
```

With `--merge-into`, the whole document is validated against the schema, not just the
Schedule FA subtree.

> **On a corporate machine:** some managed tenants enforce sensitivity labels on save, so
> saving the workbook or using Generate JSON raises an **"Add sensitivity label"** dialog.
> The import handles this, defaulting to a label named `Non-Business` (override with
> `--label`). Do not choose an **encrypting** label: the resulting file cannot be read by
> the e-filing portal. A personal tax return on a work laptop is also worth a thought in
> its own right.

---

---

## Command reference

```
itr-prep init       --work DIR [--force]
itr-prep run        --year YYYY [--drop DIR] [--work DIR] [--out FILE]
                  [--account BROKER=ACCOUNT_ID ...] [--years 2022-2025]
                  [--peak-basis {usd,inr}] [--split-basis {current,historical}]
                  [--format {itr,prefill}] [--merge-into FILE] [--no-a2]
                  [--allow-dropped-rows] [--allow-indian-securities]
                  [--offline] [--no-validate]
itr-prep doctor     [--work DIR] [--years 2022-2025] [--no-prices] [--offline]
                  [--allow-indian-securities]
itr-prep import     --year YYYY --json FILE --utility FILE [--audit FILE]   # Windows/WSL
                  [--workdir 'C:\temp\itrprep'] [--name STEM] [--label NAME]
                  [--no-save] [--timeout SECS] [--verbose]
itr-prep fx-update  [--fx-cache PATH]
itr-prep normalize  --broker {etrade,fidelity,indmoney} --input FILE --account-id ID
                  [--out FILE] [--append] [--default-ticker SYM] [--acq-kind KIND]
                  [--allow-dropped-rows]
itr-prep build      --year YYYY --out FILE [--work DIR]
                  [--format {itr,prefill}] [--merge-into FILE]
                  [--peak-basis {usd,inr}] [--split-basis {current,historical}]
                  [--cash FILE] [--no-a2] [--allow-indian-securities]
                  [--offline] [--no-validate]
itr-prep threshold  [--years 2022-2025] [--work DIR] [--out FILE]
                  [--peak-basis {usd,inr}] [--split-basis {current,historical}]
                  [--cash FILE] [--allow-indian-securities] [--offline]
itr-prep unlock     [--input PATH] [--out-dir DIR] [--env-file FILE]
                  [--list-credentials]
itr-prep rules      [--assessment-year YYYY-YY] [--annual-only]
itr-prep validate   --json FILE [--schema FILE] [--year YYYY]
itr-prep cas-import --pdf FILE [--password PW] [--work DIR]
```

`cas-import` transcribes a Consolidated Account Statement PDF (the monthly CDSL/CAS
statement; password is the investor's PAN) into draft `mf_schemes.csv` /
`mf_transactions.csv` in `--work`. It infers each scheme's classification from the name
and prints every caveat it found — the output is a draft to review, not an answer, and
the command's closing checklist says exactly what to check before `build`.

Path overrides are deliberately left out above — `--transactions`, `--issuers`, `--accounts`,
`--overrides`, `--fx-cache`, `--price-cache` and `--schema` all point a command at a file
somewhere other than its default, and `--help` on any subcommand lists the ones it takes.
`--allow-dropped-rows` is in the list because it is not plumbing: an unreadable row is
**blocking**, and this is the only way past it. Read the named rows first — a dropped vest
understates Schedule FA. `--allow-indian-securities` is there for the same reason and is the
only way past a scope refusal — see
[Indian securities are refused](COMPUTATION.md#indian-securities-are-refused) before reaching for it.

`run` composes `fx-update`, `normalize`, `doctor`, `threshold` and `build`. It stops at the
first hard error and names the stage. The individual subcommands are unchanged and still work
on their own.

`--format itr` (default) produces `{"ITR":{"ITR2":{"ScheduleFA":...}}}` for the
**Import Draft ITR / JSON** button — this is the verified path. `--format prefill` produces
the camelCase `{"lastFiledITR":{"scheduleFA":...}}` shape that the separate
**Import Prefill** button reads; it is implemented from the VBA but was not round-tripped,
so prefer the default.

`--offline` uses only cached prices and your override CSV, never the network. Worth using
on filing day once the caches are warm.


---

## Layout

```
itrprep/
  models.py        intermediate schema + Lot/Transaction/Issuer/Account
  intermediate.py  reading and writing the intermediate CSVs, with loud errors
  adapters.py      stage 1: per-broker column-alias profiles, content-based detection,
                   CSV/TSV/XLSX reading
  doctor.py        preflight checks, collected rather than raised one at a time
  readback.py      verify what landed in Excel against the JSON and the audit CSV
  fx.py            SBI TT buying rates, cached, with carry-forward
  prices.py        daily closes from Yahoo's chart API, cached, with overrides
  positions.py     lot construction, daily timelines, peak value, cash, CG/dividend totals
  splits.py        corporate action detection, basis inference, restatement
  threshold.py     the Rs 20 lakh s.43 aggregate report
  emit.py          Schedule FA JSON, both formats, with the traps encoded
  validate.py      draft-aware validation against the official ITD schema
  rules.py         the only way code reaches a statutory figure, with staleness teeth
  scope.py         what may be disclosed: the Indian-securities refusal, in one place
  host.py          the only module that knows the import step needs a Windows Excel
  unlock.py        .env-sourced document passwords that never leave the process
  capgain.py       mutual fund FIFO lot engine: grandfathering, holding periods, bonus cost
  mf_input.py      reads mf_schemes.csv / mf_transactions.csv, assembles Schedule 112A
  cas_pdf.py       transcribes a CDSL CAS statement PDF into draft MF CSVs
  cli.py           command line
rules/
  AY2026-27.json   every statutory figure, cited, classed stable or annual and tagged
  AY2027-28.json   with how much code stands behind it
docs/
  PLATFORMS.md           where this runs; the four routes off Windows
  BROKERS.md             what to export from each supported broker
  DATA_DICTIONARY.md     every column of the input CSVs
  COMPUTATION.md         lots, FX, peak value, splits, Table A2 and cash
  OTHER_SCHEDULES.md     prior years; Schedule CG/OS/FSI/TR; Form 67 / Form 44
  STATUTE_REGISTRY.md    where every statutory figure comes from
  VERIFICATION.md        the eleven suites, live round-trips, supply chain
  RUNBOOK_AY2026-27.md   linear checklist from downloads to a filed return
  ANNUAL-REVIEW.md       what to re-verify before filing a new assessment year
  VERIFIED_FINDINGS.md   what the VBA and schema actually say, with line numbers
  ROUNDTRIP_RESULT.md    the real import test and its output
  MACOS_UTILITY_TEST.md  how to settle the macOS utility's two open questions, in 20 min
  AI-ASSISTANCE.md       what a model may and may not do with a real filing's figures
scripts/
  make_macos_import_test.py  builds that test's two JSON shapes over a 178-row Table A3
  macos_import_to_utility.py the macOS import: drives the Common Offline Utility via
                             Accessibility, reads every Schedule FA row back from the
                             utility's own upload JSON
  import_to_utility.py   the Windows scripted import: fresh copy, COM drive, readback, save
  clear_modals.ps1       clear the splash form, VBA MsgBoxes and the Purview label dialog
  probe_workbook.ps1     inspect the utility's named ranges and lock state
  roundtrip.ps1          the original manual round-trip driver, kept for reference
  pdf_to_csv.py          best-effort broker trade-confirmation PDFs -> CSV
  check_no_real_data.py  the leak scan this repo runs on itself and in CI
tests/
  synthetic/             the nasty-cases dataset + broker export fixtures (all invented)
  synthetic_split/       AVGO held through the July 2024 10-for-1 split
  make_xlsx_fixture.py   builds real XLSX files, single- and multi-sheet, with the stdlib
  test_pipeline.py       end-to-end invariants
  test_validation_teeth.py       proof the validation rejects the traps
  test_splits_cash_threshold.py  splits, cash balances, threshold report
  test_doctor_readback.py        preflight, header sniffing, import verification,
                                 schema resolution, the Indian-securities refusal
  test_multisection_adapter.py   per-section column resolution, gross/withheld/net,
                                 sell-to-cover, loud failure on a dropped row
  test_multisheet_workbook.py    every worksheet read, FMV over paid price, nested
                                 grant/vest/withholding records
  test_rules_registry.py         citations, review classes, code status, AY coverage,
                                 staleness
  test_unlock_credentials.py     adversarial: proof a password cannot escape
schemas/                 where to put the ITD schema; contents are not tracked
data/                    cached FX rates and prices (created by fx-update / build)
work/                    your own CSVs (gitignored -- never committed)
work/unlocked/           decrypted statements, 0600 in a 0700 directory (gitignored)
out/                     generated JSON and audit trails (gitignored)
AGENTS.md                what an agent must read before it changes anything
.env.example             the credential template; the real .env is gitignored
```

All eleven test suites are plain scripts with no test runner:

```bash
for t in tests/test_*.py; do .venv/bin/python "$t" || break; done
```

## On a network that intercepts TLS

Many corporate and some ISP-managed networks terminate TLS with their own certificate
authority. If `git clone` or `git push` fails with `SSL certificate problem: unable to get
local issuer certificate`, this is why, and there is a specific trap.

On Debian and Ubuntu, `git` is usually linked against **`libcurl3-gnutls`**, which **ignores
`CURL_CA_BUNDLE` and `SSL_CERT_FILE`** — the two variables everyone tries first, and the ones
that make `curl` and Python work. So `pip` and `curl` succeed while `git` alone keeps failing,
which reads like a git bug and is not. Check what yours is linked against:

```bash
ldd "$(git --exec-path)/git-remote-https" | grep -i curl
```

Point git at a bundle explicitly instead. It needs to be a **combined** bundle — the system
roots *plus* your network's CA — because replacing the system roots with the corporate CA
alone breaks every other host:

```bash
cat /etc/ssl/certs/ca-certificates.crt /path/to/corporate-ca.crt > ~/.certs/combined.pem
git config --global http.sslCAInfo ~/.certs/combined.pem
```

Scope it to one host if you would rather not change global behaviour:

```bash
git config --global http.https://github.com/.sslCAInfo ~/.certs/combined.pem
```

Get the CA certificate from your IT department, or export it from a browser that already
trusts the intercepted connection. For Python, `requests` reads `REQUESTS_CA_BUNDLE`, so
`export REQUESTS_CA_BUNDLE=~/.certs/combined.pem` covers `fx-update` and the price fetches on
the same network. **Never** work around this with `http.sslVerify=false` or
`REQUESTS_CA_BUNDLE` unset: unverified TLS while moving tax data is not a trade worth making.

The same applies on macOS, where git may be linked against a different TLS backend again —
`http.sslCAInfo` is the portable answer either way.
