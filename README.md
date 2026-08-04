# itr-prep — Schedule FA from broker exports, for the ITD ITR-2 Excel utility

### Scope today: ITR-2 only

This produces **Schedule FA** (foreign asset disclosure) and the Schedule CG, OS, FSI and TR
figures that depend on it, for India's **ITR-2**, from US broker exports. That is the whole of
what it does.

It does **not** prepare ITR-1, ITR-3 or ITR-4, and it does **not** cover Indian mutual funds,
Indian-sourced capital gains, salary, house property, regime comparison or Chapter VI-A
deductions. The name is deliberately broader than the tool, because the direction of travel is
wider — but the direction is not the product. [Roadmap](#roadmap) says what is intended, and
says plainly that none of it exists yet.

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

## Read this first: six things that will bite you

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
   [Stock splits](#stock-splits-the-build-stops-rather-than-guess) — a wrong answer here is
   a factor-of-ten error, not a rounding one.

---

## Where this runs

**Everything except the last step is plain Python and runs on macOS, Linux and Windows
alike.** Parsing broker exports, reconstructing lots, FIFO and same-day matching,
specified-date FX conversion, split restatement, the ₹20 lakh threshold report, schema validation and writing
the Schedule FA JSON and its audit CSV — none of that touches a platform. CI runs the whole
test suite on Linux and macOS to keep it that way.

**One step needs a Windows Excel: `itr-prep import`.** It drives the department's `.xlsm`, and
that workbook cannot run anywhere else — see below for why. `itrprep/host.py` is the only
module that knows this; run `import` anywhere else and it stops immediately and tells you
what to do instead, rather than failing somewhere inside a subprocess.

| | macOS | Linux | Windows / WSL |
|---|---|---|---|
| `init` `normalize` `doctor` `threshold` `build` `run` `validate` `rules` `unlock` `fx-update` | ✅ | ✅ | ✅ |
| `import` (drives the ITD Excel utility) | ❌ | ❌ | ✅ |

There are no Windows-only Python packages to install: the dependency is Excel itself, driven
through `powershell.exe`, so `requirements.txt` is the same everywhere.

### The four routes off Windows, and what each is worth

Researched on **3 August 2026**. Re-check before relying on any of it; the department ships
new utility builds through the filing season.

**1. The department's own macOS utility — the answer, with one condition.**

The **Common Offline Utility** covers **ITR-1, ITR-2, ITR-3 and ITR-4 for AY 2026-27** and is
published for macOS as well as Windows: version **1.2.2, released 17 July 2026**, an 85 MB
ZIP listed as *Utility for MAC* on the department's
[Downloads → Income Tax Returns](https://www.incometax.gov.in/iec/foportal/downloads/income-tax-returns)
page. It is a wholly different program from the Excel utility — a
[Wails](https://wails.io) desktop app (Go 1.22 with an Angular front end), not a workbook —
and it generates and can directly submit the upload JSON itself, so nothing here has to
reproduce anything the department signs.

**The condition: the macOS build is Apple Silicon only.** Inspecting the Mach-O headers in
`ITDe-Filing-2026-1.2.2.dmg`, the application binary and its updater are both **arm64**, with
`LC_BUILD_VERSION` giving a minimum of **macOS 11.0** (Big Sur). There is no universal binary
and no x86_64 build of the app, so an **Intel Mac cannot run it** — arm64 code does not run
under Rosetta, which translates the other direction. If your Mac is M1 or later this is the
route; if it is Intel, it is not available and route 4 is the fallback.

Two more things to expect. The app is **not notarised**, so macOS quarantines it and reports
it as damaged on first launch; the usual remedy is
`xattr -dr com.apple.quarantine /Applications/ITDe-Filing-2026.app`. And it takes a prepared
JSON: the department's own
[File Income Tax Return](https://www.incometaxindia.gov.in/tax-services/file-income-tax-return)
page lists, as the third option on *File Returns*, **"Import draft ITR filled in Online mode
or import JSON generated from Excel/HTML utility"**, and third-party preparers document
feeding their own generated JSON through exactly that step and finishing the return in the
utility ([Quicko's walkthrough](https://qna.tax/t/how-to-file-your-itr-on-income-tax-portal-using-quicko-json/9570)).
That is the same shape as the workflow here — prepare outside, import, let the department's
software validate and generate.

**What is not established, and matters:** whether that import accepts the partial
`{"ITR":{"ITR2":{"ScheduleFA":…}}}` document this tool emits by default, or needs the complete
return `--merge-into` produces; and whether Schedule FA Table A3 survives it with a large row
count intact. Neither has been tested here, and the Excel utility's own importer failing
silently is exactly the reason this project reads every cell back. **Check every Table A3 row
in the utility before generating the JSON.** Settling it needs one run on an Apple Silicon
Mac with a synthetic dataset — which is about twenty minutes' work and is written up as a
checklist: [`docs/MACOS_UTILITY_TEST.md`](docs/MACOS_UTILITY_TEST.md), with
`scripts/make_macos_import_test.py` generating both JSON shapes over a 178-row Table A3 sized
and marked up so a truncation is visible by eye.

**2. Excel for Mac running the ITD workbook — no, and not marginally.**

Excel for Mac has had VBA since 2016, but a reduced dialect: no ActiveX, no Windows API
`Declare`, and no Windows Script Host, so `CreateObject("Scripting.Dictionary")` raises
run-time error 429 ([Microsoft Learn](https://learn.microsoft.com/en-us/office/vba/api/overview/office-mac),
[Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/5667028/vba-on-mac-issue)).
Decompiling `ITR2_AY2627_v4.xlsm` — 236,600 lines of VBA — against that list:

| Construct | Count | Runs on Excel for Mac |
|---|---|---|
| `CreateObject("Scripting.Dictionary")` | 1,227 | no |
| `Declare` / `Declare PtrSafe` into `Kernel32` and `Advapi32` | 24 | no |
| `CreateObject("MSXML2.DOMDocument")` | 3 | no |
| `CreateObject("System.Security.Cryptography.HMACSHA256")` | 3 | no — .NET through COM |
| `CreateObject("System.Text.UTF8Encoding")` | 3 | no — .NET through COM |
| `CreateObject("Scripting.FileSystemObject")` | 2 | no |
| `Application.FileDialog` | 11 | no |
| `#If Mac` conditional compilation | **0** | — |

The workbook itself is clean of ActiveX controls (its 546 controls are form controls), so the
sheets would open. The code would not run. The `Advapi32` bindings are `CryptAcquireContext`,
`CryptCreateHash`, `CryptHashData` and friends, and they sit in the class that produces the
`CreationInfo.Digest` — so the specific step that makes an upload file acceptable is bound to
a Windows DLL that does not exist on macOS. Not a porting job; a rewrite of somebody else's
236,000 lines. And even if the VBA ran, automation on macOS is AppleScript or Office Scripts
rather than COM, so `scripts/import_to_utility.py` would need rewriting too.

**3. LibreOffice — no.**

LibreOffice Basic is not VBA. It uses a different object model reached through the UNO API;
`Option VBASupport 1` covers common patterns and explicitly not the whole language
([The Document Foundation, *Calc Macros*](https://wiki.documentfoundation.org/images/d/d9/CG7112-CalcMacros.pdf)).
Windows API `Declare` and Windows COM progids are unavailable regardless of platform, which
is the same wall as route 2 with less of Excel underneath it. Ruled out in minutes, as
expected.

**4. Windows 11 in a VM on Apple Silicon — the fallback that keeps the tested path.**

Nothing about this tool changes; only the host does. Office is native ARM64 on Windows on Arm
and uses [Arm64EC](https://learn.microsoft.com/en-us/windows/arm/arm64ec) so that x64 code
runs in the same process, and VBA and COM automation work — with the caveat that macros
calling 32-bit ActiveX or non-Arm DLLs may not, which does not apply here because the utility
targets Windows DLLs that Windows on Arm provides.

- **[Parallels Desktop](https://www.parallels.com/products/desktop/microsoft-authorized-solution-windows-11-arm/)** —
  the only virtualisation product Microsoft has authorised for Windows 11 on Apple silicon.
  Standard is **$99.99/year or $219.99 perpetual**; Pro is **$119.99/year**
  ([Macworld](https://www.macworld.com/article/668146/parallels-desktop-review.html)).
  Windows 11 Pro or Enterprise is licensed separately.
- **[VMware Fusion](https://www.vmware.com/docs/desktop-hypervisor-faqs)** — **free for all
  use** since March 2025, including commercial. Runs Windows 11 for Arm on Apple silicon.
  Less polished integration than Parallels.
- **[UTM](https://mac.getutm.app/)** — free and open source, QEMU over Apple's Hypervisor
  framework. Fine for ARM64 guests; no GPU acceleration for Windows, so it is the roughest of
  the three for daily use.

**Recommendation.** On an Apple Silicon Mac, try route 1 first — it is the department's own
software, it removes Excel from the loop entirely, and it can file end to end. Keep route 4
as the fallback, and reach for it immediately if the JSON import turns out not to carry
Schedule FA cleanly. Start with **VMware Fusion**, because it is free and this is one workbook
a year rather than a daily driver; buy Parallels only if Fusion's Windows-on-Arm support
disappoints. On an **Intel** Mac, route 1 does not exist and route 4 is the only option — and
an Intel Mac runs Windows x64 in a VM more conventionally.

### The line this project will not cross

The utility's VBA is on disk, so the `CreationInfo.Digest` algorithm could in principle be
recovered, which would let a tool emit an acceptable upload file with no Excel anywhere.
**This project does not do that and will not accept a patch that does.** The digest is an
integrity control the department put there deliberately; publishing code that reproduces it
would be distributing a means of defeating that control whatever the author's own use, it
would break the first time the department changed anything, and the risk is out of all
proportion to the convenience. The boundary is that the upload file always comes out of the
department's own software — the Excel utility on Windows, or the Common Offline Utility on
macOS.

---

## Setup

Needs Python 3.10 or newer (CI covers 3.10 to 3.13) and network access once, to cache
exchange rates and prices.

```bash
git clone https://github.com/hiteshK03/itr-prep.git
cd itr-prep
./setup.sh
```

`setup.sh` creates `.venv`, bootstraps pip if the system has none, installs the two runtime
dependencies (`requests` and `jsonschema`), and caches SBI exchange rates. Then:

```bash
.venv/bin/python -m itrprep.cli --help
```

Everything below assumes you are in the repository root. For brevity, define:

```bash
alias itr-prep="$PWD/.venv/bin/python -m itrprep.cli"
```

### The ITD schema (for validation)

Validation needs the department's ITR-2 JSON schema, which is **not** bundled here — it is
theirs to publish and it changes without notice. Download it from the e-filing portal
(**Downloads → Income Tax Returns → your assessment year → ITR-2 schema**) and drop it in
`schemas/`. See [`schemas/README.md`](schemas/README.md) for the search order and the
`ITRPREP_SCHEMA` environment variable. Without it, `build` still works but says loudly that
its output is unverified.

### On a network that intercepts TLS

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

---

## The workflow

Two stages, so you can start before every export is in hand.

```
broker exports ──(stage 1: normalize)──> transactions.csv ─┐
                                          issuers.csv ─────┼──(stage 2: build)──> JSON ──> Excel utility
                                          accounts.csv ────┘
```

### The short version

```bash
itr-prep init --work work                 # once; then fill in the three descriptive files
itr-prep run    --year 2025 --drop ~/dl   # rates, normalize, preflight, threshold, build
itr-prep import --year 2025 --json out/schedule_fa_2025.json \
              --utility /path/to/pristine/ITR2_AY_26-27_V1.2.xlsm
```

`run` chains the whole pipeline and stops at the first hard error, naming the stage. `import`
drives the Excel utility over COM and verifies every imported cell against the audit trail;
it is the only command that needs Windows, and [Where this runs](#where-this-runs) covers
what to do on a Mac. Each stage below still works on its own; `run` composes them, it does
not replace them.

### 0a. If a statement is password-protected

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

### 0. Create the working files

```bash
itr-prep init --work work
```

Writes `work/transactions.csv`, `work/issuers.csv`, `work/accounts.csv`,
`work/cash_balances.csv` and `work/prices_override.csv`, each with example rows marked
`example row - delete me`. Delete those before building.

### 1. Normalize each broker export

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
Stage 1 entirely and fill `transactions.csv` by hand — the data dictionary below defines
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

### 2. Fill in issuers and accounts

These cannot be derived from a transaction export. `issuers.csv` needs one row per ticker
with the **company's** name and address; `accounts.csv` needs one row per brokerage account.
See the data dictionary.

### 3. Build

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

### 3b. The ₹20 lakh threshold report

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

### 3c. Preflight — `doctor`

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
- an FX cache that does not cover the years asked for.

Warnings, which do not block but each cost you something real:

- accounts **missing from `cash_balances.csv`**, named — Table A2 is understated by whatever
  uninvested cash they held;
- **splits** affecting a holding, so the basis decision surfaces now rather than mid-build;
- prices far from that day's market close (a clean 10x usually means a split-basis problem);
- dividends with no withholding tax — that is your Schedule TR credit;
- duplicate transaction rows, which is usually a double import;
- an account with no transactions at all, which is usually a typo in `account_id`.

### 4. Import into the utility — scripted and verified

> **This is the one step that needs Windows.** It runs on Windows itself or from WSL, and
> nowhere else. On macOS or plain Linux it stops immediately and points at the alternatives —
> see [Where this runs](#where-this-runs), which also covers the department's macOS utility.

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
6. **reads every cell back and verifies it** — see [Verification](#verification);
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

## Supported brokers, and what to export from each

Three providers have adapters, covering the usual shape of Indian-resident US equity
holdings: an employer stock-plan account, an ESPP administrator, and a retail app. Menu
paths are from each provider's UI as of the 2025 exports the adapters were built against and
may have shifted; the important thing is the **content**, listed as "must contain". Files are
classified by their header row, not their filename, so a renamed export still works.

Whichever provider you use, export **every year since the account opened**, not just the
reporting year: Table A3 needs each lot's original acquisition date and cost, and a lot
acquired in 2019 still needs its 2019 cost basis to be reported in 2025.

### 1. E\*TRADE / Morgan Stanley StockPlan Connect

The usual home of employer RSUs and ESPP purchases, and typically the account contributing
the most rows.

- **Benefit History** — StockPlan Connect: *Stock Plan → Holdings → Benefit History*, or
  E\*TRADE: *At Work → Holdings → Benefit History* → **Download / Export**
  - must contain: symbol, transaction type (release / vest / ESPP purchase), vest or
    purchase date, quantity, **vest-date fair market value per share**
- **Gains & Losses / Realized Gains** — *At Work → My Account → Gains & Losses*, filtered
  to all years with sales
  - must contain: sale date, quantity sold, sale price, and ideally the acquisition lot it
    came from
- **ESPP purchase confirmations** if the Benefit History omits the purchase price. An ESPP
  discount is typically 15% and it matters for the acquisition cost.

The **"By Benefit Type" / expanded** download of the same screen is an XLSX with one
worksheet per plan — `ESPP` and `Restricted Stock` — and it is the better export to take,
because it states each vest tranche's own cost basis and both the withheld and the
sold-to-cover share counts. All its worksheets are read; check the census names each tab you
can see in Excel.

### 2. Fidelity NetBenefits

Commonly the ESPP administrator where the stock plan is separate from the brokerage account.

- **Stock plan transaction history** — NetBenefits: *Stock Plans → [plan name] →
  View Details / Transaction History*, set the date range to cover every year with activity,
  then **Download**
  - must contain: purchase date, shares purchased, **purchase price per share**, and the
    purchase-date FMV if shown
- **Annual statements** for each year — *Documents → Statements*. Use these to confirm the
  share count still held at each 31 December.
- **Dividend history**, if dividends were paid into the account rather than swept to a bank
  account. Needed for `TotGrossAmtPaidCredited` and for Schedule OS.

### 3. INDmoney (US stocks)

A retail route into US equities, usually the cleanest exporter of the three.

- **US Stocks transaction / order history** — INDmoney app or web: *US Stocks → Portfolio →
  Reports / Transaction History* → export CSV, date range covering **all years held**
  - must contain: date, ticker, buy/sell, quantity, price per share, total amount
  - XLSX exports are read directly, including dates stored as Excel serial numbers
- **Dividend report** — same reports section
  - must contain: date, ticker, gross dividend, **US tax withheld** (usually 25%)
- **US brokerage account statements** — needed for the Table A2 row: the **US broker's legal
  name, address and the account number**. INDmoney routes US investing through a US broker
  (historically DriveWealth LLC) where the investor is the account holder, so the Table A2
  row must name that broker, not INDmoney. Confirm from the statement rather than trusting
  the example in `accounts.csv`.

### Also needed, from your own records

- Account **opening dates** for every account (Table A2).
- Form 1042-S or the equivalent US withholding summary, for Form 67 / Schedule TR.

### An unsupported broker

`normalize` is one adapter per provider and adding one is not much work: a `Profile` in
`itrprep/adapters.py` names the column aliases and the transaction-type keywords. Or skip
`normalize` entirely and write `transactions.csv` yourself — it is four required columns,
documented below, and everything downstream works from that file alone.

---

## Data dictionary

### `transactions.csv`

One row per acquisition, disposal or dividend. All amounts in **USD**.

| Column | Required | Meaning |
|---|---|---|
| `account_id` | yes | Free-form key that must match an `account_id` in `accounts.csv` |
| `ticker` | yes | Trading symbol, e.g. `CSCO`. Must have a row in `issuers.csv` |
| `txn_type` | yes | `BUY`, `SELL` or `DIVIDEND` |
| `date` | yes | `YYYY-MM-DD` preferred. Slashed dates are read as **MM/DD/YYYY** (US brokers) |
| `quantity` | BUY/SELL | Shares, always **positive**. A sale is a `SELL`, never a negative `BUY` |
| `price_usd` | BUY/SELL | Per-share USD cost of acquisition. For a vest this is the **vest-date FMV**. **For ESPP, this is also the FMV at purchase, NOT the discounted price you paid** — see the ESPP note below, this is a common and consequential mistake |
| `amount_usd` | DIVIDEND | Gross USD. Optional for BUY/SELL — derived from quantity x price if blank |
| `tax_withheld_usd` | no | US tax withheld on a dividend. Feeds Form 67 / Schedule TR |
| `expense_usd` | no | Brokerage/commission on a BUY or SELL. Deductible from capital gains under s.72(1)(a) of the Income-tax Act, 2025 (s.48 of the 1961 Act) -- added to cost of acquisition on a BUY, subtracted from sale consideration on a SELL. Omitting this when your broker actually charged commission silently overstates your taxable gain |
| `paid_price_usd` | no | What you actually paid per share on a discounted ESPP purchase, where the export states it separately from FMV. **Never a cost of acquisition** — `price_usd` is, under s.73(1) of the Income-tax Act, 2025 (s.49(2AA) of the 1961 Act). This is audit trail: FMV minus this, times quantity, is the perquisite already taxed through Form 16, so it is what reconciles Schedule FA against Form 12BA item 17. No computation reads it |
| `acq_kind` | no | `RSU_VEST`, `ESPP`, `OPEN_MARKET`, `DRIP`, `OTHER`. Informational for Schedule FA, but `doctor` uses it to recognise an employer stock-plan account and check its row count is plausible |
| `disposal_kind` | no | `SELL` rows only. `TAX_WITHHOLDING` marks shares the employer kept at vest to pay withholding tax (a "sell to cover"). Such a disposal is matched to the lot created by the vest on that **same date**, never FIFO — E\*TRADE stamps one grant number on every vest of an award, so `lot_id` alone would let an older vest absorb it and put both lots' quantity and cost basis wrong |
| `lot_id` | no | Groups an acquisition. On a `SELL`, names which lot was sold. Blank means FIFO |
| `notes` | no | Free text, carried to the audit CSV |

Include **every acquisition ever made** that you still held during any year you report,
even from years before the one you are filing. Table A3 needs the original acquisition date
and cost regardless of age, and a `SELL` with no matching `BUY` is rejected.

> #### ⚠️ ESPP cost basis is the FMV at purchase, not the discounted price paid
>
> This is a real, discovered-the-hard-way mistake, not a hypothetical one: an ESPP export's
> `Purchase Price` column (e.g. E\*TRADE's, or Fidelity NetBenefits') is the **discounted**
> price you paid, often 10–15% below market. Under Indian tax law the discount itself is
> taxed separately as **perquisite/salary income** at the time of purchase (s.17(1)(d) of
> the Income-tax Act, 2025, s.17(2)(vi) of the 1961 Act) — so the cost of acquisition
> carried forward for capital gains is the **FMV at
> purchase date**, not the discounted price. Using the discounted price as `price_usd`
> silently understates the cost basis, which **overstates every subsequent capital gain (or
> understates a loss)** — the exact wrong direction for a filer.
>
> This holds regardless of the US broker's own "qualifying" vs "disqualifying disposition"
> distinction (a US-specific concept for whether the *discount* gets ordinary-income or
> capital-gains treatment on the *US* return) — India has no equivalent distinction; the
> FMV-at-purchase basis applies uniformly. A US 1099-B or G&L export sometimes surfaces this
> as two different cost-basis columns (e.g. E\*TRADE's `Purchase Price` vs `Purchase Date
> Fair Mkt. Value` / Adjusted Cost Basis) — always use the FMV column for `price_usd`, never
> the discounted purchase price, whichever export you're reading.
>
> Broker exports commonly carry both a `Purchase Price` and a `Purchase Date FMV` (or
> `Est. Cost Basis (per share)`, or `Grant Date FMV`) column. The `etrade` and `fidelity`
> profiles check every event-date FMV and cost-basis name **before** any paid-price name,
> so an export carrying both is priced at FMV without your intervention, and the discounted
> figure is kept alongside it in `paid_price_usd` as evidence of the perquisite. Read the
> census line: it names the column each concept bound to. If an export carries **only** a
> paid price, the row is still imported — but the run warns that the basis is the discount,
> names the column, and you should replace it with the Form 12BA / Form 16 FMV by hand.
>
> **Separately:** if a sold ESPP lot's US broker export names a specific `Date Acquired` for
> the shares that were sold (common with a disqualifying disposition, since the specific lot
> matters for the ordinary-income calculation), set matching `lot_id` values on that `BUY`
> and its `SELL` row. Without a `lot_id`, disposals are matched **FIFO against your own
> `transactions.csv` file order** — which silently picks the wrong lot (and therefore the
> wrong cost basis and gain/loss) whenever the broker's actual matched lot isn't your
> oldest one.

### `issuers.csv`

One row per ticker, describing the **issuing company** — Table A3 asks about the company,
not your broker.

| Column | Required | Meaning | Max |
|---|---|---|---|
| `ticker` | yes | Matches `transactions.csv` | |
| `entity_name` | yes | Legal name, e.g. `Cisco Systems, Inc.` | 125 |
| `entity_address` | yes | Registered/HQ address | 200 |
| `entity_zip` | yes | Postal code, e.g. `95134` | 8 |
| `entity_nature` | yes | e.g. `Listed Company`, `Exchange Traded Fund` | 34 |
| `country_code` | no | Defaults `2` (USA). Must be a code from the ITD list | |
| `country_name` | no | Defaults `UNITED STATES OF AMERICA` | 55 |

Over-length values are an error, not silently truncated, so the filed data always matches
your source.

### `accounts.csv`

One row per foreign brokerage account — this is what Table A2 reports.

| Column | Required | Meaning | Max |
|---|---|---|---|
| `account_id` | yes | Matches `transactions.csv` | |
| `institution_name` | yes | The **broker's** legal name | 125 |
| `institution_address` | yes | Broker's address | 200 |
| `institution_zip` | yes | Broker's postal code | 8 |
| `account_number` | yes | Your account number at that broker | 34 |
| `status` | no | `OWNER` (default), `BENEFICIAL_OWNER`, or `BENIFICIARY` — **that spelling** | |
| `account_open_date` | no | `YYYY-MM-DD`. Defaults to 1 Jan of the reporting year | |
| `country_code` / `country_name` | no | Default USA | |

### `prices_override.csv`

`ticker,date,close_usd`. Overrides or supplies a daily close. Use when a symbol has been
renamed or delisted, when a fetch fails, or when you want to pin a value to a broker
statement. Overrides always win over fetched prices.

---

## How the numbers are computed

### Reporting period

1 January to 31 December of `--year`. A holding gets a row if it was held **at any time**
during that window, which is the ITD's own test:

> Taxpayers must furnish details of foreign assets or accounts of the following nature,
> held at any time during the relevant calendar year ending on December 31st
> — ITD step-by-step guide, "Overview of Tables A1 to G"

So a ticker bought in March and fully sold in August still gets a row, with a nil closing
balance.

### One row per lot

Each acquisition (each RSU vest, each ESPP purchase, each market buy) becomes its own
Table A3 row. Table A3 asks for an *acquisition date* and an *initial value of investment*,
both properties of a single acquisition rather than of a ticker, so aggregating lots would
force you to invent one. This is why a few years of quarterly vests produces a large
Schedule FA — that is expected and correct.

Sales are matched to lots by `lot_id` when the export identifies one, otherwise **FIFO**
within the same account and ticker.

### Exchange rates — SBI TT buying rate, per date

The ITD is specific about which date's rate applies to which field:

> Exchange Rate Conversion: All peak balances, values of investment, and amounts of
> foreign-sourced income must be converted into Indian currency using the telegraphic
> transfer buying rate of the foreign currency as on the relevant date: the date of peak
> balance in the account, the date of investment, or the closing date of the calendar year
> ending on December 31st.
> — ITD step-by-step guide, "Currency Conversion and Valuation Guidelines"

Implemented as:

| Field | Rate date |
|---|---|
| `InitialValOfInvstmnt` | the acquisition date |
| `PeakBalanceDuringPeriod` | the date the peak occurred |
| `ClosingBalance` | 31 December |
| `TotGrossAmtPaidCredited` | each dividend's date |
| `TotGrossProceeds` | each sale's date |

Rates come from [`sahilgupta/sbi-fx-ratekeeper`](https://github.com/sahilgupta/sbi-fx-ratekeeper)
(`TT BUY` column), cached to `data/sbi_ttbuy_usd.csv` by `itr-prep fx-update` so filing-time
runs need no network. Two details:

- **Non-publication days carry forward.** SBI publishes nothing at weekends, on Indian bank
  holidays, and occasionally publishes a card with no TT rate at all (54 such rows in the
  file, treated as missing). The most recent published rate on or before the date is used.
  The audit CSV records every substitution, e.g. `initial FX carried from 2024-08-14` for a
  15 August vest, 15 August being Independence Day.
- **One rate per date.** SBI occasionally revises intraday; 12 of ~1,600 dates have two
  cards. The **first** card of the day is used, so a date always maps to one reproducible
  number.

**Schedule CG and Schedule OS use a different, specified-date convention.** Rule 115(2)
of the Income-tax Rules, 1962 specifies the exchange-rate date for capital gains
(sub-clause (f)) and dividend income (sub-clause (e)) as **the last day of the month
immediately preceding** the month of transfer / dividend, not the transaction's own date;
rule 206 of the Income-tax Rules, 2026 restates the same convention as a table (Table
Sl. Nos. 6 and 5) for tax year 2026-27 onwards --
applied to *both* the cost-of-acquisition leg and the sale-proceeds leg. This is
deliberately different from the per-date convention above, which is Schedule FA's own,
separately documented rule. Confirmed against a real broker's own tax report: their
displayed exchange rate for a lot bought 2024-08-02 was the 2024-07-31 rate, not the
2024-08-02 rate. `positions._rule115_specified_date` implements this; only
`compute_year_totals` (Schedule CG/OS) uses it -- `compute_rows` (Schedule FA) does not.

### Peak value — the interpretive part

For each lot, for each day it was held during the year, the tool computes
`shares held that day x that day's closing price`, then takes the maximum. Share counts
change as lots vest and are sold, so this is driven by a genuine per-lot daily position
timeline rather than a year-end snapshot.

Three choices are worth stating plainly, because practitioners differ:

1. **Closing prices, not intraday highs.** A holding's value on a day is what it was worth
   at that day's close. Using intraday highs would report a value the taxpayer never held
   at any measurable point. Non-trading days carry the last close forward.

2. **The peak is found in USD, then converted at that date's rate** (`--peak-basis usd`,
   the default). This follows the ITD's wording literally: it says to use the rate "as on
   the date of peak balance", which presupposes the peak has already been identified —
   necessarily in the foreign currency.

   The alternative reading is to maximise the rupee value directly, since that is the
   number actually disclosed. `--peak-basis inr` does this. It is **always greater than or
   equal to** the default, so it is the more conservative disclosure. If your CA prefers it,
   use it; the difference is usually small, arising only when the peak USD date and the peak
   INR date differ.

   Where the USD value ties across several days — which happens over every weekend, since
   the position is carried at its last traded price — the tie is broken toward the higher
   rupee value. Without that, a lot acquired just before a year-end weekend could report a
   peak below its own 31 December closing value.

3. **Table A2's account peak is the sum of its holdings' peaks.** Those holdings do not all
   peak on the same day, so this slightly overstates the true account peak. It errs toward
   over-disclosure, and Table A2 asks for a peak balance rather than a same-day snapshot.

All amounts are rounded to whole rupees, because the schema types every Schedule FA money
field as `integer`.

### Stock splits: the build stops rather than guess

A split changes your share count with no transaction to record. Worse, **Yahoo's historical
closes are retroactively split-adjusted and your broker statement is not**, so for a holding
that spans a split the two are on different footings and the value comes out wrong by the
split ratio — for AVGO's 10-for-1 split of 15 July 2024, by a factor of ten.

The tool reads split events from the same Yahoo chart endpoint it already uses for prices
(`events=div,split`), so detection needs no new dependency. If any transaction pre-dates a
split, **the build stops**:

```
STOCK SPLIT DETECTED -- refusing to compute values that could be wrong by the split factor.

Splits affecting your holdings:
  AVGO: 10-for-1 split effective 2024-07-15
...
  2023-11-15 AVGO BUY qty=10 @ 975.40 [work/transactions.csv line 2] factor 10
      evidence: recorded 975.40 vs unadjusted close 975.400010
                (adjusted 97.540001 x 10):
                looks like the price of the day -> looks historical
```

It stops rather than adjusting automatically because **the data cannot tell it which basis
you are on**. A CSV re-downloaded from the broker today usually shows historical lots
already restated to post-split share counts; a statement saved in 2023 does not. Both are
legitimate, and they differ by exactly the factor at issue. So the tool guesses for you and
shows its working — comparing your recorded price against the adjusted and unadjusted
closes for that date — then makes you confirm:

| Flag | Meaning |
|---|---|
| `--split-basis current` | Quantities are **already restated** post-split. Nothing is changed: on a pre-split day, post-split shares × adjusted close is already right. |
| `--split-basis historical` | Quantities are **as printed at the time**. Each affected row is restated (quantity × factor, price ÷ factor) before anything is valued. |

To check which you are on, compare the share count on a broker statement dated *after* the
split with the one in your CSV. If they match, you are on `current`.

The choice is echoed on every successful run and every restated row is marked in the audit
CSV, so an adjustment is never silent either. CSCO, JNJ and IVV had no splits in 2022-2025;
AVGO is the live one.

### Dividends across lots

Dividends are paid per share, not per lot, so with one row per lot they are apportioned by
shares held on the payment date. The apportioned amounts always sum back to the dividend
actually received — `tests/test_pipeline.py` asserts this. A lot that was partly sold
before a later dividend correctly receives a smaller share of it.

---

## Table A2: do you need the custodial-account rows?

**Recommendation: yes, include them — and the tool does so by default.** Use `--no-a2` to
omit them.

The reasoning, separating what is established from what is judgement:

**Established.** Table A2 is "Details of Foreign Custodial Accounts", and the ITD describes
it as covering *"accounts maintained with foreign custodians, including peak balance,
closing balance, and gross amounts paid or credited (specified by type: interest, dividend,
proceeds from sale, or other income)"*. A US brokerage account holding your shares is a
custodial account on its plain meaning, and the fields it asks for — an account number, an
account-opening date, a nature-of-amount code — only make sense for an account, not for a
shareholding. Table A3 has no account number field at all. So the two tables are asking
about different things, and the schema expects both to be populable.

**Judgement.** Neither the schema nor the validation rules say "if you report equities in
A3 you must also report the account in A2", so an argument exists that A3 alone covers the
economic interest and A2 would double-count. The common practitioner view is the opposite:
report the account in A2 *and* the underlying holdings in A3, because they answer different
questions and the ITD has never treated the sum of Schedule FA tables as a portfolio total.

**Why default to including them.** The penalty asymmetry is stark. Under the Black Money
Act, failure to disclose a foreign asset can attract a penalty of ₹10 lakh per year plus
prosecution exposure, whereas disclosing an account that arguably did not need a row costs
nothing — Schedule FA is informational and its totals do not enter the tax computation.
There is no penalty for over-disclosure and a severe one for under-disclosure.

One caveat worth raising with a professional: the A2 peak is a sum of holding peaks (see
above), so it is deliberately conservative.

### Cash balances — `cash_balances.csv`

Uninvested cash sitting in a brokerage account is part of that account, so leaving it out
understates Table A2. It **cannot be derived** from a trade export: wire transfers in and
out never appear there, so the transaction rows alone can never reconstruct a balance. Give
it directly, read off the broker's own statements:

| Column | Required | Meaning |
|---|---|---|
| `account_id` | yes | Matches `accounts.csv` |
| `year` | yes | Calendar year, e.g. `2024`. One row per account per year |
| `peak_usd` | yes | Highest cash balance during that year |
| `peak_date` | no | Date of that peak. Blank converts the peak at the 31 December rate, noted in the audit CSV |
| `closing_usd` | yes | Cash balance at 31 December |
| `notes` | no | Carried into the audit trail |

The amounts are added to that account's Table A2 peak and closing balances, and are counted
in the threshold report. An account with cash but no securities still gets its A2 row. A
negative balance is rejected — a margin debit is a liability, not a negative asset — as is a
closing balance above the peak, since 31 December is one of the days the peak is taken over.

The file is optional. Leave it out and every run tells you which accounts were counted on
securities alone.

---

## Prior years: AY 2024-25 and AY 2025-26

`--year 2023` and `--year 2024` can feed an **updated return under s.139(8A)** for AY 2024-25
or AY 2025-26. This section documents the mechanics **if** one is being filed; it is not a
recommendation to file one, and three things should be settled before you reach for it:

- **Run the threshold report first.** Where a year's aggregate of non-immovable foreign assets
  is under ₹20,00,000 on every basis, the proviso to section 43 of the Black Money Act
  provides that "this section **shall not apply**" — a disapplication, not a discretion — so
  for that year there is no section 43 default and nothing for an updated return to cure.
- **An updated return does not displace a section 43 default in any event.** Section 43's
  charging limb names sub-sections (1), (4) and (5) of section 139; s.139(8A) is not among
  them. See [`docs/KNOWN-ISSUES.md`](docs/KNOWN-ISSUES.md) issue 3. A **revised** return under
  s.139(5) is in that limb; an updated return substitutes for nothing.
- **An updated return needs positive additional tax.** A disclosure-only correction with no
  additional liability is not a filing this route supports.

So the reason to file one is the **income** left out of the original return, not the missing
schedule — and that reason has to be worth the additional tax under s.140B, whose rate rises
with each 12-month band. Take advice. This tool builds Schedule FA; it does not decide
whether a year should be filed.

All three years in the table below are decided under the Income-tax Act, 1961, so the
citations in this section are to that Act deliberately. Calendar year → assessment year:

| `--year` | Financial year | Assessment year | Utility |
|---|---|---|---|
| 2023 | FY 2023-24 | AY 2024-25 | `ITR2_AY_24-25_V1.8.xlsm` |
| 2024 | FY 2024-25 | AY 2025-26 | `ITR2_AY_25-26_V1.2.xlsm` |
| 2025 | FY 2025-26 | AY 2026-27 | `ITR2_AY_26-27_V1.2.xlsm` |

Use the utility **for that assessment year**, with **s.139(8A)** selected in
`Part A Gen_139(8A)`, and complete `Part B ATI`.

**The Schedule FA import path is identical across all three years — verified, not assumed.**
The VBA was decompiled from each utility and compared:

- `Function ImportScheduleFA(ByVal jsonObject As Object)` is **1,409 lines in all three and
  character-identical**, apart from the casing of one loop variable (`node` vs `Node`),
  which VBA treats as the same identifier.
- All three read the **same 63 JSON keys**, including every Table A2 and A3 field.
- All three write to VBA code-name `Sheet27`, which resolves to the sheet named **`TR_FA`**
  in all three workbooks.
- All three expose `Part A Gen_139(8A)` and `Part B ATI`.
- The `ScheduleFA` **JSON schema definitions are byte-identical** between the AY 2025-26 and
  AY 2026-27 schemas: same 12 required fields for `DtlsForeignEquityDebtInterest`, same 12
  for `DtlsForeignCustodialAcc`, same types and constraints, no `maxItems` on either.

**And all three have now been round-tripped live**, with `itr-prep import`, each into a fresh
copy of its own utility, each passing full cell-by-cell verification against its audit CSV —
see [Verification](#the-excel-round-trip-live-on-all-three-utilities). The equivalence above
is no longer load-bearing; it is corroborated by measurement. Import a prior year with:

```bash
itr-prep import --year 2024 --json out/schedule_fa_2024.json \
              --utility /path/to/ITR2_AY_25-26_V1.2.xlsm
```

Two caveats remain worth stating:

- The **AY 2024-25 JSON schema** is no longer published at a retrievable URL, so `--year 2023`
  output is validated against the AY 2025-26 / AY 2026-27 schema. Given the A2/A3 definitions
  are unchanged between those two and the AY 2024-25 utility's importer reads the identical
  keys, this is a low risk — but it is inference from the importer rather than a check
  against that year's own schema. Validate inside the AY 2024-25 utility before filing.
- Utility **versions** matter: use the latest published for each AY (V1.8 for AY 2024-25,
  V1.2 for AY 2025-26). Earlier versions of the same year's utility were not compared.

---

## Schedule CG, OS, FSI, TR and the foreign tax credit statement

Schedule FA does not cover capital gains or dividend income. `..._other_schedules.txt`
gives you those figures, on the **financial year** (1 Apr – 31 Mar), not the calendar year:

- **Schedule CG** — aggregate full value of consideration and cost of acquisition, split
  into short term (held ≤ 24 months) and long term (> 24 months). Hundreds of trades
  collapse into these two blocks. Foreign shares are unlisted for Indian purposes, hence
  the 24-month threshold.
- **Schedule OS / FSI / TR and the foreign tax credit statement** — gross foreign dividend
  and US tax withheld, in both USD and INR. The paragraph that names the form and its
  deadline is rendered from the registry for the year being built, so it says Form 67 for
  AY 2026-27 and Form 44 for AY 2027-28 rather than asserting either.

These are **reported, not emitted into the JSON**, deliberately. Schedule CG's structure
depends on choices this tool has no business making — which section, indexation, set-off
against other losses — and a wrong auto-filled capital gains schedule is far more dangerous
than one you enter yourself. Enter them by hand or hand the file to your CA.

**For AY 2026-27 and earlier — a 1961-Act year, so 1961-Act citations throughout the rest
of this section.**

**Form 67 is due by the end of the assessment year, not by the return's due date.** Rule
128(9) of the Income-tax Rules, 1962 was substituted by **CBDT Notification No. 100/2022
dated 18 August 2022** (Income-tax (27th Amendment) Rules, 2022, G.S.R. 636(E)), with
retrospective effect from 1 April 2022. Form 67 is to be furnished **on or before the end of
the assessment year** in which the income is offered to tax — **31 March 2027 for
AY 2026-27** — provided the return itself is filed within the time allowed by s.139(1) or
s.139(4). The pre-2022 requirement to get it in by the s.139(1) due date no longer applies.

**The proviso runs the other way, and it is the one that bites on a prior year.** Where the
return is furnished under **s.139(8A)**, Form 67 for the income included in that updated
return must be furnished **on or before the date that return is furnished**. It cannot be
filed afterwards. So for each year in
[Prior years](#prior-years-ay-2024-25-and-ay-2025-26), the order is Form 67, then the ITR-U.

Being late is not necessarily fatal either. A consistent line of ITAT authority holds the
Rule 128(9) timeline **directory rather than mandatory** — the rule attaches no consequence
to non-adherence, and a procedural lapse cannot extinguish a substantive right to credit:
*Ms. Brinda Rama Krishna v. ITO* (ITAT Bangalore, ITA No. 454/Bang/2021, 17 November 2021;
[2021] 135 taxmann.com 358), followed in *42 Hertz Software India Pvt. Ltd. v. ACIT* ([2022]
139 taxmann.com 448) and *Sonakshi Sinha v. CIT(A)* ([2022] 142 taxmann.com 414 (Mum)). That
is a fallback for a credit already claimed, not a filing plan.

**AY 2026-27 is the last year on Form 67.** From tax year 2026-27 — income earned from
1 April 2026, governed by the Income-tax Act, 2025 — the claim moves to **Form No. 44 under
rule 76 of the Income-tax Rules, 2026** (CBDT Notification No. 22/2026, G.S.R. 198(E),
20 March 2026). Both limbs of the deadline survive: rule 76(12) gives twelve months from
the end of the tax year where the return is within the section 263(1) or 263(4) window, and
rule 76(13) repeats the updated-return proviso for a return under section 263(6)(a). What
changed in substance is that rule 76(16) requires an accountant to verify Form 44 where the
assessee is a company or foreign tax paid for the tax year is ₹1,00,000 or more, the form
asks for the foreign tax identification number, and a new Form No. 45 intimates the
**settlement of a dispute** over foreign tax whose credit was not claimed (rule 76(6) and
(15)). A later *refund* of foreign tax already credited is not Form 45 — rule 76(14) puts
that back on Form No. 44, in its Part C. The ITAT authority above is on rule 128(9) and
does not automatically carry to rule 76; treat the deadline as real.

---

## Where every statutory figure comes from

Every rate, limit, threshold, deadline and conversion convention this tool relies on lives
in `rules/AY<year>.json`, each with an official citation. Code reads them from there.
Nothing is computed from memory and nothing is hardcoded at a call site — because the
figures that matter here have already moved: the Black Money Act relief threshold replaced
an earlier ₹5 lakh bank-balance carve-out in 2024, the foreign tax credit deadline was
rewritten in 2022, and then the whole Act was replaced.

| Registry | Tax year | Statute | Entries |
|---|---|---|---|
| [`rules/AY2026-27.json`](rules/AY2026-27.json) | FY 2025-26 | Income-tax Act, **1961** | 12, of which 6 `annual` |
| [`rules/AY2027-28.json`](rules/AY2027-28.json) | FY 2026-27 | Income-tax Act, **2025** | 28, of which 13 `annual` |

```bash
itr-prep rules                # every entry, its value, its authority and its source
itr-prep rules --annual-only  # just the ones that need re-verifying each year
```

Each entry declares a **review class**. `stable` means fixed by statute — a settled
convention or a historical date. `annual` means a Finance Act or a notification can move
it, and it must be re-verified before the registry is used for a later assessment year.

### AY 2027-28 is a change of statute, not a refresh

The **Income-tax Act, 2025** came into force on 1 April 2026 and repealed the Income-tax
Act, 1961 by its section 536(1). Almost every provision was renumbered — but **section
536(2)(c) keeps the old Act applying to any tax year beginning before that date**, so
AY 2026-27, the year this tool was actually used to file, is permanently a 1961-Act year.

Both things have to stay true in this repository at once, which is why the section numbers
here are not consistent and should not be made so. Content about the AY 2026-27 filing keeps
its 1961-Act citations — [`docs/RUNBOOK_AY2026-27.md`](docs/RUNBOOK_AY2026-27.md) and the
dated `CHANGELOG.md` entries are 1961-Act throughout — and forward-looking content cites the
Act of 2025, usually with the old number alongside. Every entry in `rules/AY2027-28.json`
carries an `act_transition` block naming the provision it descends from and classifying the
change as a renumbering, a substantive change, separate legislation or a new entry;
[`docs/ANNUAL-REVIEW.md`](docs/ANNUAL-REVIEW.md) has the readable mapping table.

Three things worth knowing without reading that table:

- **The Black Money Act, 2015 is separate legislation and is not renumbered.** Section 43,
  the ₹10,00,000 penalty and the ₹20,00,000 relief threshold are untouched. There is a live
  cross-reference problem, though: section 43's charging limb names sub-sections (1), (4) and
  (5) of section 139 of the *1961* Act, and a tax year 2026-27 return is furnished under
  section 263 of the Act of 2025. Whether those read onto section 263 is unresolved. What is
  settled is the other half — section 139(8A) was never in that limb, so an updated return
  never displaced a section 43 default and renumbering does not change that. See
  [`docs/KNOWN-ISSUES.md`](docs/KNOWN-ISSUES.md).
- **Two entries changed in substance, not just number.** The foreign tax credit statement
  became Form No. 44 under rule 76 of the Income-tax Rules, 2026, with an accountant's
  verification above ₹1,00,000 of foreign tax; and the revised-return deadline became twelve
  months from the end of the tax year under section 263(5).
- **The registry gained Indian mutual fund entries**, cited from the Gazette text:
  grandfathering (s.90(7)–(8)), Specified Mutual Funds (s.76), both capital gains rates
  (ss.196–198), holding periods (s.2(101)) and FIFO (s.67(7)(c)). No code reads them yet.
  Two carry `implementation_trap` blocks that the test suite refuses to let anyone delete —
  AMFI's 31 January 2018 file has both a *Net Asset Value* and a *Repurchase Price* column
  and they differ on 4,756 of its 9,502 rows, and section 76 makes a Specified Mutual Fund
  unit acquired on or after 1 April 2023 short-term *irrespective of the holding period*.

That is enforced, not merely documented, because a note in a file gets skipped:

- **`itr-prep build` refuses to run** for an assessment year the registry does not cover. It
  does not quietly fall back to the newest one. Computing AY 2027-28 against AY 2026-27
  figures is exactly the silent failure this prevents.
- Building an **earlier** year runs — prior-year updated returns (s.139(8A) of the 1961 Act,
  s.263(6)(a) of the Act of 2025) are a documented workflow — but prints a banner saying
  which assessment year the figures it used are stated for, and which Act that year is
  decided under.
- **`tests/test_rules_registry.py` fails** if any entry lacks an official source URL, if
  any entry cites a secondary aggregator as its authority, if an `annual` entry has been
  left behind by the registry it lives in, or if an `annual` entry is missing from
  [`docs/ANNUAL-REVIEW.md`](docs/ANNUAL-REVIEW.md). It also asserts the arithmetic reads
  the registry rather than a reintroduced literal.

The suite fails while the runtime only warns, deliberately. A contributor or a CI run
should be stopped dead by a registry that has rotted. Someone mid-filing should not be:
Schedule FA is arithmetic on their own broker data and does not depend on a rate, so they
get a banner they cannot miss instead of a blocked deadline. The one place a stale figure
would change an answer — the ₹20 lakh threshold report — prints which registry and
verification date it used at the top of every report.

**Primary sources only.** The Act or Finance Act text, a CBDT notification or circular, or
the department's own site. ClearTax, TaxGuru, Taxmann and practitioner blogs are fine for
*finding* a provision and may be quoted in prose, but are never the cited authority for a
rate, a limit or a date; the test enforces the domain rule. `revised_return_deadline` was
flagged `contested` while our own research disagreed about it, rather than picking a date
and looking confident; it has since been settled against the enacted Finance Act 2026 text
and the flag removed. **One entry is `contested` now** —
`specified_mf_debt_threshold_pct`, where secondary commentary describes a 90-day carve-out
that is not in the Gazette text and the department's consolidated as-amended PDF returns 403
to every automated client, so the question could not be closed either way.

Scope is deliberately narrow: the registry holds what Schedule FA and its dependent
schedules need, plus Indian mutual fund capital gains. Slab rates, surcharge tiers and
Chapter VI-A deductions are not here. The 31 January 2018 grandfathering date used to be out
of scope too, correctly — foreign shares are never section 112A assets — but its Act-of-2025
successor at section 90(7)–(8) governs mutual fund units, so it is now in.

---

## Verification

Eight suites, 1,164 checks, all runnable offline once the caches are warm, and all of them
on macOS and Linux alike — CI runs the whole set on both:

```bash
.venv/bin/python tests/test_validation_teeth.py        # 24 cases
.venv/bin/python tests/test_pipeline.py                # 80 checks
.venv/bin/python tests/test_splits_cash_threshold.py   # 67 checks
.venv/bin/python tests/test_doctor_readback.py         # 96 checks
.venv/bin/python tests/test_multisection_adapter.py    # 111 checks
.venv/bin/python tests/test_multisheet_workbook.py     # 117 checks
.venv/bin/python tests/test_rules_registry.py          # 579 checks
.venv/bin/python tests/test_unlock_credentials.py      # 90 checks
```

The registry suite was 167 checks and is now 579. Two things account for most of the jump:
there is a second registry, and the suite now runs the citation, review-class and staleness
blocks against **every** registry on disk rather than only the newest. Before, adding
`rules/AY2027-28.json` would silently have retired `rules/AY2026-27.json` from the suite.
The rest is new. The **act-transition** block asserts that each registry cites the Act its
year is decided under, that every entry in the later registry records where it came from,
that nothing was dropped across the change and that the Black Money Act entries are marked
as separate legislation rather than renumbered. The **encoded-trap** block fails if either
mutual fund trap is deleted or hollowed out. And the other-schedules summary is now asserted
to name the form, rule and deadline the registry gives — Form 67 and rule 128(9) for
AY 2026-27, and no repealed provision at all for AY 2027-28.

**That is the count with everything present**, and two of the eight suites need something a
bare clone does not have. Without the ITD schema in `schemas/`, `test_validation_teeth.py`
skips in full and `test_pipeline.py` drops three schema-dependent checks; without the optional
unlock extras, `test_unlock_credentials.py` skips its 38 encrypted round-trip checks. All three
say so when they skip, none of them fails, and a bare clone therefore sees 8 suites and 1,099
checks pass. CI installs the unlock extras deliberately — a proof that skips is not one — and
does not fetch the schema, since the department's artefact is not ours to download in a
workflow.

"Offline" means "reads a cache", and a fresh clone has none — `data/` is gitignored. Run
`itr-prep fx-update` and one `itr-prep threshold` over each synthetic dataset first, which is
what CI does.

**`test_validation_teeth.py`** proves the schema validation actually rejects things. It
mutates a known-good row one field at a time and asserts the official ITD schema refuses
it: `BENIFICIARY` spelled correctly, an integer country code, a float rupee amount, a
`DD/MM/YYYY` date, a missing required field, an extra field, an over-length string, an
out-of-enum nature code. All 24 cases behave correctly.

A subtle one it also covers: **the ITD schema is draft-04, not draft-07.** It declares
`http://json-schema.org/draft-04/schema#` and uses draft-04's boolean form of
`exclusiveMinimum` in 659 places. A draft-07 validator reads `"exclusiveMinimum": false` as
"must exceed 0" and wrongly rejects every legitimately-zero amount — which is exactly what
happened for 2023 and 2024 before this was found. The validator is chosen from the
schema's own declaration.

**`test_pipeline.py`** runs the synthetic dataset (`tests/synthetic/`) through the whole
pipeline for 2023, 2024 and 2025. It covers multiple lots per ticker, a mid-year sale of an
identified lot, a mid-year sale that must go FIFO, a ticker bought and fully exited inside
the year, four quarterly dividends across four lots, holdings spanning the entire year, and
lots acquired in earlier years. Rather than golden numbers — which would rot, since prices
come from a live source — it asserts conservation properties: apportioned dividends sum to
dividends received, attributed proceeds sum to sales made, peak ≥ closing, fully-exited lots
have a nil closing balance, peak share count never exceeds the lot size. It asserts the
provenance trail survives the whole pipeline: every lot names the row it was built from,
every computed row names the sale and dividend lines behind its apportioned figures, and
the audit CSV's own columns agree with them. It also exercises the adapters against
realistic broker fixtures and checks that bad input is rejected loudly.

**`test_splits_cash_threshold.py`** covers the three later additions against a second
dataset (`tests/synthetic_split/`) built around a real corporate action: 10 AVGO shares
bought in November 2023, held through the 10-for-1 split of 15 July 2024. It asserts the
split is found with the right date and ratio, that the build refuses to run without
`--split-basis`, that the refusal names ticker/date/ratio, that restatement preserves cost
while scaling quantity, and — the point of the exercise — that **choosing the wrong basis is
a factor-of-ten error** (₹21,22,463 against ₹2,12,246 for the same holding). It also checks
that a lot acquired *after* a split is left alone. For cash it asserts Table A2 rises by
exactly the cash figures, Table A3 does not move, an account holding only cash still gets a
row, and that bad input is rejected. For the threshold report it asserts totals reconcile to
their account and lot breakdowns, peak ≥ closing, conservative ≥ literal, that a year with
no data reports `NO DATA` rather than zero, and that the straddle warning fires — the
dataset is sized so 2024 lands **OVER** on the peak basis and **UNDER** at 31 December.

**`test_doctor_readback.py`** covers the preflight command, the header sniffer and the import
verifier. For `doctor` it asserts that untouched templates are a hard error, that a missing
issuer ticker and an unresolvable `account_id` are both named, that an oversell is an error
while missing cash balances are only a warning, and that a split surfaces before the build.
For detection it gives an E\*TRADE export a Fidelity filename and a Fidelity export an
E\*TRADE filename, and asserts both are still classified correctly — then that an
unclassifiable file is refused rather than guessed. It also builds a real XLSX with the
stdlib and asserts dates arrive as `2025-01-08`, not as the serial `45665`.

For the verifier it synthesises the failure shapes seen in practice and asserts each is
caught: a dropped last row, a last row present but blank, a wrong rupee figure in the
*second* row, a country cell left as a bare `2`, a date arriving as a serial number, a
date transposed to MM/DD/YYYY, a stripped leading zero in a zip code, and a missing item 19.
It also asserts the verifier catches a JSON that disagrees with the audit CSV it was built
from *even when the spreadsheet faithfully matches that JSON* — so the whole chain is
checked, not just its last link.

It closes with the platform boundary. Every host is described by injecting the platform name
and a `which`, so the behaviour on Windows, on WSL, on a Mac and on a plain Linux box is all
asserted from whichever one you happen to be on — a check that only runs on the machine it
describes proves nothing about the others. It asserts the refusal names the host, points at
both the department's macOS utility and a Windows VM, and does not claim the macOS route has
been tested here; that `itr-prep import` exits 2 rather than raising; that the driver refuses
before it complains about a missing file; and — the structural one — that every module in
`itrprep/` imports on the host running the suite and that none but `host.py` so much as
mentions `win32com`, `powershell.exe` or `Excel.Application`.

**`test_multisection_adapter.py`** covers the per-section reader. A stock-plan export carries
one header per plan type or grant, so it asserts each block resolves its own column layout,
that a wider later section keeps its own positions instead of being truncated against the
first one's, and that a section may reorder its columns freely. It covers the gross/withheld/
net distinction a sell-to-cover turns on — one row becoming an acquisition of the gross count
plus a same-day disposal of the withheld portion, bound to the lot that vest created rather
than to an older vest of the same award — and the row types that used to classify as nothing
at all. Above all it asserts that a row which cannot be read is **counted, named and
blocking**: the run exits non-zero behind a banner, and `--allow-dropped-rows` is the only way
past it.

**`test_multisheet_workbook.py`** covers the workbook reader and what an acquisition is worth.
It builds a two-sheet "By Benefit Type" fixture with the real export's shape — trailing-colon
column names, repeated headers, nested `Grant` / `Vest Schedule` / `Tax Withholding` /
`Sellable Shares` records tied by grant number — and asserts every worksheet is read and named
in the census, hidden tabs included, while an instructions tab is reported as skipped without
stopping the run. A sheet whose rows parse as transactions but whose header does not is
blocking, not skipped. For pricing it asserts FMV beats the discounted purchase price, that a
paid-price-only section says so loudly, that a disposal is valued at what it executed at, and
that `Est. Market Value` and `Est. Taxable Gain/Loss` are refused as any concept at all. A
final block re-parses every fixture that already worked and asserts nothing about their output
moved.

**`test_rules_registry.py`** is the enforcement half of the rules registry — see
[Where every statutory figure comes from](#where-every-statutory-figure-comes-from). It
asserts every entry cites an official source and cites no aggregator, that review classes
and the assessment years they are stated for agree, that a build past the newest registry is
refused while an earlier one runs with a banner, that `docs/ANNUAL-REVIEW.md` still lists
every `annual` entry with its source link, and — the check that catches real drift — that
the arithmetic reads the registry, by driving a sale one day either side of the long-term
threshold rather than reading the constant back. `ITRPREP_CHECK_SOURCE_URLS=1` additionally
HEADs every cited URL, failing only on 404 or 410, since the department's site answers 403
to any non-browser client and that says nothing about whether the page exists.

**`test_unlock_credentials.py`** is adversarial rather than functional: it tries to make a
document password escape the process. It builds a genuinely encrypted PDF, fails to open it
with the wrong credential, then searches the error text, the formatted traceback, and the
CLI's combined stdout and stderr for both the correct password and the wrong one. It asserts
`Credential` withholds its value from `repr`, `str`, f-strings, `%s` formatting and enclosing
containers; that `--list-credentials` prints no value and not even the PAN or date of birth;
that a file named after its own password still does not open when nothing is declared; and
that decrypted output lands 0600 in an owner-only directory git ignores. The PDF and workbook
round-trips skip without the optional unlock extras, so the suite still runs on a base
install.

### The Excel round-trip, live, on all three utilities

Not inferred — **run**, with `itr-prep import`, and verified cell by cell:

| Utility | Reporting year | A3 rows | A2 rows | Result |
|---|---|---|---|---|
| `ITR2_AY_26-27_V1.2.xlsm` | 2025 | 11 | 3 | **PASS** |
| `ITR2_AY_25-26_V1.2.xlsm` | 2024 | 5 | 2 | **PASS** |
| `ITR2_AY_24-25_V1.8.xlsm` | 2023 | 2 | 1 | **PASS** |

Every text field, date and rupee figure in every row matched the generated JSON, and the
JSON's totals matched the audit CSV. This closes the last verification gap: the prior-year
import path was previously only inferred from the fact that the VBA is character-identical
across the three utilities. It is now measured. See also
[`docs/ROUNDTRIP_RESULT.md`](docs/ROUNDTRIP_RESULT.md).

The live runs also found a defect no amount of static reading would have: the utility's zip
cell is number-formatted, so `02210` is stored as `2210`. Roughly a tenth of US zip codes
begin with a zero. `itr-prep import` now repairs it and the verifier fails the import if the
repair does not take.

What is **not** verified: the file-picker dialog itself (bypassed by calling the same
functions `ImportJson` calls), the `--format prefill` output, and anything on the portal
side after Generate JSON.

---

## Supply chain

`pip install itr-schedule-fa` was **not** used, and no code was taken from it.

That package appeared on PyPI on 2026-07-28 — all three versions within seven hours, the
same day this tool was written — and targets this exact niche. Reading its metadata and
wheel source before deciding:

- It depends on `fa-inrdata-api` and `sbi-tt-rates`, two more packages of the same vintage,
  so adopting it means trusting at least three brand-new packages inside a tax filing.
- Its peak value comes from a **remote HTTP API** (`fainrapi.max_value`). A number you
  cannot reproduce offline is a poor basis for a disclosure you may have to defend years
  later. This tool caches SBI rates and prices locally and shows every input in the audit
  CSV.
- It computes peak as `max_inr_price x quantity`, taking the maximum of a price series and
  multiplying by a single quantity. That is only correct while the share count is constant,
  so it would misstate any lot with a mid-year sale.
- It emits a "portal-ready CSV". The mechanism verified here is JSON through the Excel
  utility; the utility ships CSV helpers for Schedule 112A and TDS but **none for
  Schedule FA**.
- It also depends on `yfinance`, which failed outright in the environment this was written
  in: its bundled `curl_cffi` CA bundle would not verify, so every request died with
  `CertificateVerifyError`. One more moving part in the chain between a broker export and a
  filed return.

Nothing was worth vendoring. The one idea worth noting is that maximising an INR-converted
series corresponds to `--peak-basis inr`, which is already supported as an option.

Runtime dependencies are only `requests` and `jsonschema`, both pinned. `oletools` and
`pdfminer.six` are dev-only, used to decompile the utility's VBA and read the ITD PDFs while
establishing the JSON contract.

`itr-prep unlock` needs `pypdf` and `msoffcrypto-tool`, which are kept in a separate
`requirements-unlock.txt` rather than added to the base install: they are only useful if you
have password-protected statements, and the pipeline itself never touches them. Without them
`unlock` says exactly what to install and every other command is unaffected.

---

## Command reference

```
itr-prep init       --work DIR [--force]
itr-prep run        --year YYYY [--drop DIR] [--work DIR] [--out FILE]
                  [--account BROKER=ACCOUNT_ID ...] [--years 2022-2025]
                  [--peak-basis {usd,inr}] [--split-basis {current,historical}]
                  [--format {itr,prefill}] [--merge-into FILE] [--no-a2]
                  [--offline] [--no-validate]
itr-prep doctor     [--work DIR] [--years 2022-2025] [--no-prices] [--offline]
itr-prep import     --year YYYY --json FILE --utility FILE [--audit FILE]   # Windows/WSL
                  [--workdir 'C:\temp\itrprep'] [--name STEM] [--label NAME]
                  [--no-save] [--timeout SECS] [--verbose]
itr-prep fx-update  [--fx-cache PATH]
itr-prep normalize  --broker {etrade,fidelity,indmoney} --input FILE --account-id ID
                  [--out FILE] [--append] [--default-ticker SYM] [--acq-kind KIND]
itr-prep build      --year YYYY --out FILE [--work DIR]
                  [--format {itr,prefill}] [--merge-into FILE]
                  [--peak-basis {usd,inr}] [--split-basis {current,historical}]
                  [--cash FILE] [--no-a2] [--offline] [--no-validate]
itr-prep threshold  [--years 2022-2025] [--work DIR] [--out FILE]
                  [--peak-basis {usd,inr}] [--split-basis {current,historical}]
                  [--cash FILE] [--offline]
itr-prep unlock     [--input PATH] [--out-dir DIR] [--env-file FILE]
                  [--list-credentials]
itr-prep rules      [--assessment-year YYYY-YY] [--annual-only]
itr-prep validate   --json FILE [--schema FILE]
```

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
  host.py          the only module that knows the import step needs a Windows Excel
  unlock.py        .env-sourced document passwords that never leave the process
  cli.py           command line
rules/
  AY2026-27.json   every statutory figure, cited, classed stable or annual
docs/
  RUNBOOK_AY2026-27.md   linear checklist from downloads to a filed return
  ANNUAL-REVIEW.md       what to re-verify before filing a new assessment year
  VERIFIED_FINDINGS.md   what the VBA and schema actually say, with line numbers
  ROUNDTRIP_RESULT.md    the real import test and its output
  MACOS_UTILITY_TEST.md  how to settle the macOS utility's two open questions, in 20 min
  AI-ASSISTANCE.md       what a model may and may not do with a real filing's figures
scripts/
  make_macos_import_test.py  builds that test's two JSON shapes over a 178-row Table A3
  import_to_utility.py   the scripted import: fresh copy, COM drive, readback, save
  clear_modals.ps1       clear the splash form, VBA MsgBoxes and the Purview label dialog
  probe_workbook.ps1     inspect the utility's named ranges and lock state
  roundtrip.ps1          the original manual round-trip driver, kept for reference
tests/
  synthetic/             the nasty-cases dataset + broker export fixtures (all invented)
  synthetic_split/       AVGO held through the July 2024 10-for-1 split
  make_xlsx_fixture.py   builds real XLSX files, single- and multi-sheet, with the stdlib
  test_pipeline.py       end-to-end invariants
  test_validation_teeth.py       proof the validation rejects the traps
  test_splits_cash_threshold.py  splits, cash balances, threshold report
  test_doctor_readback.py        preflight, header sniffing, import verification,
                                 schema resolution
  test_multisection_adapter.py   per-section column resolution, gross/withheld/net,
                                 sell-to-cover, loud failure on a dropped row
  test_multisheet_workbook.py    every worksheet read, FMV over paid price, nested
                                 grant/vest/withholding records
  test_rules_registry.py         citations, review classes, AY coverage, staleness
  test_unlock_credentials.py     adversarial: proof a password cannot escape
schemas/                 where to put the ITD schema; contents are not tracked
data/                    cached FX rates and prices (created by fx-update / build)
work/                    your own CSVs (gitignored -- never committed)
work/unlocked/           decrypted statements, 0600 in a 0700 directory (gitignored)
out/                     generated JSON and audit trails (gitignored)
AGENTS.md                what an agent must read before it changes anything
.env.example             the credential template; the real .env is gitignored
```

All eight test suites are plain scripts with no test runner:

```bash
for t in tests/test_*.py; do .venv/bin/python "$t" || break; done
```

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
- **The threshold report is arithmetic, not advice.** It aggregates your own data against
  ₹20,00,000 on two bases. Which basis a tribunal would accept is unsettled, and the report
  says so rather than resolving it.
- **Only the ITR-2 utility is supported.** ITR-3 shares the VBA but the sheet/codename
  mapping was not checked.
- **The import step needs Windows, and the macOS alternative is unverified.** The pipeline
  runs anywhere; `itr-prep import` does not, because the department's `.xlsm` binds Windows
  CryptoAPI and Windows COM. The department's Common Offline Utility for macOS looks like
  the way through — it covers ITR-2 and accepts an imported JSON — but no run of this
  tool's output through it has been done, and its macOS build is Apple Silicon only. See
  [Where this runs](#where-this-runs), and
  [`docs/MACOS_UTILITY_TEST.md`](docs/MACOS_UTILITY_TEST.md) for the checklist that would
  close it.

---

## Roadmap

**Everything in this section is intent, not capability.** None of it is implemented, none of it
is scheduled, and none of it should affect a decision to use this tool. What the tool does today
is [Scope today](#scope-today-itr-2-only) and the rest of this README; if a claim appears here
and nowhere else, it is not built. Check the code before relying on any of it.

- **Indian mutual funds.** Capital gains on Indian mutual fund units, from a registrar or
  broker capital-gains statement. This is a genuinely different problem from the one solved
  here, not an extension of it: units are not lots of a foreign share, the holding-period and
  equity-oriented treatment differ, grandfathering to 31 January 2018 applies, and none of it
  touches Schedule FA. **The rules-registry entries now exist** —
  [`rules/AY2027-28.json`](rules/AY2027-28.json) carries grandfathering, Specified Mutual
  Funds, both rates, holding periods and FIFO, cited to the Income-tax Act, 2025 — but no
  code reads them and there are no fixtures. The registry work was the cheap half.
- **ITR-1, ITR-3 and ITR-4.** The department's utilities for these share much of the ITR-2
  VBA, so the import mechanism may well carry over — but "may well" is the whole distance
  between this list and the [Verification](#verification) section. Nothing about the sheet
  names, code names or named ranges in those workbooks has been checked here, and the one
  thing this project has learned repeatedly is that an unverified assumption about that
  utility is usually wrong. Each form would need its own round-trip, live, before being
  claimed.

Two things will not change if any of that happens: a statutory figure needs a primary citation
before it enters `rules/`, and the upload file keeps coming out of the department's own
software. See [The line this project will not cross](#the-line-this-project-will-not-cross).

---

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
or account numbers to anything public.
