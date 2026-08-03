# Verified findings from the official ITD artifacts

Everything in this file was read directly out of the ITD's own published artefacts, listed
below — the offline utility and the VBA recovered from it. Each claim names its source and
cites line numbers, so a future reader can re-check it against a freshly downloaded utility
instead of trusting this file. None of these artefacts are redistributed here; download the
utility from the e-filing portal and decompile it yourself if you want to verify.

Sources:

- `ITR2_AY_26-27_V1.2/ITR2_AY_26-27_V1.2.xlsm` — official ITR-2 Excel utility v1.2 (AY 2026-27)
- `vba/olevba_out.vba` — 236,599 lines of VBA source recovered from the utility's
  `xl/vbaProject.bin` with `oletools.olevba --code`
- `ITR-2_2026_Main_V1.1.json` — official JSON schema for the ITR-2 return
- `ITR2_Validation_Rules_AY2026-27_V1.0.pdf` (text: `vba/itr2_valid_clean.txt`)
- `ITD_StepByStep_FA_FSI.pdf` (text: `vba/fa_guide_pdfminer.txt`)

---

## 1. There are TWO import entry points, and they read DIFFERENT JSON shapes

This is the single most important finding, and it corrected an earlier wrong assumption.

| Module | Sub | Reads |
|---|---|---|
| `ImportJson.bas` | `Sub ImportJson()` (line 178628) | `jsonObject("ITR")("ITR2")` then `("ScheduleFA")("DtlsForeignEquityDebtInterest")` — **PascalCase** |
| `ImportPrefill.bas` | `Sub ImportPrefill()` (line 209740) | `jsonObject("lastFiledITR")("scheduleFA")("dtlsForeignEquityDebtInterest")` — **camelCase** |

`ImportJson` unwraps the ITR root explicitly (line 178656-178662):

```vb
If getITRNo = 3 Then
    Set jsonObject = jsonObject("ITR")("ITR3")
ElseIf getITRNo = 2 Then
    Set jsonObject = jsonObject("ITR")("ITR2")
```

then calls `ImportScheduleFA (jsonObject)` at line 178717, which resolves to the
`Function ImportScheduleFA(ByVal jsonObject As Object)` overload at line 198539.

`ImportPrefill` instead calls `ImportScheduleFA (jsonText)` at line 209783, resolving to
`Function ImportScheduleFA(jsonText As String)` at line 218657, whose FA table keys are
all camelCase under `lastFiledITR.scheduleFA`, including the ITD's own typo
`detailsForiegnBank` ("Foriegn").

**This tool targets `ImportJson` (the PascalCase / `ITR.ITR2` form) by default**, because that
is the same shape the utility's own `GenerateJson.bas` emits and the same shape the downloaded
`ITR-2_2026_Main_V1.1.json` schema describes. That means one artifact can be both
schema-validated and imported. A `--format prefill` emitter is provided for the other path.

## 2. Table A3 field contract — `DtlsForeignEquityDebtInterest`

Read from the importer (VBA lines 198907-198950), cross-checked against the generator
(`GenerateJson.bas` lines 175636-175719) and the schema definition.

| JSON key | Excel named range | Schema type / constraint |
|---|---|---|
| `CountryName` | (not imported; generator emits it) | string, 1-55 chars, **required** |
| `CountryCodeExcludingIndia` | `FA_A3_Country` | enum of **strings**, required |
| `NameOfEntity` | `FA_A3_BankName` | string, 1-125 |
| `AddressOfEntity` | `FA_A3_BankAdd` | string, 1-200 |
| `ZipCode` | `FA_A3_ZipCode` | string, 1-8 |
| `NatureOfEntity` | `FA_A3_NatureOfEntity` | string, 1-34 |
| `InterestAcquiringDate` | `FA_A3_AccOpeningDate` | string `YYYY-MM-DD` |
| `InitialValOfInvstmnt` | `FA_A3_initialvalue` | **integer** |
| `PeakBalanceDuringPeriod` | `FA_A3_PeakBal` | **integer** |
| `ClosingBalance` | `FA_A3_ClosingBal` | **integer** |
| `TotGrossAmtPaidCredited` | `FA_A3_Totalgrossamount` | **integer** |
| `TotGrossProceeds` | `FA_A3_Totalgrosproceeds` | **integer** |

