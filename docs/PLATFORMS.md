# Where this runs

*Part of [itr-prep](../README.md) — platforms, the four routes off Windows, and the line the project will not cross.*

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
published for macOS as well as Windows: version **1.2.3, released 14 August 2026**, an 85 MB
ZIP listed as *Utility for MAC* on the department's
[Downloads → Income Tax Returns](https://www.incometax.gov.in/iec/foportal/downloads/income-tax-returns)
page. It is a wholly different program from the Excel utility — a
[Wails](https://wails.io) desktop app (Go 1.22 with an Angular front end), not a workbook —
and it generates and can directly submit the upload JSON itself, so nothing here has to
reproduce anything the department signs.

**The condition: the macOS build is Apple Silicon only.** Inspecting the Mach-O headers in
`ITDe-Filing-2026-1.2.3.dmg`, the application binary and its updater are both **arm64**, with
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

**Established by test, 25 August 2026:** the import rejects the partial
`{"ITR":{"ITR2":{"ScheduleFA":…}}}` document this tool emits by default — it attaches but
the app's Proceed button never enables, silently. The complete return `--merge-into`
produces imports cleanly and passes Internal Validation. A 178-row Table A3 survives it
entirely: the utility's own re-generated upload JSON was diffed field-by-field against the
input and every value matched — all 178 rows in order, ZIP codes zero-padded
(`00001`…`00178`), dates ascending, peak > closing everywhere. Full record in
[`docs/MACOS_UTILITY_TEST.md`](MACOS_UTILITY_TEST.md) (*Test outcome — 25 August 2026*),
including the utility version (1.2.3) this applies to — the department ships new builds
mid-season, so re-check the record before relying on it.

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
