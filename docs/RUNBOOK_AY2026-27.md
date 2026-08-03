# Runbook — filing ITR-2 with Schedule FA for AY 2026-27

**Deadline: 31 July 2026.** Reporting period for Schedule FA: **1 January – 31 December 2025**.

This is a single linear checklist. Follow it top to bottom. You should not need to read
anything else; where detail matters it is inline. Tick each box as you go.

Rough timings assume the broker downloads work first time. Budget half a day.

---

## Before anything else: a note on AIS

Three facts, offered because they are easy to learn too late. **None of this is tax or legal
advice**, and whether any of it matters in a given case depends on facts this runbook cannot
know.

1. **The department publishes foreign-asset information in AIS**, and it can be useful for
   reconciliation.
2. **Downloading it is logged** against the PAN, one calendar year at a time, and cannot be
   undone. AIS feedback is likewise acknowledged, one-shot per category, and cannot be
   withdrawn.
3. **That log may bear on eligibility to file an updated return.** Section 139(8A) bars an
   updated return in certain circumstances, including where information received under an
   agreement referred to in s.90 or s.90A has been communicated to the assessee — a bar that
   operates per assessment year.

**So take professional advice before downloading**, particularly if there is any prospect of
needing to file or revise a return for an earlier year. If advice says go ahead, AIS is a
useful cross-check.

Nothing below needs it. This runbook reconstructs everything from broker statements, which is
independently defensible and reproducible years later from the audit CSVs.

---

## Stage 0 — Set up (15 min, do this first, it needs the network)

- [ ] **0.1** Open a terminal and set up the tool:

      git clone https://github.com/hiteshK03/itr-prep.git
      cd itr-prep
      ./setup.sh
      alias itr-prep="$PWD/.venv/bin/python -m itrprep.cli"

- [ ] **0.2** Refresh exchange rates so filing day needs no network:

      itr-prep fx-update

      Should print roughly 1,600 cached SBI TT-buy rates. These are the rates Schedule FA
      requires; nothing else is acceptable.

- [ ] **0.3** Create the working files:

      itr-prep init --work work

      Writes `transactions.csv`, `issuers.csv`, `accounts.csv`, `cash_balances.csv` and
      `prices_override.csv` into `work/`, each with example rows.

- [ ] **0.4** **Delete every row marked `example row - delete me`** from all five files.
      Leaving them in files a return with fictitious holdings. `itr-prep doctor` refuses to
      let you build until they are gone, so this is checked rather than trusted — but do
      it now while you are in the files anyway.

- [ ] **0.5** Confirm you have a **pristine, untouched** copy of `ITR2_AY_26-27_V1.2.xlsm`
      stored somewhere you will not accidentally edit. You will copy from it repeatedly.
      Get the current version from the ITD downloads page if unsure.

- [ ] **0.6** The Excel utility only runs macros from a **Trusted Location**. Open Excel →
      *File → Options → Trust Center → Trust Center Settings → Trusted Locations → Add new
      location*, and add `C:\temp\itrprep`. Without this the scripted import cannot call the
      utility's own import code and will tell you so.

      Steps 0.5 and 0.6 are for Stage 5 only, and Stage 5 needs Excel for Windows. If you are
      on a Mac, read the README's **Where this runs** before you get there — everything up to
      Stage 4 works on your machine.

---

## The short version

Two commands do everything that can be automated:

      itr-prep run    --year 2025 --drop ~/dl
      itr-prep import --year 2025 --json out/schedule_fa_2025.json \
                    --utility /path/to/pristine/ITR2_AY_26-27_V1.2.xlsm

The first turns a folder of broker exports into a validated Schedule FA JSON. The second
imports it into a fresh copy of the Excel utility and **verifies every imported cell**
against the audit trail. Neither can be run usefully until `work/issuers.csv`,
`work/accounts.csv` and `work/cash_balances.csv` are filled in, because no broker export
contains an issuer's registered address or your account's peak cash balance.