All 12 are in the schema's `required` list and the object is `additionalProperties: false`,
so emitting a partial row or an unexpected key is a hard validation failure.

**Table A3 has no owner/beneficiary `Status` field.** An earlier note of mine wrongly
attached the `BENIFICIARY` trap to A3; it belongs to A1/A2 only. Verified by the absence of
any `Status` read in the A3 loop and by the schema's A3 property list.

## 3. Table A2 field contract — `DtlsForeignCustodialAcc`

Keys read by the importer: `CountryCodeExcludingIndia`, `FinancialInstName`,
`FinancialInstAddress`, `ZipCode`, `AccountNumber`, `Status`, `AccOpenDate`,
`PeakBalanceDuringPeriod`, `ClosingBalance`, `GrossAmtPaidCredited`, `NatureOfAmount`
(+ `CountryName` required by the schema). All 12 required, `additionalProperties: false`.

Two enums matter:

- `Status`: `["OWNER", "BENEFICIAL_OWNER", "BENIFICIARY"]`
  — **`BENIFICIARY` is misspelled in the official schema and in the VBA.** The VBA compares
  the literal string at lines 218784-218792. Do not "correct" this spelling; a corrected
  spelling fails schema validation and falls through to `"(Select)"` in the sheet.
- `NatureOfAmount`: `["I", "D", "S", "O", "N"]` = Interest / Dividend / Sale-or-redemption
  proceeds / Other income / No amount paid-credited.

`GrossAmtPaidCredited` has `minimum: 0` (unlike the A3 money fields, which allow negatives).

## 4. Country code for the USA is the STRING `"2"`

`definitions.CountryCodeExcludingIndia` is a 249-entry enum of **strings**; `"2"` is present
and `2` (integer) is not. Its `description` carries the code-to-name map, which includes
`2:UNITED STATES OF AMERICA`. So:

- `CountryCodeExcludingIndia = "2"` (string, quoted)
- `CountryName = "UNITED STATES OF AMERICA"`

Watch out for neighbours: `1:CANADA`, `44:UNITED KINGDOM...`,
`1009:UNITED STATES MINOR OUTLYING ISLANDS`, `1340:VIRGIN ISLANDS (U.S.)`.

In the sheet the country cell is not the bare code — `Findtext` (line 94727) scans the
dropdown list for an entry whose text before the first `-` equals the code, and writes the
whole `"<code>-<NAME>"` string. That only matters if writing to Excel directly; via JSON
import the bare code is correct.

## 5. Dates: JSON is `YYYY-MM-DD`, the sheet is `DD/MM/YYYY`

The importer converts explicitly (A3, lines 198932-198937):

```vb
Date_1 = Node("InterestAcquiringDate")
YYYY = Mid(Date_1, 1, 4)
MM = Mid(Date_1, 6, 2)
DD = Mid(Date_1, 9, 2)
Date_1 = DD & "/" & MM & "/" & YYYY
```

So emit ISO `YYYY-MM-DD` in JSON. The schema also enforces the pattern
`([12]\d{3}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01]))`.

## 6. Rows are auto-added; there is no row cap

`AddRows_A3_FA3(DiffRows As Long)` (line 96921):

```vb
Sub AddRows_A3_FA3(DiffRows As Long)
    setTblinfo_A3_FA
    Sheet27.Activate
    SelectLastRow ("FA_A3_Country")
    InsertDiffRowsAndFillFormulas (DiffRows)
    Call ExendRangeNameToTable(DiffRows, rngname_A3_FA)
End Sub
```

