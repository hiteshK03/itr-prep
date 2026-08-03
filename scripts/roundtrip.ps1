# Round-trip test: import a generated Schedule FA JSON into the real ITD utility and read
# the Schedule FA sheet back out.
#
# Rather than driving `Sub ImportJson()` -- which opens a modal file-picker that cannot be
# fed from COM -- this calls the exact two functions ImportJson itself calls:
#
#     ImportJson.ParseJson(jsonText)  ->  Scripting.Dictionary
#     dictionary("ITR")("ITR2")       ->  the node ImportJson unwraps to
#     ImportJson.ImportScheduleFA(node)
#
# so the production code path is exercised with the production data, minus the file dialog.
#
# Names must be module-qualified: ParseJson exists in both ParseJson.bas and ImportJson.bas,
# and ImportScheduleFA exists in both ImportJson.bas (Object overload, used here) and
# ImportPrefill.bas (String overload).
#
# Run scripts/clear_modals.ps1 concurrently -- the utility shows a modal UserForm while
# opening, which blocks every COM call until it is cleared.

param(
    [string]$Workbook = "C:\temp\itrprep\roundtrip.xlsm",
    [string]$Json     = "C:\temp\itrprep\synth_2025.json",
    [string]$SaveAs   = "C:\temp\itrprep\roundtrip_imported.xlsm"
)

$ErrorActionPreference = "Continue"

function Say($m) { Write-Output $m }

$jsonText = [System.IO.File]::ReadAllText($Json)
Say "json bytes: $($jsonText.Length)"

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $true          # CommandBars work poorly on an invisible instance
$excel.DisplayAlerts = $false
$excel.AutomationSecurity = 1   # msoAutomationSecurityLow -> enable macros
$excel.ScreenUpdating = $true

