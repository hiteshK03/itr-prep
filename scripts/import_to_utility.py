#!/usr/bin/env python3
"""Import a generated Schedule FA JSON into the ITD Excel utility, and verify it landed.

Runs from WSL or from Windows itself, driving Excel through `powershell.exe`. Only the
stdlib is used here; the verification lives in `itrprep.readback` and the platform question
in `itrprep.host`, both of which are portable and both of which are tested everywhere.

What it automates, and why each part is not optional:

* A **fresh copy** of the pristine utility, every time. Importing twice into one workbook
  leaves blank rows that the utility gives you no way to delete, so a reused workbook is
  unfilable and the failure is invisible until the portal rejects it.
* The **modal splash UserForm** the utility shows while opening. It blocks every COM call
  until dismissed, so a watcher process clears it from outside the blocked call.
* **Part B-TTI item 19 = "Yes"** before importing. Validation rule 746 rejects a return
  carrying Schedule FA rows without it.
* Import via `ParseJson` + `ImportScheduleFA`, the two functions `Sub ImportJson()` calls
  internally, because ImportJson itself opens a file-picker dialog that COM cannot feed.
* **Readback verification of every cell.** `ImportScheduleFA` runs under
  `On Error Resume Next`: it cannot fail visibly. Trusting it is the single biggest risk in
  the whole workflow.

The import path is character-identical in the AY 2024-25, 2025-26 and 2026-27 utilities --
same named ranges, same signatures -- so `--utility` plus `--year` handles prior years.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import host, readback  # noqa: E402

# Macros only run from a Trusted Location, and a UNC path (\\wsl$\...) is never trusted.
# So the workbook and the JSON must both live on the Windows filesystem.
DEFAULT_WORKDIR = "C:\\temp\\itrprep"

# Managed tenants make Purview labelling mandatory, and Save blocks on the label dialog
# until one is chosen. A personal tax return is not business data, and an encrypting label
# ("Confidential", "Restricted") yields a file the income-tax portal cannot read -- so the
# least restrictive label is both the accurate choice and the safe one.
DEFAULT_LABEL = "Non-Business"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLEAR_MODALS_SCRIPT = os.path.join(SCRIPT_DIR, "clear_modals.ps1")

A3_COLUMNS = [
    "FA_A3_Country", "FA_A3_BankName", "FA_A3_BankAdd", "FA_A3_ZipCode",
    "FA_A3_NatureOfEntity", "FA_A3_AccOpeningDate", "FA_A3_initialvalue",
    "FA_A3_PeakBal", "FA_A3_ClosingBal", "FA_A3_Totalgrossamount",
    "FA_A3_Totalgrosproceeds",
]
A2_COLUMNS = [
    "FA_A2_Country", "FA_A2_BankName", "FA_A2_BankAdd", "FA_A2_ZipCode",
    "FA_A2_ForeignAccountNumber", "FA_A2_StatusBeneficiary", "FA_A2_AccOpeningDate",
    "FA_A2_PeakBal", "FA_A2_ClosingBal", "FA_A2_Grossinterest",
    "FA_A2_Grossinterest_Nature",
]


class ImportFailed(Exception):
    """A stage of the import failed in a way the user has to act on."""


def win_path(wsl_path: str) -> str:
    """/mnt/c/temp/x -> C:\\temp\\x"""
    out = subprocess.run(["wslpath", "-w", wsl_path], capture_output=True, text=True)
    if out.returncode != 0:
        raise ImportFailed(f"wslpath failed for {wsl_path}: {out.stderr.strip()}")
    return out.stdout.strip()


def wsl_path(windows_path: str) -> str:
    out = subprocess.run(["wslpath", "-u", windows_path],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise ImportFailed(f"wslpath failed for {windows_path}: {out.stderr.strip()}")
    return out.stdout.strip()


def powershell(script_text: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", script_text],
        capture_output=True, text=True, timeout=timeout,
    )


# Office caches the tenant's Purview label policy here, one gzipped XML per signed-in
# identity. It is the same list the "Add sensitivity label" dialog offers.
LABEL_TAG = re.compile(r"<label\b(?P<attrs>[^>]*?)(?P<selfclose>/?)>", re.S)
LABEL_ATTR = re.compile(r'(\w+)="([^"]*)"')


def _clp_policy_files() -> list[str]:
    """Office's label-policy cache as WSL paths; empty on a machine with no policy."""
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "[Console]::Out.Write($env:LOCALAPPDATA)"],
        capture_output=True, text=True,
    )
    local = out.stdout.strip()
    if not local:
        return []
    try:
        folder = wsl_path(local + "\\Microsoft\\Office\\CLP")
    except ImportFailed:
        return []
    return sorted(glob.glob(os.path.join(folder, "policy.*.gz")))