The importer computes `TotalDiffRow = TotalXMLRow - TotalExRow` and calls this when the JSON
has more rows than the sheet currently shows (A3: line 198900-198902). It both inserts the
rows and extends all eleven A3 named ranges, so the table genuinely grows. Neither the schema
nor the VBA imposes a maximum row count for Schedule FA.

## 7. Import is destructive per-table, and silent on failure

- When a table's array is present and non-empty, the importer calls `.ClearContents` on every
  column of that table first (A3: lines 198864-198898). Existing rows in that table are wiped.
- When the array is **absent**, the whole `If init.exists(...)` block is skipped, so other
  tables and other schedules are untouched. This is why a ScheduleFA-only JSON is safe to
  import: it cannot blank out schedules it does not mention.
- Every import function opens with `On Error Resume Next`. A malformed value fails **silently**
  — no error dialog. You must visually confirm the rows landed. This is the main reason a
  code-read alone is weaker evidence than an actual round-trip.

## 8. Validation rule 746 — Schedule FA is gated, but not by cell locking

Verbatim from the validation rules PDF (rule 746):

> Schedule FA has to be filled if SL.no.19 of Part B-TTI is selected as "Yes"

That flag lives in the named range `AOIFlag_1` on the sheet `Part B - TI TTI` (cell L129),
and in JSON as `PartB_TTI.AssetOutIndiaFlag` with the enum `["YES", "NO"]`.

An earlier version of this note claimed the FA cells stay **locked** until item 19 is Yes,
so that importing first would silently write nothing. **Measurement disproved that.**
Opening the pristine v1.2 workbook and reading the ranges showed, with `AOIFlag_1` empty:

```
FA_A3_Country              E52:E57        rows=6    locked=False
FA_A3_BankName             F52:F57        rows=6    locked=False
...all eleven A3 columns    locked=False
```

The `TR_FA` sheet is protected (`ProtectContents = True`) but the A3 input cells are
unlocked, so the importer's `If ... .Locked = False Then` guards pass and the import
succeeds regardless of item 19. Item 19 still has to be set to "Yes" for the **return** to
be valid under rule 746 — it just is not a precondition for the import to work.

Note the guards do matter in general: a cell that *is* locked is skipped silently, and
because every import function opens with `On Error Resume Next` there is no error either
way. Always eyeball the sheet after importing.

## 9. Reporting period is the CALENDAR year

From the step-by-step guide:

> Taxpayers must furnish details of foreign assets or accounts of the following nature, held
> at any time during the relevant **calendar year ending on December 31st**

So for AY 2026-27 (FY 2025-26) Schedule FA covers **1 Jan 2025 – 31 Dec 2025**, not the
financial year. Schedule CG / OS / FSI / TR remain on the financial year.

## 10. FX conversion — per-date TT buying rate, not a single year-end rate

This is the authoritative sentence, verbatim from the step-by-step guide, section
"Currency Conversion and Valuation Guidelines":

> Exchange Rate Conversion: All peak balances, values of investment, and amounts of
> foreign-sourced income must be converted into Indian currency using the telegraphic
> transfer buying rate of the foreign currency as on the relevant date: **the date of peak
> balance in the account, the date of investment, or the closing date of the calendar year
> ending on December 31st.**

Which pins down three different dates for three different fields:

| Field | TT-buy rate date |
|---|---|
| `InitialValOfInvstmnt` | date of investment (the acquisition/vest/purchase date) |
| `PeakBalanceDuringPeriod` | the date on which the peak balance occurred |
| `ClosingBalance` | 31 December of the reporting calendar year |
| `TotGrossAmtPaidCredited`, `TotGrossProceeds` | date of each dividend / sale |

Note the wording orders the operation as "the date of peak balance" — i.e. the peak is
identified first, then converted at that date's rate. See the README's peak-value section for
how this tool implements that and what the alternative reading would do.

