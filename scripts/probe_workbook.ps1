# Stage 1 of the round-trip: open the utility and report the state of the Schedule FA
# sheet before anything is imported. Read-only; saves nothing.

$ErrorActionPreference = "Stop"
$wbPath = "C:\temp\itrprep\roundtrip.xlsm"

Write-Output "opening $wbPath ..."
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
# msoAutomationSecurityLow: enable macros when opening via automation, which is what the
# utility needs. Without it Excel silently disables the VBA project.
$excel.AutomationSecurity = 1

try {
    $wb = $excel.Workbooks.Open($wbPath)
    Write-Output "opened. sheets=$($wb.Worksheets.Count)  names=$($wb.Names.Count)"

    Write-Output "`n--- is the VBA project actually live? ---"
    try {
        $itrNo = $excel.Run("getITRNo")
        Write-Output "getITRNo() = $itrNo   (2 confirms this is the ITR-2 utility)"
    } catch {
        Write-Output "MACROS NOT AVAILABLE: $($_.Exception.Message)"
    }

    Write-Output "`n--- Part B-TTI item 19 flag ---"
    try {
        $aoi = $wb.Names.Item("AOIFlag_1").RefersToRange
        Write-Output "AOIFlag_1 -> $($aoi.Address(0,0)) on '$($aoi.Worksheet.Name)' = '$($aoi.Value2)'"
    } catch {
        Write-Output "AOIFlag_1 not found: $($_.Exception.Message)"
    }

    Write-Output "`n--- Schedule FA named ranges (A3 table) ---"
    foreach ($n in @("FA_A3_Country","FA_A3_BankName","FA_A3_BankAdd","FA_A3_ZipCode",
                     "FA_A3_NatureOfEntity","FA_A3_AccOpeningDate","FA_A3_initialvalue",
                     "FA_A3_PeakBal","FA_A3_ClosingBal","FA_A3_Totalgrossamount",
                     "FA_A3_Totalgrosproceeds")) {
        try {
            $r = $wb.Names.Item($n).RefersToRange
            Write-Output ("{0,-26} {1,-14} rows={2,-4} locked={3}" -f $n, $r.Address(0,0), $r.Rows.Count, $r.Locked)
        } catch {
            Write-Output ("{0,-26} MISSING" -f $n)
        }
    }

    Write-Output "`n--- Schedule FA sheet protection ---"
    try {
        $sheet = $wb.Names.Item("FA_A3_Country").RefersToRange.Worksheet
        Write-Output "sheet name       : $($sheet.Name)"
        Write-Output "sheet codename   : $($sheet.CodeName)"
        Write-Output "ProtectContents  : $($sheet.ProtectContents)"
        Write-Output "visible          : $($sheet.Visible)"
    } catch {
        Write-Output "could not inspect: $($_.Exception.Message)"
    }

    $wb.Close($false)
} finally {
    $excel.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
}
Write-Output "`ndone."
