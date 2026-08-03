# Clear the modal windows that block COM automation of the ITD utility.
#
# This must run in a SEPARATE process from the automation script, because that script is
# blocked inside the very call each dialog is holding up. Three different windows block it,
# and each needs different handling:
#
#  1. ThunderDFrame -- the VBA UserForm splash shown while the workbook opens. Blocks
#     Workbooks.Open itself.
#  2. #32770 -- a plain Win32 dialog, which is what a VBA MsgBox is. Until it is cleared,
#     every COM call fails with RPC_E_CALL_REJECTED (0x80010001). DisplayAlerts = $false
#     does NOT suppress a MsgBox raised from VBA, so it has to be cleared from outside.
#  3. NUIDialog "Add sensitivity label" -- Microsoft Purview mandatory labelling. On a
#     managed tenant, Save blocks on this until a label is chosen. It cannot be dismissed:
#     Cancel cancels the save, which would lose the import. A label must actually be
#     picked, so this script picks one and clicks Apply.
#
# The label choice matters and is deliberately visible. An encrypting label (usually shown
# with a padlock icon, e.g. "Confidential" or "Restricted") produces a file the income-tax
# portal cannot read. A personal tax return on a corporate machine is not business data, so
# the default is the least restrictive label available.
#
# Usage: clear_modals.ps1 [seconds] [readyMarkerPath] [labelName]
#
# The ready marker is how the caller knows the watcher is up. Waiting on stdout does not
# work: powershell.exe buffers when its output is a pipe, so the startup line may not
# arrive until the process ends -- by which point the caller has been blocked reading it
# for the whole run.

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Collections.Generic;
public class Dlg {
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] static extern int GetClassName(IntPtr h, StringBuilder s, int c);
  [DllImport("user32.dll")] static extern int GetWindowText(IntPtr h, StringBuilder s, int c);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr h, int id);
  delegate bool EnumProc(IntPtr h, IntPtr p);

  public const uint WM_KEYDOWN = 0x0100;
  public const uint WM_KEYUP   = 0x0101;
  public const uint WM_CLOSE   = 0x0010;
  public const uint BM_CLICK   = 0x00F5;
  public const int  VK_RETURN  = 0x0D;

  public class Win {
    public IntPtr Handle; public string Class; public string Title; public uint Pid;
  }

  public static List<Win> Visible() {
    var res = new List<Win>();
    EnumWindows((h,p) => {
      if (!IsWindowVisible(h)) return true;
      var c = new StringBuilder(256); GetClassName(h,c,256);
      var t = new StringBuilder(512); GetWindowText(h,t,512);
      uint pid; GetWindowThreadProcessId(h, out pid);
      res.Add(new Win { Handle = h, Class = c.ToString(), Title = t.ToString(), Pid = pid });
      return true;
    }, IntPtr.Zero);
    return res;
  }
}
'@

$seconds  = if ($args[0]) { [int]$args[0] } else { 300 }
$marker   = $args[1]
$wantLabel = if ($args[2]) { [string]$args[2] } else { "Non-Business" }

$deadline  = (Get-Date).AddSeconds($seconds)
$dismissed = 0
$handled   = @{}

Write-Output "watcher up for ${seconds}s; label preference '$wantLabel'"
if ($marker) {
    try { [System.IO.File]::WriteAllText($marker, "up $(Get-Date -Format o)") }
    catch { Write-Output "could not write ready marker ${marker}: $($_.Exception.Message)" }
}

# Past setup, nothing here is worth dying for: an unexpected error in one iteration must
# not take the watcher down while the automation is still blocked.
$ErrorActionPreference = "Continue"

# Cache which pids are Excel so the per-iteration filter stays cheap.
# Note: a parameter cannot be called $pid -- that is a read-only PowerShell automatic
# variable, and binding it throws, which silently kills the watcher and leaves the
# automation blocked on the very dialog this script exists to clear.
$excelPids = @{}
function Test-ExcelProcess([uint32]$ProcId) {
    if ($excelPids.ContainsKey($ProcId)) { return $excelPids[$ProcId] }
    $isExcel = $false
    try {
        $p = Get-Process -Id $ProcId -ErrorAction Stop
        $isExcel = ($p.ProcessName -ieq "EXCEL")
    } catch { }
    $excelPids[$ProcId] = $isExcel
    return $isExcel
}

$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]

function Get-Descendants($element) {
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        $AE::IsControlElementProperty, $true)
    return $element.FindAll($TS::Descendants, $cond)
}

function Invoke-Element($element) {
    try {
        $p = $element.GetCurrentPattern(
            [System.Windows.Automation.InvokePattern]::Pattern)
        $p.Invoke()
        return $true
    } catch { }
    return $false
}