The stages below are that same pipeline, spelled out. Read them the first time through:
`run` will stop and ask for a decision at two points (the ₹20 lakh verdict, and a stock
split if you hold one), and those decisions are yours, not the tool's.

---

## Stage 1 — Download from the brokers (60–90 min, the slowest stage)

You need **every acquisition ever made** that you still held at any point in 2025 — not
just 2025's. Table A3 needs each lot's original acquisition date and cost however old it is,
and a sale with no matching purchase is rejected.

### 1A — E\*TRADE / Morgan Stanley

- [ ] **1.1** *Stock Plan → Holdings → Benefit History* → **Download**. Must contain:
      symbol, transaction type (release/vest/ESPP purchase), date, quantity, and the
      **vest-date fair market value per share**.
- [ ] **1.2** *At Work → My Account → Gains & Losses*, filtered to **all years** with sales.
      Must contain sale date, quantity, sale price, and ideally the lot sold.
- [ ] **1.3** ESPP purchase confirmations, if the Benefit History omits the purchase price.
- [ ] **1.4** The **2025 year-end statement**, for the cash balance and to confirm the share
      count at 31 December.

### 1B — Fidelity NetBenefits (if it administers your ESPP)

- [ ] **1.5** *Stock Plans → [your plan] → Transaction History*, date range covering
      **every year from account opening**, not just 2025. Must contain purchase date, shares,
      **purchase price per share**.
- [ ] **1.6** **Annual statements for every year the account has existed.** You need these
      for the threshold report in Stage 3 and to confirm share counts at each 31 December.
- [ ] **1.7** Dividend history, if dividends were paid into the account rather than swept
      to a bank account.
- [ ] **1.8** The **account opening date**. If it predates 2023, say so — it changes which
      assessment years are in default.

### 1C — INDmoney (US stocks)

- [ ] **1.9** *US Stocks → Portfolio → Reports / Transaction History* → export CSV, date
      range covering **all years**.
- [ ] **1.10** The **dividend report**, including **US tax withheld** (usually 25%).
- [ ] **1.11** A **US brokerage statement**. Table A2 must name the **US broker** whose books
      you are on — historically DriveWealth LLC — with its legal name, address and your
      account number. Not INDmoney. Take this from your own statement.
- [ ] **1.12** Cash balances: highest during 2025 and the balance at 31 December 2025.

### 1D — From your own records

- [ ] **1.13** Account **opening dates** for every foreign account.
- [ ] **1.14** Form 1042-S or equivalent US withholding summary, for Form 67 / Schedule TR.

---

## Stage 2 — Build the intermediate data (30–45 min)

- [ ] **2.1** Put every broker export in one folder — `~/dl` below. **Filenames do not
      matter**; each file is classified by its header row, so `Download (3).csv` is fine.
      CSV, TSV and XLSX all work. Then:

      itr-prep run --year 2025 --drop ~/dl

      This chains the whole pipeline: exchange rates (skipped if already cached), normalize
      every export it finds, preflight checks, the threshold report, and the build. It stops
      at the first hard error and names the stage.

      Stage 2 of its output prints a table of what it matched each file to, and the evidence
      it used. **Read that table.** If a file was matched to the wrong broker, the rows will
      be wrong in ways later checks cannot see. A file it cannot classify is named and the
      run stops rather than guessing.

      If an account cannot be matched to an export, say so explicitly:
      `--account etrade=etrade_stockplan`.

- [ ] **2.2** **Open `work/transactions.csv` and read it.** `doctor` (run automatically as
      stage 3) checks what is checkable: that every `SELL` has shares to sell, that vest
      prices are neither zero nor far from that day's market close, that dividend rows carry
      both an amount and a withholding figure, and that no two rows are accidental
      duplicates. What it cannot check is whether a number is *your* number. Skim it.

      To run the checks alone, at any time:

      itr-prep doctor --work work

      It reports everything actionable in one pass and prints `READY TO BUILD` when clean.
      Errors block a build; warnings do not, but each one is something that will quietly
      make the return wrong — most often an understated Table A2.