def resolve_sensitivity_label(want: str) -> dict:
    """Find the Purview label named `want` in Office's own policy cache.

    Applying the label through the object model is the only reliable way to save on a
    tenant that makes labelling mandatory. Driving the "Add sensitivity label" dialog
    instead is a trap: answering it any way that does not actually apply a label leaves
    `Workbook.Save` returning **success having written nothing to disk**, so the import
    looks complete and the file on disk is still the pristine utility.

    Returns {} when there is no policy at all -- an unmanaged machine, where Save just
    works and no label is needed.

    Refuses an encrypting label. Encryption produces a file the e-filing portal cannot
    read, and that failure would otherwise surface only at upload.
    """
    for path in _clp_policy_files():
        try:
            with gzip.open(path, "rb") as fh:
                text = fh.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        tenant = ""
        found = re.search(r"<TenantId>([^<]+)</TenantId>", text)
        if found:
            tenant = found.group(1).strip()
        mandatory = 'key="mandatory" value="true"' in text

        candidates = []
        for match in LABEL_TAG.finditer(text):
            attrs = dict(LABEL_ATTR.findall(match.group("attrs")))
            if not attrs.get("id") or not attrs.get("name"):
                continue
            if attrs.get("enabled") != "true" or attrs.get("isParentLabel") == "true":
                continue
            if match.group("selfclose"):
                body = ""
            else:
                end = text.find("</label>", match.end())
                body = text[match.end():end] if end != -1 else ""
            candidates.append({
                "id": attrs["id"],
                "name": attrs["name"],
                "site_id": tenant,
                "mandatory": mandatory,
                # A protection/encryption block on the label is what makes the saved file
                # unreadable to the portal.
                "encrypting": bool(re.search(r"protect|encrypt|templateid", body, re.I)),
            })
        if not candidates:
            continue

        lowered = want.strip().casefold()
        for test in (lambda n: n.casefold() == lowered,
                     lambda n: n.casefold().startswith(lowered),
                     lambda n: lowered in n.casefold()):
            for cand in candidates:
                if test(cand["name"]):
                    cand["offered"] = [c["name"] for c in candidates]
                    return cand
        return {"missing": want, "offered": [c["name"] for c in candidates],
                "mandatory": mandatory, "site_id": tenant}
    return {}