function Clear-SensitivityLabel($win) {
    # Expand the label dropdown, pick a label, click Apply. Cancelling is not an option:
    # it cancels the save and the imported data is lost with it.
    $el = $AE::FromHandle($win.Handle)
    if ($null -eq $el) { return $false }
    [void][Dlg]::SetForegroundWindow($win.Handle)
    Start-Sleep -Milliseconds 200

    $menuCond = New-Object System.Windows.Automation.PropertyCondition(
        $AE::ControlTypeProperty, $CT::MenuItem)
    $menu = $el.FindFirst($TS::Descendants, $menuCond)
    if ($null -eq $menu) {
        Write-Output "  label dialog has no label menu; leaving it alone"
        return $false
    }
    try {
        $menu.GetCurrentPattern(
            [System.Windows.Automation.ExpandCollapsePattern]::Pattern).Expand()
    } catch {
        Write-Output "  could not open the label list: $($_.Exception.Message)"
        return $false
    }
    Start-Sleep -Milliseconds 800

    $options = @()
    foreach ($k in Get-Descendants $el) {
        if ($k.Current.ControlType -eq $CT::MenuItem -and
            $k.Current.Name -and $k.Current.Name -ne "Select a label") {
            $options += $k
        }
    }
    if ($options.Count -eq 0) {
        Write-Output "  label list is empty"
        return $false
    }
    Write-Output ("  labels offered: " + (($options | ForEach-Object { $_.Current.Name }) -join ", "))

    $chosen = $options | Where-Object { $_.Current.Name -ieq $wantLabel } | Select-Object -First 1
    if ($null -eq $chosen) {
        $chosen = $options | Where-Object { $_.Current.Name -imatch [regex]::Escape($wantLabel) } | Select-Object -First 1
    }
    if ($null -eq $chosen) {
        # Fall back to the first offered label, which is the least restrictive in every
        # tenant layout seen so far. Say so loudly rather than choosing quietly.
        $chosen = $options[0]
        Write-Output "  '$wantLabel' is not offered; falling back to '$($chosen.Current.Name)'"
    }
    if (-not (Invoke-Element $chosen)) {
        Write-Output "  could not select '$($chosen.Current.Name)'"
        return $false
    }
    Write-Output "  applied label '$($chosen.Current.Name)'"
    Start-Sleep -Milliseconds 500

    $apply = $null
    foreach ($k in Get-Descendants $el) {
        if ($k.Current.ControlType -eq $CT::Button -and $k.Current.Name -ieq "Apply") {
            $apply = $k; break
        }
    }
    if ($null -ne $apply) {
        if (Invoke-Element $apply) {
            Write-Output "  clicked Apply"
            return $true
        }
    }
    # Some builds apply the label as soon as it is picked and drop the Apply button.
    Write-Output "  no Apply button to click; assuming the label took effect"
    return $true
}

function Clear-Window($w) {
    [void][Dlg]::SetForegroundWindow($w.Handle)
    Start-Sleep -Milliseconds 120

    # A dialog's default button is control id 1 (IDOK); clicking it is more reliable than
    # a keypress, which can land on whichever control happens to have focus.
    $ok = [Dlg]::GetDlgItem($w.Handle, 1)
    if ($ok -ne [IntPtr]::Zero) {
        [void][Dlg]::PostMessage($ok, [Dlg]::BM_CLICK, [IntPtr]::Zero, [IntPtr]::Zero)
    } else {
        [void][Dlg]::PostMessage($w.Handle, [Dlg]::WM_KEYDOWN, [IntPtr][Dlg]::VK_RETURN, [IntPtr]::Zero)
        [void][Dlg]::PostMessage($w.Handle, [Dlg]::WM_KEYUP,   [IntPtr][Dlg]::VK_RETURN, [IntPtr]::Zero)
    }
    Start-Sleep -Milliseconds 250

    # If it is still there it has no default button; close it outright.
    if ([Dlg]::Visible() | Where-Object { $_.Handle -eq $w.Handle }) {
        [void][Dlg]::PostMessage($w.Handle, [Dlg]::WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero)
    }
}

while ((Get-Date) -lt $deadline) {
    foreach ($w in [Dlg]::Visible()) {
        $isForm  = ($w.Class -eq "ThunderDFrame")
        $isMsgBox = ($w.Class -eq "#32770" -and (Test-ExcelProcess $w.Pid))
        $isLabel = ($w.Class -eq "NUIDialog" -and $w.Title -imatch "sensitivity label")

        if ($isLabel) {
            # Retry a label dialog on later passes if the first attempt did not clear it,
            # but not more than a few times, to avoid fighting a dialog that will not go.
            $key = "label:$($w.Handle)"
            if (-not $handled.ContainsKey($key)) { $handled[$key] = 0 }
            if ($handled[$key] -ge 3) { continue }
            $handled[$key]++
            Write-Output "sensitivity label dialog (hwnd=$($w.Handle)), attempt $($handled[$key])"
            if (Clear-SensitivityLabel $w) { $dismissed++ }
            continue
        }

        if (-not ($isForm -or $isMsgBox)) { continue }
        Clear-Window $w
        $dismissed++
        Write-Output "dismissed [$($w.Class)] '$($w.Title)' (hwnd=$($w.Handle))"
    }
    Start-Sleep -Milliseconds 300
}
Write-Output "watcher finished; handled $dismissed window(s)"