$exit = 1
try {
    Say "opening workbook ..."
    $wb = $excel.Workbooks.Open($Workbook, 0, $false, 5, "", "", $true)
    Say "opened: $($wb.Name)  readonly=$($wb.ReadOnly)  sheets=$($wb.Worksheets.Count)"

    # --- confirm the VBA project is callable, trying each plausible qualification ---
    Say "`n--- macro reachability ---"
    $canRun = $false
    foreach ($name in @("ImportJson.getITRNo", "getITRNo",
                        "'$($wb.Name)'!ImportJson.getITRNo",
                        "'$($wb.Name)'!getITRNo")) {
        try {
            $v = $excel.Run($name)
            Say "OK   $name -> $v"
            $canRun = $true
            $goodPrefix = if ($name -like "*!*") { "'$($wb.Name)'!" } else { "" }
            break
        } catch {
            Say "no   $name -> $($_.Exception.Message.Split([char]10)[0])"
        }
    }
    if (-not $canRun) {
        Say "`nFAILED: cannot invoke VBA. Macros are disabled for this location."
        Say "Add C:\temp\itrprep as a Trusted Location, or open the workbook by hand."
        throw "macros unavailable"
    }

    # --- pre-import state ---
    Say "`n--- before import ---"
    $a3 = $wb.Names.Item("FA_A3_Country").RefersToRange
    Say "FA_A3_Country = $($a3.Address(0,0))  rows=$($a3.Rows.Count)  locked=$($a3.Locked)"
    $sheet = $a3.Worksheet
    Say "sheet '$($sheet.Name)' protected=$($sheet.ProtectContents)"

    # Part B-TTI item 19 -> Yes. Validation rule 746 ties Schedule FA to this flag.
    try {
        $wb.Names.Item("AOIFlag_1").RefersToRange.Value2 = "Yes"
        Say "set AOIFlag_1 = 'Yes' (Part B-TTI item 19)"
    } catch {
        Say "could not set AOIFlag_1: $($_.Exception.Message.Split([char]10)[0])"
    }

    # --- parse + import, exactly as Sub ImportJson() does ---
    Say "`n--- import ---"
    $parsed = $excel.Run($goodPrefix + "ImportJson.ParseJson", $jsonText)
    Say "parsed JSON -> $($parsed.GetType().Name)"
    $itr = $parsed.Item("ITR")
    $itr2 = $itr.Item("ITR2")
    Say "unwrapped ITR.ITR2; keys present:"
    foreach ($k in $itr2.Keys()) { Say "   $k" }

    $fa = $itr2.Item("ScheduleFA")
    $rows = $fa.Item("DtlsForeignEquityDebtInterest")
    Say "A3 rows in JSON: $($rows.Count)"

    $excel.Run($goodPrefix + "ImportJson.ImportScheduleFA", $itr2)
    Say "ImportScheduleFA returned"

    # --- read the sheet back ---
    Say "`n--- after import ---"
    $a3 = $wb.Names.Item("FA_A3_Country").RefersToRange
    Say "FA_A3_Country now = $($a3.Address(0,0))  rows=$($a3.Rows.Count)"

    $cols = @{}
    foreach ($n in @("FA_A3_Country","FA_A3_BankName","FA_A3_BankAdd","FA_A3_ZipCode",
                     "FA_A3_NatureOfEntity","FA_A3_AccOpeningDate","FA_A3_initialvalue",
                     "FA_A3_PeakBal","FA_A3_ClosingBal","FA_A3_Totalgrossamount",
                     "FA_A3_Totalgrosproceeds")) {
        $cols[$n] = $wb.Names.Item($n).RefersToRange.Column
    }
    $firstRow = $a3.Row
    $n = $a3.Rows.Count
    Say "reading rows $firstRow..$($firstRow + $n - 1) from '$($sheet.Name)'"
    Say ""
    Say ("{0,-4} {1,-26} {2,-30} {3,-9} {4,-22} {5,-12} {6,-12} {7,-12} {8,-10} {9,-12}" -f `
         "row","country","entity","zip","nature","acqDate","initial","peak","closing","proceeds")
    for ($i = 0; $i -lt $n; $i++) {
        $r = $firstRow + $i
        $vals = @()
        foreach ($k in @("FA_A3_Country","FA_A3_BankName","FA_A3_BankAdd","FA_A3_ZipCode",
                         "FA_A3_NatureOfEntity","FA_A3_AccOpeningDate","FA_A3_initialvalue",
                         "FA_A3_PeakBal","FA_A3_ClosingBal","FA_A3_Totalgrosproceeds")) {
            $vals += [string]$sheet.Cells($r, $cols[$k]).Text
        }
        Say ("{0,-4} {1,-26} {2,-30} {3,-9} {4,-22} {5,-12} {6,-12} {7,-12} {8,-10} {9,-12}" -f `
             $r, $vals[0], $vals[1].Substring(0,[Math]::Min(29,$vals[1].Length)), $vals[3],
             $vals[4], $vals[5], $vals[6], $vals[7], $vals[8], $vals[9])
    }

    # --- A2 ---
    Say "`n--- Table A2 ---"
    try {
        $a2 = $wb.Names.Item("FA_A2_Country").RefersToRange
        Say "FA_A2_Country = $($a2.Address(0,0)) rows=$($a2.Rows.Count)"
        $a2cols = @{}
        foreach ($nm in @("FA_A2_Country","FA_A2_BankName","FA_A2_ForeignAccountNumber",
                          "FA_A2_StatusBeneficiary","FA_A2_PeakBal","FA_A2_ClosingBal",
                          "FA_A2_Grossinterest","FA_A2_Grossinterest_Nature")) {
            $a2cols[$nm] = $wb.Names.Item($nm).RefersToRange.Column
        }
        for ($i = 0; $i -lt $a2.Rows.Count; $i++) {
            $r = $a2.Row + $i
            $line = "row $r :"
            foreach ($nm in @("FA_A2_Country","FA_A2_BankName","FA_A2_ForeignAccountNumber",
                              "FA_A2_StatusBeneficiary","FA_A2_PeakBal","FA_A2_ClosingBal",
                              "FA_A2_Grossinterest","FA_A2_Grossinterest_Nature")) {
                $line += " [" + $sheet.Cells($r, $a2cols[$nm]).Text + "]"
            }
            Say $line
        }
    } catch {
        Say "A2 read failed: $($_.Exception.Message.Split([char]10)[0])"
    }

    $wb.SaveAs($SaveAs, 52)   # 52 = xlOpenXMLWorkbookMacroEnabled
    Say "`nsaved to $SaveAs"
    $wb.Close($false)
    $exit = 0
} catch {
    Say "`nERROR: $($_.Exception.Message)"
} finally {
    try { $excel.Quit() } catch {}
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
}
Say "`nexit=$exit"
exit $exit