def build_driver_ps(workbook_win: str, json_win: str, dump_win: str,
                    save: bool = True, trace_win: str = "",
                    label: dict | None = None) -> str:
    """The PowerShell half: open, set the flag, import, dump every cell, save.

    Everything it knows how to do is mechanical. It makes no judgements and reports no
    verdict -- it writes the cells to JSON and Python decides whether they are right.
    """
    a3_list = ",".join(f'"{c}"' for c in A3_COLUMNS)
    a2_list = ",".join(f'"{c}"' for c in A2_COLUMNS)
    label = label or {}
    label_id = label.get("id", "")
    label_name = label.get("name", "")
    label_site = label.get("site_id", "")
    # The workbook was opened from the fresh copy already sitting at its final path, so a
    # plain Save is enough. SaveAs to the same path would raise an overwrite prompt, which
    # is one more modal dialog to fight for no benefit.
    save_block = '$wb.Save()' if save else '$null = 1  # --no-save'
    return f'''
$ErrorActionPreference = "Continue"
$result = @{{ stage = "start"; ok = $false; notes = @() }}

# Stage trace, flushed to disk as it goes. COM automation of this workbook can block with
# no dialog on screen and no output, and without this a hang is indistinguishable from slow
# -- there is nothing to look at and nothing to report to the user.
function Trace($stage) {{
    $result.stage = $stage
    if ("{trace_win}") {{
        try {{
            $line = "{{0:HH:mm:ss}} {{1}}" -f (Get-Date), $stage
            [System.IO.File]::AppendAllText("{trace_win}", "$line`r`n")
        }} catch {{ }}
    }}
}}

# A VBA MsgBox leaves Excel refusing every COM call with RPC_E_CALL_REJECTED
# (0x80010001) until it is cleared. The watcher process clears it, but there is a race
# between the dialog appearing and being dismissed, so calls that can land in that window
# are retried rather than treated as failures.
function Invoke-Retry {{
    param([scriptblock]$Action, [string]$What, [int]$Tries = 30)
    for ($i = 1; $i -le $Tries; $i++) {{
        try {{
            return & $Action
        }} catch {{
            $msg = $_.Exception.Message
            $busy = ($msg -match "0x80010001") -or ($msg -match "rejected by callee") -or
                    ($msg -match "0x8001010A") -or ($msg -match "is busy")
            if (-not $busy -or $i -eq $Tries) {{ throw }}
            Start-Sleep -Milliseconds 1000
        }}
    }}
}}

$jsonText = [System.IO.File]::ReadAllText("{json_win}")

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $true            # CommandBars misbehave on an invisible instance
$excel.DisplayAlerts = $false
$excel.AutomationSecurity = 1     # msoAutomationSecurityLow -> macros enabled
$excel.EnableEvents = $true

try {{
    Trace "open"
    $wb = $excel.Workbooks.Open("{workbook_win}", 0, $false, 5, "", "", $true)
    $result.workbook = $wb.Name

    # -- prove the VBA project is reachable, and learn how names must be qualified --
    Trace "macro-reachability"
    $prefix = $null
    foreach ($name in @("ImportJson.getITRNo", "getITRNo",
                        "'$($wb.Name)'!ImportJson.getITRNo")) {{
        try {{
            $null = $excel.Run($name)
            $prefix = if ($name -like "*!*") {{ "'$($wb.Name)'!" }} else {{ "" }}
            break
        }} catch {{ }}
    }}
    if ($null -eq $prefix) {{
        throw "cannot invoke VBA: macros are disabled for this location. Add the folder as a Trusted Location in Excel (File > Options > Trust Center > Trusted Locations)."
    }}
    $result.macro_prefix = $prefix

    # -- Part B-TTI item 19: validation rule 746 requires it before FA data means anything
    Trace "aoi-flag"
    $wb.Names.Item("AOIFlag_1").RefersToRange.Value2 = "Yes"
    $result.aoi_flag = [string]$wb.Names.Item("AOIFlag_1").RefersToRange.Text

    # -- import exactly as Sub ImportJson() does, minus its file dialog --
    Trace "parse-json"
    $parsed = $excel.Run($prefix + "ImportJson.ParseJson", $jsonText)
    $itr2 = $parsed.Item("ITR").Item("ITR2")

    Trace "import-schedule-fa"
    $excel.Run($prefix + "ImportJson.ImportScheduleFA", $itr2)

    # ImportScheduleFA finishes with a MsgBox. Wait for the watcher to clear it before
    # reading anything, otherwise every cell read is rejected and the dump comes back
    # empty -- which looks identical to an import that wrote nothing.
    Trace "await-dialog-clear"
    $null = Invoke-Retry {{ $wb.Names.Item("FA_A3_Country").RefersToRange.Column }} "settle"

    # -- repair leading-zero zip codes ---------------------------------------
    # The utility's zip cells are number-formatted, so the importer's write turns 02210
    # into 2210 and 07306 into 7306. That wrong zip then flows into the JSON the portal
    # receives. Re-write the affected cells as text with the value from the JSON. Around a
    # tenth of US zips begin with a zero, so this is a routine repair, not an edge case.
    #
    # Events are switched off for the write. The utility installs Worksheet_Change
    # handlers that recalculate across a 10 MB workbook, and leaving them live made a
    # handful of cell writes hang indefinitely.
    Trace "repair-zips"
    $repairs = @()
    $excel.EnableEvents = $false
    $excel.Calculation = -4135          # xlCalculationManual
    function Repair-Zips($anchorName, $zipName, $nodes, $zipKey) {{
        $fixed = @()
        try {{
            $anchor = $wb.Names.Item($anchorName).RefersToRange
            $sheet = $anchor.Worksheet
            $zipCol = $wb.Names.Item($zipName).RefersToRange.Column
            $first = $anchor.Row
            $i = 0
            foreach ($node in $nodes) {{
                $want = [string]$node.Item($zipKey)
                if ($want -and $want.StartsWith("0")) {{
                    $cell = $sheet.Cells($first + $i, $zipCol)
                    if (-not $cell.Locked) {{
                        # Preferred: make the cell text, then write the zip. The sheet is
                        # protected against formatting, so this usually throws -- in which
                        # case write it with Excel's leading-apostrophe text prefix, which
                        # forces text storage without touching the cell format. The
                        # apostrophe is not part of the value: .Value2 reads back "02210".
                        try {{
                            $cell.NumberFormat = "@"
                            $cell.Value2 = $want
                        }} catch {{
                            $cell.Formula = "'" + $want
                        }}
                        $got = [string]$cell.Text
                        $fixed += "$zipName row $($first + $i): $want (cell now '$got')"
                    }}
                }}
                $i++
            }}
        }} catch {{
            $fixed += "$zipName repair failed: $($_.Exception.Message.Split([char]10)[0])"
        }}
        return $fixed
    }}
    $faNode = $itr2.Item("ScheduleFA")
    try {{
        $repairs += Repair-Zips "FA_A3_Country" "FA_A3_ZipCode" `
            $faNode.Item("DtlsForeignEquityDebtInterest") "ZipCode"
    }} catch {{ }}
    try {{
        $repairs += Repair-Zips "FA_A2_Country" "FA_A2_ZipCode" `
            $faNode.Item("DtlsForeignCustodialAcc") "ZipCode"
    }} catch {{ }}
    $result.zip_repairs = $repairs
    $excel.Calculation = -4105          # xlCalculationAutomatic
    $excel.EnableEvents = $true

    # -- read every cell of both tables back --
    Trace "readback"
    function Dump-Table($colNames) {{
        $cols = @{{}}
        $missing = @()
        foreach ($n in $colNames) {{
            try {{
                $cols[$n] = (Invoke-Retry {{ $wb.Names.Item($n).RefersToRange.Column }} $n)
            }} catch {{
                $missing += "$n : $($_.Exception.Message.Split([char]10)[0])"
            }}
        }}
        if ($cols.Count -eq 0) {{
            return @{{ error = "no named range resolved"; missing = $missing }}
        }}
        $anchor = $wb.Names.Item($colNames[0]).RefersToRange
        $sheet = $anchor.Worksheet
        $first = $anchor.Row
        $count = $anchor.Rows.Count
        $rows = @()
        for ($i = 0; $i -lt $count; $i++) {{
            $r = $first + $i
            $row = @{{}}
            foreach ($n in $colNames) {{
                if (-not $cols.ContainsKey($n)) {{ continue }}
                $cell = $sheet.Cells($r, $cols[$n])
                $row[$n] = @{{
                    text  = [string]$cell.Text
                    value = if ($null -eq $cell.Value2) {{ "" }} else {{ [string]$cell.Value2 }}
                }}
            }}
            $rows += $row
        }}
        return @{{
            sheet = $sheet.Name
            first_row = $first
            block_rows = $count
            missing = $missing
            rows = $rows
        }}
    }}

    $result.a3 = Dump-Table @({a3_list})
    $result.a2 = Dump-Table @({a2_list})

    # The readback is what proves the import, so it is complete before the save is
    # attempted. A save that fails is recoverable by hand; a missing readback is not.
    Trace "readback-complete"
    $result.ok = $true

    # -- apply a Purview sensitivity label before saving ---------------------
    # Where the tenant makes labelling mandatory, an unlabelled workbook cannot be saved:
    # Excel raises the "Add sensitivity label" dialog and, if that dialog is answered any
    # way other than by actually applying a label, Save returns **without error having
    # written nothing**. Setting the label through the object model removes the dialog from
    # the path entirely, and can be read back to prove it took.
    Trace "sensitivity-label"
    $result.label_applied = ""
    if ("{label_id}") {{
        try {{
            $sl = $wb.SensitivityLabel
            $existing = $null
            try {{ $existing = $sl.GetLabel() }} catch {{ }}
            if ($existing -and $existing.LabelId) {{
                $result.label_applied = "already labelled ($($existing.LabelId))"
            }} else {{
                $li = $sl.CreateLabelInfo()
                $li.LabelId          = "{label_id}"
                $li.LabelName        = "{label_name}"
                $li.AssignmentMethod = 2
                $li.SiteId           = "{label_site}"
                $li.ActionId         = [guid]::NewGuid().ToString()
                $li.ContentBits      = 0
                $li.IsEnabled        = $true
                $li.SetDate          = (Get-Date).ToString("o")
                $sl.SetLabel($li, $li)
                $check = $sl.GetLabel()
                if ($check -and $check.LabelId) {{
                    $result.label_applied = "{label_name} ($($check.LabelId))"
                }} else {{
                    $result.label_error = "SetLabel did not take: GetLabel is still empty"
                }}
            }}
        }} catch {{
            $result.label_error = $_.Exception.Message.Split([char]10)[0]
        }}
    }}

    Trace "save"
    try {{
        Invoke-Retry {{ {save_block} }} "save"
        $result.saved = $true
    }} catch {{
        $result.saved = $false
        $result.save_error = $_.Exception.Message
    }}
    Trace "done"
}} catch {{
    $result.error = $_.Exception.Message
}} finally {{
    try {{
        $json = $result | ConvertTo-Json -Depth 8 -Compress
        [System.IO.File]::WriteAllText("{dump_win}", $json)
    }} catch {{
        Write-Output "DUMP-WRITE-FAILED: $($_.Exception.Message)"
    }}
    try {{ if ($wb) {{ $wb.Close($false) }} }} catch {{ }}
    try {{ $excel.Quit() }} catch {{ }}
    try {{
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    }} catch {{ }}
}}
if ($result.ok) {{ exit 0 }} else {{ exit 1 }}
'''