## 11. `Digest` is computed inside the utility

The `Digest` field is an HMAC the utility fills in at Generate-JSON time using a key held in a
hidden sheet; the schema permits `"-"`. Because this tool routes everything through the
utility's own Generate JSON step, the digest is never something we need to forge.

## 12. The Schedule FA import path is identical across AY 2024-25, 2025-26 and 2026-27

Established because `--year 2023` and `--year 2024` feed updated returns under s.139(8A) for
the earlier assessment years, and it would have been an assumption otherwise.

Artifacts compared (each the latest version published for its AY):

| Assessment year | Utility | Schema |
|---|---|---|
| AY 2024-25 | `ITR2_AY_24-25_V1.8.xlsm` (published 2025-01) | not retrievable, see below |
| AY 2025-26 | `ITR2_AY_25-26_V1.2.xlsm` (published 2025-09) | `ITR-2_2025_Main_V1.1.json` |
| AY 2026-27 | `ITR2_AY_26-27_V1.2.xlsm` (published 2026-07) | `ITR-2_2026_Main_V1.1.json` |

### VBA

`Function ImportScheduleFA(ByVal jsonObject As Object)` was extracted from all three
`vbaProject.bin` files with `olevba -c` and compared line by line.

- **1,409 lines in each.**
- AY 2024-25 vs AY 2026-27: **identical** once identifier casing and trailing whitespace are
  normalised.
- AY 2025-26 vs AY 2026-27: identical on the same basis. The only textual difference anywhere
  is the loop variable, spelled `node` in the two earlier utilities and `Node` in AY 2026-27.
  VBA identifiers are case-insensitive, so this is a VBE re-casing artifact and not a
  behavioural change.
- All three read the **same 63 JSON keys**, extracted as the set matched by
  `[Nn]ode\("([A-Za-z]+)"\)` within the function. Set difference in both directions is empty.
  That set includes every Table A2 and A3 field this tool emits.
- All three write via the VBA code name **`Sheet27`** and nothing else.

### Sheet identity

`Sheet27` was resolved to a display name by reading `<sheetPr codeName=...>` out of each
worksheet part and mapping it back through `xl/_rels/workbook.xml.rels` and
`xl/workbook.xml`. In all three workbooks:

```
AY2024-25 V1.8: Sheet27 == 'TR_FA'
AY2025-26 V1.2: Sheet27 == 'TR_FA'
AY2026-27 V1.2: Sheet27 == 'TR_FA'
```

All three also expose `Part A Gen_139(8A)` and `Part B ATI`, which is what an updated return
needs. Sheet counts differ slightly (63 / 65 / 66), so the workbooks are not identical
overall — only the Schedule FA import path is.

### Schema

Comparing the `ScheduleFA` definition between `ITR-2_2025_Main_V1.1.json` and
`ITR-2_2026_Main_V1.1.json`:

- Same ten tables, same order, same `$ref` targets, no `maxItems` on any of them.
- `DtlsForeignEquityDebtInterest`: same 12 required fields, and **all 12 property
  definitions compare equal** — types, patterns, length limits and minima.
- `DtlsForeignCustodialAcc`: same 12 required fields, all 12 property definitions equal.

### The one gap

The **AY 2024-25 JSON schema is not retrievable**. The published-file URL pattern
(`sites/default/files/YYYY-MM/ITR-2_YYYY_Main_Vx.y.json`) was probed across every plausible
month and version for 2024 and returns 404 throughout, while the AY 2025-26 file resolves at
`2025-08/ITR-2_2025_Main_V1.1.json`. So `--year 2023` output is validated against the later
schema. Given the A2/A3 definitions are unchanged between AY 2025-26 and AY 2026-27, and the
AY 2024-25 utility's importer reads the identical key set, the risk is low — but this is
inference from the importer rather than a check against that year's own schema, and the
README says so.
