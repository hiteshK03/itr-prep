# Testing Schedule FA through the department's macOS Common Offline Utility

**About 20 minutes on an Apple Silicon Mac.** It settles the two questions the README's
[Where this runs](../README.md#where-this-runs) leaves open, and they decide whether next year's
filing has to touch Windows at all:

1. **Which shape of JSON does the import accept** — the partial
   `{"ITR":{"ITR2":{"ScheduleFA": …}}}` document this tool emits by default, or the complete
   return `itr-prep build --merge-into` produces? You try both, in that order.
2. **Does a large Schedule FA Table A3 survive the import with every row intact?**

The second is the one that matters. The department's *Excel* utility imports Schedule FA under
`On Error Resume Next`, so it drops rows with no error dialog and a partial import looks exactly
like a complete one — which is why `itr-prep import` reads every cell back afterwards. The desktop
app has no equivalent, so the only check available is a person's eyes. A few years of quarterly
vests across two or three accounts runs comfortably into the hundreds of Table A3 rows, and a
silent truncation there would be a Black Money Act exposure rather than a bug. So the test
dataset is 178 rows, built so that checking it by eye takes seconds.

Nothing in the kit is real. Every issuer, account number, quantity and price is invented. The
complete return carries the placeholder PAN `AAAAA9999A` this repository documents, and — for the
one verification field whose fourth character the schema requires to be `P` — a variant of it
derived at generation time rather than written into the tree.

---

## Step 1 — Generate the two files (5 min)

- [ ] **1.1** Clone this repository on the Mac and set it up. `setup.sh` builds the venv and
  caches the SBI TT-buying rates the build needs.

      git clone <this repo> itr-prep && cd itr-prep && ./setup.sh

- [ ] **1.2** Put the ITD's **ITR-2 schema for AY 2026-27** into `schemas/`. It is not
  redistributed here; [`schemas/README.md`](../schemas/README.md) says where to get it. The
  generator refuses to run without it, because an unvalidated test file proves nothing.

- [ ] **1.3** Generate the kit. It writes a gitignored `macos-utility-test/`.

      .venv/bin/python scripts/make_macos_import_test.py

- [ ] **1.4** Confirm it printed `Schema validation PASSED` twice — once for a *ScheduleFA
  subtree*, once for a *full ITR document* — and left two files in `macos-utility-test/out/`:

  - **Shape A**, partial: `schedule_fa_2025.json`
  - **Shape B**, complete return: `complete_return_2025.json`

  Their Schedule FA content is identical, so the envelope is the only variable between the two
  attempts. `macos-utility-test/EXPECTED.txt` holds the row counts and the first and last rows,
  read back out of the files themselves.

> No Python or no schema on the Mac? Generate elsewhere and copy those two JSON files across.
> Nothing else in the kit is needed on the Mac.

## Step 2 — Download and first-launch the utility (5 min)

- [ ] **2.1** From the portal's
  [Downloads → Income Tax Returns](https://www.incometax.gov.in/iec/foportal/downloads/income-tax-returns),
  take **Utility for MAC** — version 1.2.3, released 14 August 2026, an 85 MB ZIP. Unzip it,
  open the DMG inside (`ITDe-Filing-2026-1.2.3.dmg`), drag the app to `/Applications`.

- [ ] **2.2** The app is **arm64 only**, minimum macOS 11.0. Any Apple Silicon Mac is fine; an
  Intel Mac cannot run it at all and there is no point continuing on one.

- [ ] **2.3** It is **not notarised**, so the first launch reports it as damaged. Clear the
  quarantine attribute, then open it. Adjust the name if the DMG mounts something different, and
  note what you actually saw.

      xattr -dr com.apple.quarantine /Applications/ITDe-Filing-2026.app
      open /Applications/ITDe-Filing-2026.app

## Step 3 — Attempt A: import the partial document (3 min)

- [ ] **3.1** Start a **new ITR-2 return for AY 2026-27**.

- [ ] **3.2** On the *File Returns* screen, choose the option that takes a prepared JSON. The
  department describes it as *"Import draft ITR filled in Online mode or import JSON generated
  from Excel/HTML utility"*; note the exact label your version uses, which may differ.

- [ ] **3.3** Select `schedule_fa_2025.json`, and write down what happens — accepted, rejected,
  or accepted with a warning — including the wording of any message.

- [ ] **3.4** If it was accepted, set **Part B-TTI item 19** ("hold any asset located outside
  India") to **Yes**. Shape A carries Schedule FA and nothing else, so it cannot set this itself,
  and the return is invalid without it under validation rule 746.

- [ ] **3.5** Open **Schedule FA** and work through Step 5.

## Step 4 — Attempt B: import the complete return (3 min)

- [ ] **4.1** **Start from a clean state**: discard the draft from Step 3 and begin a new return.
  The Excel utility's importer leaves rows behind when you import twice into one workbook.
  Whether this app does is unknown, and a contaminated second attempt answers the wrong question.

- [ ] **4.2** Repeat 3.2, selecting `complete_return_2025.json` this time. It is a whole ITR-2 —
  personal details, the required computation blocks, `AssetOutIndiaFlag` already `YES`, and
  Schedule FA — so note whether the app treats it any differently from shape A.

  Its PAN is the placeholder, not yours. If the app refuses it on a PAN mismatch, that is a
  *rejection of the placeholder*, not of the shape: record it as such, and if you want the shape
  answered anyway, edit `PartA_GEN1/PersonalInfo/PAN` and
  `Verification/Declaration/AssesseeVerPAN` in your local copy of the file before retrying. Do
  not commit that copy — it is gitignored where the generator puts it, and it should stay there.

- [ ] **4.3** Work through Step 5 again.

## Step 5 — What to look at, and the correct answers

Scroll the whole of Table A3, in this order:

- [ ] **5.1 Row count: exactly 178.** Table A2, foreign custodial accounts: **exactly 3**.
- [ ] **5.2 The name column runs `ROW 001 OF 178` … `ROW 178 OF 178`, in order, no gaps.** Every
  row's *Name of entity* begins with its own position, so a dropped row shows as a jump and a
  reordered one as a number out of place. The *Address* column repeats that number
  (`Unit 001 of 178`, …): if a row's two numbers disagree, something moved between columns.
- [ ] **5.3 The acquisition date ascends all the way down**, `09/01/2023` to `12/06/2025`. A
  second, independent sequence — and the column most likely to be silently reformatted.
- [ ] **5.4 The first and last rows read exactly as in the table below.** The last row is the one
  that matters most: a truncating importer loses the *end* of the table, so a Table A3 that looks
  fine until you scroll to the bottom is the failure this whole exercise exists to catch.
- [ ] **5.5 ZIP codes keep their leading zeros** — all 178 are zero-padded, `00001` … `00178`.
  The Excel utility number-formats that cell and turns `02210` into `2210`; if this app does the
  same you will see `1` … `178`. Record it either way: it is a finding, not a test failure.
- [ ] **5.6 The deliberately uneven columns survived.** Exactly **17 rows** (every tenth) have a
  non-zero *gross amount paid/credited*. Exactly **2 rows** — positions **047** and **153** —
  have non-zero *gross proceeds* and a **nil closing value**. Those two nil balances are there on
  purpose: a legitimately zero rupee figure is a value importers get wrong.
- [ ] **5.7 On all 178 rows the peak exceeds the closing value**, and every row's country is the
  United States, code `2` — never blank, never a bare number. A quick scan for an exception
  catches a column that has been shifted or truncated.

| Field | First row | Last row |
|---|---|---|
| Name of entity | `ROW 001 OF 178 - FIRST ROW - SYNTHETIC TEST ISSUER` | `ROW 178 OF 178 - LAST ROW - SYNTHETIC TEST ISSUER` |
| Address | `Unit 001 of 178, 12 Import Test Road, Synthetic City, Nowhere State` | `Unit 178 of 178, 12 Import Test Road, Synthetic City, Nowhere State` |
| ZIP | `00001` | `00178` |
| Nature of entity | `Listed Company` | `Listed Company` |
| Date of acquisition | `09/01/2023` | `12/06/2025` |
| Initial value of investment | `82719` | `236439` |
| Peak value during the period | `119715` | `329513` |
| Closing value | `92172` | `253701` |
| Gross amount paid/credited | `0` | `0` |
| Gross proceeds | `0` | `0` |

The rupee figures are from the run that wrote this file. They are reproducible from the same SBI
rate series, but `macos-utility-test/EXPECTED.txt` is read back out of *your* generated files and
is the authority if the two ever disagree.

What Step 5 proves is that every row arrived, in order, with its text intact. It does not check
all 178 rows' rupee figures — only the first and last — so it would not catch a value mangled in
the middle of the table. If the app can export or save its own JSON, do that afterwards and diff
its `ScheduleFA` against `schedule_fa_2025.json`; that turns the eye-check into a real read-back
and is worth the extra five minutes.

## Step 6 — Record the outcome

- [ ] **6.1** Add a short dated section at the foot of this file: utility version and build date,
  macOS version, which of shapes A and B were accepted, the Table A3 row count you actually saw
  for each, the leading-zero result from 5.5, and the exact wording of anything the app said. The
  department ships new builds mid-season, so this answer expires.
- [ ] **6.2** If it passed, update the two places in the README that currently say the macOS
  import is untested: the *What is not established* paragraph under
  [Where this runs](../README.md#where-this-runs), and the matching *Known limitations* entry.

## If the import fails or truncates

That is a real possible outcome and it does not leave you stuck. Fall back to route 4 in the
README: **Windows 11 for Arm in a VM**, where `itr-prep import` runs unchanged and reads every cell
back, which is the path with a verified round-trip behind it. Try
**[VMware Fusion](https://www.vmware.com/docs/desktop-hypervisor-faqs)** first — free for all use
including commercial since March 2025, and this is one workbook a year rather than a daily
driver. Buy **[Parallels Desktop](https://www.parallels.com/products/desktop/microsoft-authorized-solution-windows-11-arm/)**
(Standard, $99.99/year) only if Fusion's Windows-on-Arm support disappoints; it is the only
virtualisation product Microsoft has authorised for Windows 11 on Apple silicon.

Either way, record the failure above. Knowing the macOS route does *not* carry a large Table A3
is worth as much as knowing it does.

---

## Test outcome — 25 August 2026

Run on the department's **Common Offline Utility v1.2.3** for AY 2026-27 — the *Utility for
MAC* release of **14 August 2026** (85.3 MB ZIP, DMG `ITDe-Filing-2026-1.2.3.dmg`) — on
**macOS 26.5.2**, Apple Silicon. Quarantine cleared with
`xattr -dr com.apple.quarantine /Applications/ITDe-Filing-2026.app` as step 2.3 describes.
The kit was generated with `scripts/make_macos_import_test.py`; both shapes printed
`Schema validation PASSED`, against `ITR-2_2026_Main_V1.2.json` re-verified byte-identical
to what the portal serves.

| | Shape A — partial ScheduleFA | Shape B — complete return |
|---|---|---|
| Accepted | **No** | **Yes** |
| Table A3 rows seen | — (import not admitted) | **178** |
| Table A2 rows seen | — | **3** |

**Shape A.** `schedule_fa_2025.json` attached cleanly through the *Excel/HTML utility* import
option, but the app's **Proceed button stayed disabled and no message appeared** — silent
rejection, no error text of any kind. Nothing was imported, so step 3.4 (Part B-TTI item 19)
was never reached. The shape this tool emits by default is not what the utility wants.

**Shape B.** `complete_return_2025.json` imported and passed Internal Validation with the
app's exact words: *"Validation successful! No errors were found."* One finding on the way:
the first attempt failed Internal Validation until four `PartA_GEN1/FilingStatus` fields were
added that the JSON schema does not make mandatory — `ConditionsResStatus`,
`BenefitUs115HFlg`, `PortugeseCC5A`, `CompDirectorPrvYrFlg`. The generator now supplies them.
A discard-previous-details dialog can also appear on a re-run if a draft already exists; it
must be dismissed before the import option is offered.

**Read-back (the point of the exercise).** The utility generated its own upload JSON
(`AAAAA9999A_upload_2026-27…json`, ~93 KB) and a field-by-field diff of its `ScheduleFA`
against the input reported:

    ok — Schedule FA verified field by field: Table A3 178 row(s), Table A2 3 row(s), every value identical

Because every value was identical, this settles steps 5.1–5.7 by construction: row counts and
order (5.1), the `ROW nnn OF 178` name/address sequences (5.2), acquisition dates ascending
in ISO order (5.3), the exact first and last rows of the table above (5.4), the 17 non-zero
gross-paid rows and the two nil-closing rows at 047 and 153 (5.6), and peak > closing with
country code `2` on every row (5.7). For **5.5 leading zeros: preserved** — ZIP codes
round-tripped zero-padded, `00001` … `00178`; unlike the Excel utility, this app does not
number-format the field.

Caveats worth keeping:

- The app deletes its upload JSON when the session ends; the read-back must run live during
  the session, against the file it has just written.
- Import is driven through the app's Accessibility tree (AppleScript) rather than by eye —
  deterministic, no screenshots in the loop — with `scripts/macos_import_to_utility.py` as
  the macOS analog of `itr-prep import`. One trap that implementation records: the utility's
  action buttons are unlabeled in the accessibility tree (labels are painted onto the
  webview canvas), and the validation screen's `floatRight` buttons render in reversed DOM
  order, so the visually rightmost button is **Preview** (which walks into the login flow),
  not Download JSON. The script therefore presses Download JSON by position: exclude the
  leftmost wide button (Back), press the next one. With that, a fully unattended run on
  25 August 2026 completed splash → import → questionnaire → validation → export → row
  read-back with exit 0.
- On macOS 26 the system reports that this app "includes a component that will not work with
  the future release of macOS." The component is the bundled **wkhtmltopdf** — Intel-only
  (x86_64), running under Rosetta 2; the utility's own binaries are arm64. It renders the PDF
  preview only. It does not affect the import or the upload-JSON generation, and 1.2.3 is the
  latest build the department publishes, so there is nothing to update to.

**Verdict:** the macOS route carries a large Table A3. Import the complete return
(`--merge-into`), not the default partial document, and read the rows back from the utility's
own upload JSON. As of 1.2.3, next year's filing does not need to touch Windows.

---

## When the department ships a new build

The portal's *Utility for MAC* bumps versions mid-season (1.2.2 → 1.2.3 within a month). The
automation presses buttons by position, so a new build is the dangerous case — a moved button
is a silent misclick. `scripts/macos_import_to_utility.py` therefore carries a version gate:

1. **At startup it compares installed vs portal.** `--check-version` reports the two numbers
   alone; a normal run prints both and warns when the portal is ahead. Neither case blocks an
   *up-to-date* run — only an untested build does.
2. **It refuses to drive a build the kit has not passed on.** The gate compares the installed
   build against `VERIFIED_UTILITY_VERSION` (the build the "Test outcome" section above was
   run against) and exits `3` if they differ. This is the protection that matters: the
   positional clicks are only safe on the layout they were verified against.
3. **`--force` is the escape hatch** once you have re-validated the new build yourself.

**Re-validating a new build** (about ten minutes):

1. Download the new *Utility for MAC* ZIP, install over `/Applications/ITDe-Filing-2026.app`,
   clear quarantine (`xattr -dr com.apple.quarantine /Applications/ITDe-Filing-2026.app`).
2. If the portal also published a newer ITR-2 schema, replace `schemas/ITR-2_2026_Main_V1.2.json`
   and regenerate the kit (`scripts/make_macos_import_test.py`) so the test data matches the
   new rules.
3. Run the kit against the new build with `--force` (the build is unverified by definition):

       .venv/bin/python scripts/macos_import_to_utility.py \
         --json macos-utility-test/out/complete_return_2025.json --year 2025 --force

4. If it exits 0 with `IMPORT VERIFIED`, bump `VERIFIED_UTILITY_VERSION` in the script to the
   new version and add a dated line to the outcome table above. If it fails, do **not** bump —
   fall back (next section) and fix the automation before trusting the new layout.

**If the new build breaks the automation** (buttons moved, screens added, the splash changes):

The gate means this can never bite silently — it refuses to run, so the worst case is a stalled
filing, not a wrong one. Your options, in order:

- **Run the same steps by hand.** Every screen the script drives has a labelled button on the
  screen (the labels are just invisible to the accessibility tree). The checklist above is the
  manual version; import the complete return, watch the validation screen, download the JSON,
  and diff it yourself against the input.
- **Fix the positional selectors.** The script isolates each screen's button geometry in one
  helper each (`press_rightmost_unlabeled`, `press_download_json_button`, `select_excel_html_import`);
  re-probe the new layout with a short AppleScript `entire contents` dump and adjust. The
  floatRight reversal trap (rightmost = Preview, not Download JSON) is the one to re-check
  first.
- **Fall back to the verified route.** The README's route 4 — Windows 11 on Arm in a VM,
  where `itr-prep import` reads every cell back through COM — has a proven round-trip and is
  unaffected by whatever the macOS app changed.