def working_copy(workdir_wsl: str, stem: str) -> str:
    """Where this run's working copy goes, refusing to reuse one that already exists.

    Importing twice into one workbook leaves blank rows the utility gives you no way to
    delete, so a reused workbook is unfilable and the failure stays invisible until the
    portal rejects it. Separate from `run_import` so the rule can be exercised on a host
    that has no Excel to reach.
    """
    path = os.path.join(workdir_wsl, f"{stem}.xlsm")
    if os.path.exists(path):
        raise ImportFailed(
            f"{path} already exists and this script will not reuse it.\n"
            "Importing twice into one workbook leaves blank rows the utility cannot "
            "delete, which makes the return unfilable. Delete it or pass a new --name."
        )
    return path


def run_import(utility: str, json_path: str, year: int, workdir_win: str,
               name: str = "", save: bool = True, keep: bool = False,
               timeout: int = 900, verbose: bool = False,
               label: str = DEFAULT_LABEL,
               label_info: dict | None = None) -> tuple[dict, str]:
    """Copy, open, import, dump. Returns (dump, workbook_wsl_path)."""
    # First, because "this cannot work on this machine" is more use than "wslpath: not
    # found" three calls further in.
    host.require()
    if not os.path.exists(utility):
        raise ImportFailed(f"utility not found: {utility}")
    if not os.path.exists(json_path):
        raise ImportFailed(f"JSON not found: {json_path}")

    workdir_wsl = wsl_path(workdir_win)
    os.makedirs(workdir_wsl, exist_ok=True)

    stem = name or f"ITR2_FA_{year}_{time.strftime('%Y%m%d_%H%M%S')}"
    workbook_wsl = working_copy(workdir_wsl, stem)

    print(f"  copying pristine utility -> {os.path.basename(workbook_wsl)}")
    shutil.copy2(utility, workbook_wsl)
    # copy2 preserves the pristine's mtime, so this is the fingerprint of "never written".
    before_save = (os.path.getmtime(workbook_wsl), os.path.getsize(workbook_wsl))

    json_wsl = os.path.join(workdir_wsl, f"{stem}.json")
    shutil.copy2(json_path, json_wsl)
    dump_wsl = os.path.join(workdir_wsl, f"{stem}_dump.json")
    if os.path.exists(dump_wsl):
        os.remove(dump_wsl)

    trace_wsl = os.path.join(workdir_wsl, f"{stem}_trace.log")
    if os.path.exists(trace_wsl):
        os.remove(trace_wsl)
    script = build_driver_ps(
        win_path(workbook_wsl), win_path(json_wsl), win_path(dump_wsl), save,
        trace_win=win_path(trace_wsl), label=label_info,
    )

    # The splash UserForm blocks the COM call that opens the workbook, so the watcher has
    # to already be running in its own process before Excel is launched.
    print("  starting the modal-dialog watcher")
    ready_marker = os.path.join(workdir_wsl, f"{stem}_watcher_up.txt")
    watcher_log = os.path.join(workdir_wsl, f"{stem}_watcher.log")
    for stale in (ready_marker, watcher_log):
        if os.path.exists(stale):
            os.remove(stale)
    # Watcher output goes to a file, not a pipe. powershell.exe buffers a piped stdout, so
    # readiness is signalled by a marker file instead -- waiting on the pipe would block
    # until the watcher exits, which is the opposite of what is wanted.
    log_handle = open(watcher_log, "w", encoding="utf-8")
    watcher = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", win_path(CLEAR_MODALS_SCRIPT), str(max(timeout, 300)),
         win_path(ready_marker), label],
        stdout=log_handle, stderr=subprocess.STDOUT, text=True,
    )

    deadline = time.time() + 45
    while time.time() < deadline and not os.path.exists(ready_marker):
        if watcher.poll() is not None:
            break
        time.sleep(0.25)
    if not os.path.exists(ready_marker):
        watcher.terminate()
        log_handle.close()
        raise ImportFailed(
            "the modal-dialog watcher did not start, so Excel would block forever on "
            f"the utility's splash form.\nWatcher log: {watcher_log}\n"
            f"Run it by hand to see why:\n  powershell.exe -NoProfile "
            f"-ExecutionPolicy Bypass -File {win_path(CLEAR_MODALS_SCRIPT)} 10"
        )
    print("  watcher running")

    try:
        print("  opening Excel and importing (this takes 30-90 seconds)")
        completed = powershell(script, timeout=timeout)
    finally:
        try:
            watcher.terminate()
        except OSError:
            pass
        log_handle.close()

    if verbose and os.path.exists(watcher_log):
        with open(watcher_log, encoding="utf-8", errors="replace") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        if lines:
            print("  --- watcher ---")
            for line in lines:
                print(f"    {line}")

    if verbose:
        if completed.stdout.strip():
            print("  --- powershell stdout ---")
            for line in completed.stdout.splitlines():
                print(f"    {line}")
        if completed.stderr.strip():
            print("  --- powershell stderr ---")
            for line in completed.stderr.splitlines():
                print(f"    {line}")

    if not os.path.exists(dump_wsl):
        raise ImportFailed(
            "the driver produced no cell dump, so nothing can be verified.\n"
            f"{_trace_tail(trace_wsl)}\n"
            f"powershell exit={completed.returncode}\n"
            f"stdout:\n{completed.stdout[-2500:]}\n"
            f"stderr:\n{completed.stderr[-2500:]}"
        )
    with open(dump_wsl, encoding="utf-8-sig") as fh:
        dump = json.load(fh)

    if not keep:
        try:
            os.remove(json_wsl)
        except OSError:
            pass

    if not dump.get("ok"):
        raise ImportFailed(
            f"the import failed at stage '{dump.get('stage')}': "
            f"{dump.get('error', 'no error text')}"
        )

    # Excel reports success for a save it silently abandoned -- which is what mandatory
    # Purview labelling causes. Asking the filesystem is the only trustworthy answer, and
    # without it the workbook left behind is the pristine utility with no Schedule FA in it.
    if save and dump.get("saved") is True:
        after_save = (os.path.getmtime(workbook_wsl), os.path.getsize(workbook_wsl))
        dump["save_persisted"] = after_save != before_save
    return dump, workbook_wsl


