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
  take **Utility for MAC** — version 1.2.2, released 17 July 2026, an 85 MB ZIP. Unzip it, open
  the DMG inside (`ITDe-Filing-2026-1.2.2.dmg`), drag the app to `/Applications`.

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
  from Excel/HTML utility"*; note the exact label 1.2.2 uses, which may differ.

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
