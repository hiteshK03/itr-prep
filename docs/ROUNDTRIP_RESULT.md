# Round-trip result: JSON -> real ITD utility -> Schedule FA sheet

> ## Every figure on this page is synthetic
>
> All inputs are the committed fixtures in [`tests/synthetic/`](../tests/synthetic) —
> invented lots in CSCO, JNJ, AVGO and IVV, chosen to exercise awkward cases (a lot spanning
> the 1 January boundary, a full exit, a FIFO sale with no lot id, pro-rata dividends). The
> issuer names and addresses are real public companies because Table A3 wants the *issuer's*
> details and the country/zip handling had to be tested against plausible values. **No row
> here describes anyone's actual holding**, and the Table A2 account numbers are literally
> `SYNTH-ET-0001`, `SYNTH-FD-0002` and `SYNTH-IM-0003`.
>
> Regenerate them yourself:
>
> ```bash
> itr-prep build --year 2025 --work tests/synthetic --out /tmp/synth_2025.json --offline
> ```

**Status: the round-trip was actually performed and passed.** This is not a code-read
inference. The generated JSON was fed through the utility's own import functions inside a
live Excel instance and the resulting sheet cells were read back and compared.

- Date: 2026-07-28
- Excel: Microsoft 365 desktop, **x64**. The 64-bit build matters, for the `PtrSafe`
  declarations in the utility's VBA; the specific version did not.
- Workbook: `ITR2_AY_26-27_V1.2.xlsm`, unmodified, copied to a scratch directory
- Input: `tests/synthetic/` -> `synth_2025.json` (12 A3 rows, 3 A2 rows)
- Driver: `scripts/roundtrip.ps1` + `scripts/clear_modals.ps1`