def _trace_tail(trace_path: str, lines: int = 12) -> str:
    """The last stages the driver reached, so a hang or crash names its own location."""
    if not os.path.exists(trace_path):
        return "(no stage trace was written -- the driver did not start)"
    with open(trace_path, encoding="utf-8", errors="replace") as fh:
        recorded = [ln for ln in fh.read().splitlines() if ln.strip()]
    if not recorded:
        return "(stage trace is empty)"
    tail = recorded[-lines:]
    return "stages reached:\n  " + "\n  ".join(tail)


def report_save(dump: dict) -> bool:
    """Report the save, and say whether the file on disk actually changed."""
    applied = dump.get("label_applied")
    if applied:
        print(f"  sensitivity label: {applied}")
    if dump.get("label_error"):
        print(f"  sensitivity label NOT applied: {dump['label_error']}")
    if dump.get("saved") is True:
        if dump.get("save_persisted") is False:
            print("  SAVE DID NOT PERSIST: Excel reported success but the file on disk is "
                  "byte-for-byte the pristine utility.")
            print("  This is what mandatory Purview labelling does -- the save is "
                  "abandoned silently. The import and verification below are still an "
                  "accurate account of what was in memory, but there is nothing on disk "
                  "to file. Delete the working copy and re-run.")
            return False
        print("  saved")
        return True
    if dump.get("saved") is False:
        print("  NOT SAVED: " + str(dump.get("save_error", "unknown"))
              .splitlines()[0])
        print("  The import and the verification below are still valid -- they ran "
              "before the save. Open the workbook and save it by hand, accepting the "
              "sensitivity-label prompt if one appears.")
        return False
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a Schedule FA JSON into the ITD Excel utility and verify "
                    "every imported cell against the generated JSON and audit trail.",
    )
    parser.add_argument("--json", required=True, help="Schedule FA JSON from `itr-prep build`")
    parser.add_argument("--utility", required=True,
                        help="path to the PRISTINE .xlsm utility (never modified)")
    parser.add_argument("--year", type=int, required=True,
                        help="reporting calendar year, used to name the working copy")
    parser.add_argument("--audit", default="",
                        help="audit CSV; defaults to <json stem>_audit.csv")
    parser.add_argument("--workdir", default=DEFAULT_WORKDIR,
                        help=f"Windows folder for the working copy (default "
                             f"{DEFAULT_WORKDIR}). Must be an Excel Trusted Location.")
    parser.add_argument("--name", default="",
                        help="filename stem for the working copy (default is timestamped)")
    parser.add_argument("--label", default=DEFAULT_LABEL,
                        help="Purview sensitivity label to apply on save (default "
                             f"{DEFAULT_LABEL!r}). Managed tenants block Save until a "
                             "label is chosen. Avoid an encrypting label -- the portal "
                             "cannot read the resulting file.")
    parser.add_argument("--no-save", action="store_true",
                        help="import and verify but do not save (for testing)")
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    # Before anything reads a file or launches a shell. Everything below this line
    # assumes a Windows Excel is reachable, and on a Mac it is not.
    try:
        host.require()
    except host.UnsupportedHost as exc:
        print(f"\nCANNOT IMPORT ON THIS HOST\n\n{exc}\n")
        return 2

    audit = args.audit
    if not audit:
        candidate = f"{os.path.splitext(args.json)[0]}_audit.csv"
        audit = candidate if os.path.exists(candidate) else ""

    print("=" * 78)
    print(f"SCRIPTED IMPORT -- calendar {args.year}")
    print("=" * 78)
    print(f"  utility  {args.utility}")
    print(f"  json     {args.json}")
    print(f"  audit    {audit or '(none found -- cross-check skipped)'}")

    label_info = resolve_sensitivity_label(args.label)
    if label_info.get("missing"):
        print(f"  label    {args.label!r} is not offered by this tenant's policy.")
        print(f"           offered: {', '.join(label_info['offered'])}")
        print("           Pass --label with one of those. Saving will fail without it "
              "where labelling is mandatory.")
        return 2
    if label_info.get("encrypting"):
        print(f"  label    {label_info['name']!r} encrypts the file, which produces a "
              "workbook the e-filing portal cannot read.")
        print(f"           offered: {', '.join(label_info['offered'])}")
        print("           Pass --label with a non-encrypting label.")
        return 2
    if label_info:
        print(f"  label    {label_info['name']} "
              f"(mandatory={label_info.get('mandatory')}, no encryption)")
    else:
        print("  label    no Purview policy on this machine; none needed")
    print()

    try:
        dump, workbook = run_import(
            args.utility, args.json, args.year, args.workdir,
            name=args.name, save=not args.no_save, keep=args.keep_temp,
            timeout=args.timeout, verbose=args.verbose, label=args.label,
            label_info=label_info,
        )
    except ImportFailed as exc:
        print(f"\nIMPORT FAILED\n\n{exc}\n")
        return 2
    except subprocess.TimeoutExpired:
        print(f"\nIMPORT FAILED\n\nExcel did not finish within {args.timeout}s. A modal "
              "dialog the watcher does not recognise is the usual cause; re-run with "
              "--verbose and watch the Excel window.\n")
        return 2

    print(f"  imported, sheet '{(dump.get('a3') or {}).get('sheet', '?')}'")
    repairs = dump.get("zip_repairs") or []
    if repairs:
        print(f"  repaired {len(repairs)} leading-zero zip code(s) the utility's numeric "
              f"cell format had truncated:")
        for line in repairs:
            print(f"    {line}")
    on_disk = report_save(dump)
    print()

    with open(args.json, encoding="utf-8") as fh:
        expected = json.load(fh)
    report = readback.verify(dump, expected, audit)
    print(readback.render(report, workbook))

    if report.passed and not on_disk and not args.no_save:
        print()
        print("The import verified, but nothing reached the disk, so there is no workbook "
              "to file. Delete the working copy and re-run.")
        return 1

    if report.passed:
        print()
        print(f"Workbook ready: {workbook}")
        print(f"  Windows path: {win_path(workbook)}")
        print()
        print("Schedule FA is done and verified. What is left needs human judgement:")
        print("  1. Schedule CG  -- share-by-share capital gains structure")
        print("  2. Schedule OS  -- dividend income, and FSI/TR for the US tax credit")
        print("  3. Validate every sheet, then Generate JSON, in the utility")
        print("  4. Upload to the portal and e-verify")
        print()
        print("When you save the workbook yourself, or use Generate JSON, the sensitivity-"
              "label prompt will appear again. Pick the least restrictive label: an "
              "encrypting one produces a file the portal cannot read.")
        return 0

    print()
    print("Do not file this workbook. Delete it and re-run against a fresh copy.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