- [ ] **2.3** Fill `work/issuers.csv` — one row per ticker, describing the **issuing
      company** (the employer whose stock it is, the ETF's issuer), never the broker. Name,
      address, ZIP and nature are all mandatory.

- [ ] **2.4** Fill `work/accounts.csv` — one row per foreign account, describing the
      **broker**. Real account numbers, real opening dates. Leave `status` as `OWNER` unless
      it genuinely is not.

- [ ] **2.5** Fill `work/cash_balances.csv` — one row per account per year:

      account_id,year,peak_usd,peak_date,closing_usd,notes
      indmoney_us,2025,1250.00,2025-07-15,310.42,from Dec statement

      Leave `peak_date` blank if you do not know it; the peak is then converted at the
      31 December rate and the assumption is recorded in the audit CSV. Skipping this file
      understates Table A2 — `doctor` names every account-year that is missing one.

- [ ] **2.6** Re-run `itr-prep run --year 2025 --drop ~/dl` now that the three descriptive
      files are filled in. It is safe to repeat: normalizing again replaces each account's
      rows rather than adding to them.

      *If you would rather drive the stages individually* — or a broker export defeats the
      sniffer — every subcommand still works alone:

      itr-prep fx-update
      itr-prep normalize --broker etrade --input ~/dl/whatever.csv \
                       --account-id etrade_stockplan --out work/transactions.csv --append
      itr-prep doctor    --work work
      itr-prep threshold --work work --years 2022-2025
      itr-prep build     --year 2025 --work work --out out/schedule_fa_2025.json

      Hand-filling `transactions.csv` produces identical output to the adapters, so a broker
      whose export cannot be parsed is an inconvenience, not a blocker.

---

## Stage 3 — The ₹20 lakh threshold report (10 min — do not skip)

Run this **before** filing anything, even if you only care about 2025. It is the number that
decides your exposure on the years whose Schedule FA was omitted.

- [ ] **3.1** Run it across every year, starting at 2022:

      itr-prep threshold --work work --years 2022-2025 --out work/threshold_report.txt

- [ ] **3.2** Read the SUMMARY table. For each year you get an **OVER / UNDER ₹20,00,000**
      verdict on a peak basis and on a 31 December basis.

- [ ] **3.3** If a year says **`NO DATA`**, that does *not* mean nil. It means your
      `transactions.csv` has nothing covering it. If an account was open and funded that
      year, go back to Stage 1 and get its history. This matters most for **2022**: if the
      Fidelity account predates 2023 then AY 2023-24 is also in default, at a higher
      additional-tax rate.

- [ ] **3.4** If you see a **STRADDLE WARNING**, stop and take advice on that year before
      filing anything for it. It means the two valuation bases fall on opposite sides of the
      line, and the proviso does not say which applies. The gap is ₹10,00,000 of penalty per
      assessment year, turning on an unsettled point of law. This is the single place where
      a professional fee is obviously worth paying.

- [ ] **3.5** Keep `work/threshold_report.txt` and `work/threshold_report_audit.csv`. They
      are the working behind whatever position you take.

---

## Stage 4 — Build the Schedule FA JSON (10 min)

- [ ] **4.1** Build for calendar 2025:

      itr-prep build --year 2025 --work work --out out/schedule_fa_2025.json

- [ ] **4.2** **If the build stops with `STOCK SPLIT DETECTED`,** read the message. It names
      the ticker, the split date and the ratio, and tells you whether your rows look
      pre-split or post-split. Confirm against a broker statement dated *after* the split:
      - share count matches your CSV → re-run with `--split-basis current`
      - your CSV shows the smaller, older count → re-run with `--split-basis historical`

      Do not guess. AVGO's 10-for-1 split of 15 July 2024 makes this a factor-of-ten error,
      easily enough to flip the threshold verdict above.

- [ ] **4.3** Confirm the output says **`Schema validation PASSED`**. If it does not, the
      errors name the exact field. Fix and rebuild. Do not import a file that failed.

- [ ] **4.4** Sanity-check the printed totals against what you believe you hold. A3 row count
      should be one per acquisition lot held during 2025 — a few years of quarterly vests
      legitimately produces dozens.

- [ ] **4.5** You now have three files in `out/`:
      - `schedule_fa_2025.json` — import this
      - `schedule_fa_2025_audit.csv` — every row's working
      - `schedule_fa_2025_other_schedules.txt` — Schedule CG and dividend figures

Optional: if you already have a return in progress, build with
`--merge-into ~/dl/my_prefill.json` so one import restores everything, not just Schedule FA.

---

## Stage 5 — Import into the Excel utility (5 min, scripted)

> **This is the only stage that needs Windows.** Stages 0–4 run anywhere; this one drives the
> department's `.xlsm`, which only Excel for Windows can run. On a Mac, `itr-prep import` stops
> and says so. Read the README's **Where this runs** before starting: the department publishes
> a macOS Common Offline Utility that covers ITR-2 and takes an imported JSON, but it is
> Apple Silicon only and nothing here has been tested through it, so a Windows VM is the route
> with a verified round-trip behind it. [`MACOS_UTILITY_TEST.md`](MACOS_UTILITY_TEST.md) is a
> twenty-minute checklist for settling that, and it is worth doing before next year rather
> than mid-filing.

- [ ] **5.1** Run the import:

      itr-prep import --year 2025 --json out/schedule_fa_2025.json \
                    --utility /path/to/pristine/ITR2_AY_26-27_V1.2.xlsm

      Takes about 45 seconds. Excel will open and flicker; leave it alone. This does, in
      order: takes a fresh copy of the pristine utility; clears the splash form that blocks
      automation; sets **Part B-TTI item 19** to `Yes`; imports the JSON by calling the
      utility's own import functions directly, bypassing its file-picker dialog; repairs
      leading-zero zip codes; reads back every cell and verifies it; and saves, choosing a
      sensitivity label if your tenant demands one.

      > **Fresh copy every attempt, and never a reused one.** The importer clears the A3
      > cell *contents* but leaves the *rows* it inserted, so importing twice into one
      > workbook gives you filled rows plus blank ones you cannot delete. The script refuses
      > to write over an existing working copy for exactly this reason. If a run fails,
      > delete the copy and run again — do not re-import.

- [ ] **5.2** **Read the verification block.** It ends in `PASS` or `FAIL`:

      PASS -- every imported cell matches the generated JSON and the audit trail.

      This replaces eyeballing the spreadsheet, and it is stricter than a person would be.
      It checks the Table A3 and A2 row counts, that the country column renders as
      `2-UNITED STATES OF AMERICA` rather than blank or a bare `2`, that dates render as
      DD/MM/YYYY, that the **last** row is populated (where a truncated import shows), that
      the one-letter nature-of-amount code expanded to the right label, and **every rupee
      figure in every row** against `schedule_fa_2025_audit.csv` — not two sampled rows.

      This matters because the utility's importer runs under `On Error Resume Next`: it
      cannot report a failure. A silent partial import looks exactly like a successful one.

      On `FAIL` you get a table of expected-versus-actual per cell. Delete the working copy,
      fix the input, and re-run. **Do not file a workbook that failed.**

- [ ] **5.3** On a managed corporate machine, Excel may refuse to save without a
      sensitivity label. The script picks a label named **Non-Business**, which is
      accurate for a personal tax return, and prints which label it applied. Override with
      `--label "<your label>"` if your tenant names its labels differently.

      > Do not choose an **encrypting** label (usually `Confidential` or `Restricted`, shown
      > with a padlock). It produces a file the e-filing portal cannot read.

- [ ] **5.4** Fill in your personal details in the workbook, or import your portal prefill
      JSON. (Alternatively build with `--merge-into ~/dl/my_prefill.json` at Stage 4 so a
      single import restores everything at once.)

<details>
<summary><b>Manual import — the fallback if the script cannot run</b></summary>

Use this if Excel is not reachable from WSL, if macros cannot be trusted, or if the scripted
import fails in a way you cannot fix. The result is identical; only the verification is
weaker, because it depends on you.

1. **Copy** the pristine `.xlsm` to a new filename. Work only in the copy, and take a new
   copy for every attempt.
2. Open it, click **Enable Content / Enable Macros**, dismiss the splash form.
3. Go to **Part B-TTI** and set **item 19** ("Do you at any time during the previous year
   hold ... any asset located outside India") to **Yes**. This is validation rule 746: the
   Schedule FA import works without it, but the return is invalid.
4. Click **Import Draft ITR / Import JSON**, acknowledge the message box, and pick
   `out/schedule_fa_2025.json`.
5. On the **`TR_FA`** sheet, check by hand what the script checks automatically:
   - Table A3 has **exactly** the row count the build printed;
   - the country column reads `2-UNITED STATES OF AMERICA`, not blank and not `2`;
   - dates render as DD/MM/YYYY;
   - the **last** A3 row is populated — a truncated import shows up at the end;
   - Table A2 has one row per account, with peak and closing balances including cash;
   - **zip codes beginning with a zero** are intact. The zip cell is number-formatted, so
     the importer turns `02210` into `2210`. Format the cell as Text and retype it. This
     affects the whole of New England plus NJ, NY and PR;
   - every rupee figure in **every** row matches `schedule_fa_2025_audit.csv`. Sampling two
     rows is what the scripted path exists to replace; a dropped row 19 is invisible to it.

If anything is wrong: discard the copy, fix the input, start again from a fresh one.
</details>

- [ ] **5.7** Enter by hand, from `out/schedule_fa_2025_other_schedules.txt` — these are on
      the **financial year** 2025-26, not the calendar year:
      - [ ] **Schedule CG**, short-term block (held ≤ 24 months): full value of consideration
            and cost of acquisition.
      - [ ] **Schedule CG**, long-term block (held > 24 months): the same two figures.
            Foreign shares are unlisted for Indian purposes, hence 24 months rather than 12.
      - [ ] **Schedule OS** — gross foreign dividend in INR.
      - [ ] **Schedule FSI** — the same dividend, against country code 2.
      - [ ] **Schedule TR** — US tax withheld, as the foreign tax credit claimed.

      These are deliberately not auto-filled: Schedule CG's structure depends on choices
      about section, indexation and set-off that the tool has no business making.

- [ ] **5.8** **File Form 67 on the portal.** Foreign tax credit in Schedule TR is not
      allowed without it, and it is a separate online form. Rule 128(9), as substituted by
      **CBDT Notification No. 100/2022 dated 18 August 2022**, allows it **on or before the
      end of the assessment year — 31 March 2027 for AY 2026-27** — provided this return is
      filed within the s.139(1) or s.139(4) window. Filing it before the return is still the
      tidier order, since Schedule TR has to agree with it. For a **prior year filed under
      s.139(8A)** the proviso is stricter and the order is mandatory: Form 67 must be
      furnished on or before the updated return, never after it.

---

## Stage 6 — Validate, generate, file (20 min)

- [ ] **6.1** Click **Validate** on each sheet the utility flags, then the whole workbook.

- [ ] **6.2** Click **Generate JSON**.

      > **Sensitivity label prompt.** On a managed corporate machine, saving the workbook or
      > generating JSON may raise an **"Add sensitivity label"** dialog, because some tenants
      > enforce a labelling policy. It is not an error and not caused by the import. Pick any
      > non-encrypting label your policy allows and continue; it does not alter the data. If
      > the dialog seems to hang, it may be behind the Excel window.

- [ ] **6.3** Log in to the e-filing portal and upload the generated JSON.

- [ ] **6.4** Before submitting, open Schedule FA **on the portal** and confirm the row count
      matches. The portal is the last place a silent truncation can surface.

- [ ] **6.5** Submit and **e-verify**. An unverified return is not filed.

- [ ] **6.6** Archive, together: the generated JSON, the acknowledgement, every broker export
      you started from, `schedule_fa_2025_audit.csv`, `threshold_report.txt` and its audit
      CSV. Black Money Act assessments reach back a long way, and the audit CSV is what lets
      you reconstruct any figure years later.

---

## Stage 7 — The earlier years, if the threshold report says you need to

Only if Stage 3 showed a year over ₹20,00,000, or straddling it, and that year's Schedule FA
was omitted from a return already filed. **Take advice before filing an updated return** —
the additional tax rate rises with time and the eligibility conditions are narrow.

Calendar year → assessment year → utility:

| `--year` | Assessment year | Utility |
|---|---|---|
| 2024 | AY 2025-26 | `ITR2_AY_25-26_V1.2.xlsm` |
| 2023 | AY 2024-25 | `ITR2_AY_24-25_V1.8.xlsm` |

- [ ] **7.1** Build that year:

      itr-prep build --year 2024 --work work --out out/schedule_fa_2024.json \
                   --schema schemas/ITR-2_2025_Main_V1.1.json

- [ ] **7.2** Download the utility **for that assessment year** from the ITD downloads page.
- [ ] **7.3** In that utility, select **s.139(8A)** on the `Part A Gen_139(8A)` sheet and
      complete **Part B ATI**.
- [ ] **7.4** Import with the same command as Stage 5, pointing at that year's utility:

      itr-prep import --year 2024 --json out/schedule_fa_2024.json \
                    --utility /path/to/ITR2_AY_25-26_V1.2.xlsm

      The Schedule FA import path is identical across all three years: the
      `ImportScheduleFA` VBA is character-for-character the same, reads the same 63 JSON
      keys, uses the same named ranges, and writes to the same `TR_FA` sheet. **Both
      prior-year utilities have been live-tested end to end with this script and passed full
      cell-by-cell verification** — AY 2025-26 (`V1.2`) and AY 2024-25 (`V1.8`).
- [ ] **7.5** Item 19 is set for you by the script, as in Stage 5. If importing by hand, set
      **Part B-TTI item 19** to **Yes** for that year too.
- [ ] **7.6** **Take advice before downloading that year's AIS foreign-asset report**, if it
      has not been downloaded already. The s.139(8A) bar operates per assessment year and the
      report downloads one calendar year at a time, so the decision is a per-year one rather
      than once-for-all — see the note at the top of this page. Reconstructing from broker
      statements needs no AIS either way.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `STOCK SPLIT DETECTED` | A holding spans a split | Confirm the basis against a post-split statement, re-run with `--split-basis` |
| `SELL ... exceeds the shares held` | An acquisition is missing | Add the original `BUY`, however old |
| `no matching BUY for that ticker` | Same | Same |
| `No daily prices available for X` | Symbol renamed/delisted, or the fetch failed | Add rows to `prices_override.csv` (`ticker,date,close_usd`) |
| `SCHEMA VALIDATION FAILED` | A field is the wrong type or too long | The message names the field; fix and rebuild |
| Blank rows at the end of Table A3 | You imported twice into one file | Start from a fresh copy of the `.xlsm` |
| `import` says the target already exists | Guard against re-importing | Delete that working copy, or pass `--name` |
| `cannot invoke VBA: macros are disabled` | Working folder is not trusted | Add `C:\temp\itrprep` as an Excel Trusted Location (step 0.6) |
| `import` hangs, then times out | A modal dialog the watcher does not know | Re-run with `--verbose`; the stage trace in the workdir names where it stopped |
| Zip code lost its leading zero | The utility's zip cell is numeric | The scripted import repairs it; by hand, format as Text and retype |
| Country column blank in `TR_FA` | Country code emitted as a number | Should not happen — check `country_code` in your CSVs is `2` |
| "Add sensitivity label" dialog | Corporate labelling policy | Expected. Pick a non-encrypting label and continue |

Add `--offline` to any `build` or `threshold` run to work purely from cached prices and
`prices_override.csv`. Worth using on filing day once the caches are warm.