> **Superseded, and extended, on 2026-07-29.** This first round-trip was driven by a
> hand-run PowerShell script and its output compared by eye. It is now productised as
> `itr-prep import` (`scripts/import_to_utility.py` + `scripts/clear_modals.ps1`), which
> verifies every cell programmatically, and the same round-trip has been repeated on **all
> three** assessment years' utilities. See
> [the all-three-utilities section](#all-three-utilities-live-2026-07-29) at the end. The
> mechanics described below are still exactly what the scripted path does.
>
> **The cell dumps on this page are from the 2026-07-29 re-run**, not from the original
> 2026-07-28 one. The example tickers in the fixtures were changed after that first run, so
> the whole round-trip was repeated on all three utilities rather than leaving figures here
> that no longer corresponded to the committed fixtures. Every number below was read back out
> of a live sheet; none of it is transcribed from the generated JSON.

## How the file dialog was bypassed

`Sub ImportJson()` opens `Application.FileDialog(msoFileDialogFilePicker)`, which is modal
and cannot be fed over COM. Instead the script calls the same two functions `ImportJson`
itself calls, with the same arguments:

```powershell
$parsed = $excel.Run("ImportJson.ParseJson", $jsonText)
$itr2   = $parsed.Item("ITR").Item("ITR2")
$excel.Run("ImportJson.ImportScheduleFA", $itr2)
```

Module qualification is required: `ParseJson` exists in both `ParseJson.bas` and
`ImportJson.bas`, and `ImportScheduleFA` exists in both `ImportJson.bas` (the `Object`
overload, used here) and `ImportPrefill.bas` (the `String` overload).

So the only part of the production path not exercised is the file picker itself reading
bytes off disk. Everything downstream — parsing, unwrapping, row insertion, country lookup,
date reformatting, cell writes — is the real thing.

## Row auto-insertion worked

```
before import:  FA_A3_Country = E52:E57   rows=6
after  import:  FA_A3_Country = E52:E63   rows=12
```

The sheet ships with 6 A3 rows. The JSON had 12. `AddRows_A3_FA3(6)` inserted six rows and
extended all eleven A3 named ranges. **No manual row-adding is needed, and there is no row
cap.**

## All 12 A3 rows landed in the right columns

Read back from the `TR_FA` sheet after import:

```
row  country                    entity                     zip     nature               acqDate     initial  peak     closing  proceeds
52   2-UNITED STATES OF AMERICA Broadcom Inc.              94304   Listed Company       05/03/2025  996024   1638603  0        1533798
53   2-UNITED STATES OF AMERICA Cisco Systems, Inc.        95134   Listed Company       15/08/2024  202637   345700   172297   166345
54   2-UNITED STATES OF AMERICA Cisco Systems, Inc.        95134   Listed Company       15/02/2025  223931   250260   0        239136
55   2-UNITED STATES OF AMERICA Cisco Systems, Inc.        95134   Listed Company       15/05/2025  191398   251243   241216   0
56   2-UNITED STATES OF AMERICA Cisco Systems, Inc.        95134   Listed Company       30/06/2025  110404   157924   151621   0
57   2-UNITED STATES OF AMERICA Cisco Systems, Inc.        95134   Listed Company       15/08/2025  172981   215351   206756   0
58   2-UNITED STATES OF AMERICA iShares Core S&P 500 ETF   94105   Exchange Traded Fund 22/05/2023  1039498  1793054  612816   1172163
59   2-UNITED STATES OF AMERICA iShares Core S&P 500 ETF   94105   Exchange Traded Fund 08/01/2025  606876   741789   735379   0
60   2-UNITED STATES OF AMERICA Johnson & Johnson          08933   Listed Company       30/06/2023  206721   348112   333285   0
61   2-UNITED STATES OF AMERICA Johnson & Johnson          08933   Listed Company       29/12/2023  165392   290093   277737   0
62   2-UNITED STATES OF AMERICA Johnson & Johnson          08933   Listed Company       28/06/2024  144367   270754   259221   0
63   2-UNITED STATES OF AMERICA Johnson & Johnson          08933   Listed Company       31/12/2024  125684   232075   222190   0
```

Confirmed by this output:

- **The country code resolves correctly.** JSON carried the bare string `"2"`; the sheet
  shows `2-UNITED STATES OF AMERICA`, so `Findtext` matched the code against the dropdown
  list. A wrong code would have left the raw value in the cell and failed the dropdown.
- **Dates are reformatted as documented.** JSON `2024-08-15` became `15/08/2024`.
- **Money values arrive byte-identical** to what the emitter wrote (996024, 1638603, 0,
  1533798 for row 52), so no rounding or coercion happens in transit.
- **Every column is correctly aligned** — issuer name, address, zip and nature are the
  *company's*, which is what Table A3 asks for.
- **Leading-zero ZIPs survived**, but only because they are repaired: rows 60-63 show
  `08933`, which the utility had truncated to `8933` on import. See
  [the finding below](#three-things-the-automated-verification-found-that-eyeballing-had-not).
- Fully-exited lots (rows 52 and 54) show a nil closing balance with non-zero proceeds.

## Table A2 landed too, with the enums resolved

```
row 38 : [2-UNITED STATES OF AMERICA] [Morgan Stanley Smith Barney LLC (E*TRADE)] [SYNTH-ET-0001] [OWNER] [1220478] [771890] [405481] [Proceeds from sale or redemption of financial assets]
row 39 : [2-UNITED STATES OF AMERICA] [Fidelity Brokerage Services LLC] [SYNTH-FD-0002] [OWNER] [1141034] [1092433] [26515] [Dividend]
row 40 : [2-UNITED STATES OF AMERICA] [DriveWealth LLC] [SYNTH-IM-0003] [OWNER] [4173446] [1348195] [2728224] [Proceeds from sale or redemption of financial assets]
```

Columns shown: country, institution, account number, status, peak, closing, gross amount
credited, nature of amount.

The single-letter `NatureOfAmount` codes expanded to their display text (`S` ->
"Proceeds from sale or redemption of financial assets", `D` -> "Dividend"), and `Status`
`OWNER` was accepted. A2 needed no row insertion because the sheet ships with 6 rows.

## Two environment quirks worth knowing

1. **The utility shows a modal VBA UserForm while opening** (window class `ThunderDFrame`),
   which blocks all COM calls until dismissed. `scripts/clear_modals.ps1` clears it from a
   separate process. Irrelevant when opening by hand.

2. **Some managed corporate tenants enforce a sensitivity label on save.** Where that policy
   is in force, saving the workbook raises an "Add sensitivity label" dialog (`NUIDialog`)
   that blocks the save until answered — as it did here. It will also appear when the
   workbook is saved by hand or Generate JSON is used, so expect to pick a label. It does not
   affect the import itself, which completes before the save. `clear_modals.ps1` answers it
   during the scripted run.

---

## All three utilities, live (2026-07-29)

The round-trip above was repeated on every assessment year, using `itr-prep import`, each into
a fresh copy of the pristine utility, each verified cell by cell against its audit CSV rather
than by eye. Inputs were the same synthetic fixtures, built for each reporting year.

| Utility | `--year` | A3 rows | A2 rows | Result |
|---|---|---|---|---|
| `ITR2_AY_26-27_V1.2.xlsm` | 2025 | 12 | 3 | **PASS** |
| `ITR2_AY_25-26_V1.2.xlsm` | 2024 | 6 | 3 | **PASS** |
| `ITR2_AY_24-25_V1.8.xlsm` | 2023 | 3 | 2 | **PASS** |

Each run took 40-50 seconds unattended. The A3 and A2 named ranges, the `TR_FA` sheet name,
the `AOIFlag_1` name for Part B-TTI item 19, and the `ParseJson` / `ImportScheduleFA`
signatures were identical in all three — which is what the static VBA comparison predicted,
now measured rather than inferred.

Each year exercises a different table size, which is the point: the prior years are smaller
because the fixtures' later lots had not been acquired yet, so row insertion was tested
growing the sheet by different amounts — and in 2023 and 2024 by *less* than the six rows the
sheet ships with, so the trailing blank rows had to be distinguished from missing data.

Reproduce the inputs, and the counts in the table above, with:

```bash
for y in 2023 2024 2025; do
  itr-prep build --year $y --work tests/synthetic --out /tmp/synth_$y.json --offline
done
```

Calendar 2023 is assessment year 2024-25, whose schema the department no longer publishes, so
that build needs `--schema` pointed at the AY 2025-26 schema (or `--no-validate`). The tool
will not silently validate one year against another year's rules.

### Three things the automated verification found that eyeballing had not

1. **Leading-zero zip codes are silently truncated.** The utility's zip cell is
   number-formatted, so `ZipCode: "08933"` (New Brunswick, NJ) lands as `8933`, `"02210"`
   (Boston) as `2210` and `"07306"` (Jersey City) as `7306`, in both `.Text` and `.Value2`.
   The utility would then generate that wrong zip into the JSON you upload. Roughly a tenth
   of US zip codes begin with a zero — all of New England plus NJ, NY and PR — so this is
   routine, not a corner case. The 2025 run above repaired six such cells, four of them A3
   issuer zips and two A2 institution zips. `itr-prep import`
   now rewrites those cells as text after importing, and the verifier fails the import if the
   rewrite did not take. The cell is protected against *formatting* changes, so the repair
   writes the value with Excel's leading-apostrophe text prefix instead of setting
   `NumberFormat`.

2. **`ImportScheduleFA` leaves a `MsgBox` on screen when it finishes.** Until it is cleared,
   every subsequent COM call fails with `RPC_E_CALL_REJECTED` (0x80010001).
   `Application.DisplayAlerts = False` does not suppress a MsgBox raised from VBA. The first
   attempt at a scripted readback returned *empty tables* because of this — indistinguishable,
   from the outside, from an import that wrote nothing at all.

3. **Writing cells with events enabled can hang indefinitely.** The utility installs
   `Worksheet_Change` handlers that recalculate across a 10 MB workbook. The zip repair is
   done with `EnableEvents = False` and manual calculation for that reason.

## What is still not proven

- The file picker path itself. `Sub ImportJson()` was not driven through its dialog, so the
  claim "clicking Import will work" rests on the fact that everything after the dialog is
  what was tested. The manual instructions in the README follow the clicking path.
- `Sub ImportPrefill()` and the `--format prefill` output were **not** round-tripped. Only
  the default `--format itr` path was. Prefer the default.
- Generate JSON -> portal upload -> portal-side validation. Not tested at all.
- The AY 2024-25 round-trip used the AY 2025-26 JSON schema for validation, because that
  year's own schema is no longer published. The *import* is measured; the schema check for
  that year is still inference.
