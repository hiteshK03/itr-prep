#!/usr/bin/env python3
"""Import a generated Schedule FA JSON into the ITD's macOS Common Offline Utility, and
verify it landed -- the macOS equivalent of scripts/import_to_utility.py.

The Windows script drives the department's Excel utility through COM; the macOS utility is
a different program (a Wails desktop app) with no COM, so this script drives the app's own
import path through AppleScript Accessibility -- deterministic element scripting, the
macOS analog of COM, not screenshot automation -- and verifies the result by reading back
the upload JSON the utility itself generates, row by row, exactly as the Windows script
reads every cell back after ImportScheduleFA.

Why every part is not optional (same reasoning as the Windows script):

* A **fresh launch** of the utility every time. A draft left over from a previous attempt
  changes what the import does, and the failure mode is invisible.
* **Import via the app's own "Excel/HTML utility JSON" entry point** -- the option the
  department documents for exactly this shape of file -- because that is the code path a
  person would use, and it is the one that validated in testing.
* **Readback verification of every Schedule FA row.** The app's import runs its own
  validation; trusting "Success" alone is exactly the mistake the Windows script exists to
  avoid. The verification compares the utility's re-exported upload JSON against the input
  JSON field by field, for all Table A2 and Table A3 rows.

Usage:
    python scripts/macos_import_to_utility.py --json <complete_return.json> --year 2025

Requires macOS, the department's ITDe-Filing-2026 app in /Applications, and Accessibility
permission for Terminal/System Events. Only the stdlib is used.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request

SPLASH_PROCESS = "ITDe-Filing-2026"
PROCESS = "ITDe-Filing-2026-Setup-1.2.3"
APP_PATH = "/Applications/ITDe-Filing-2026.app"
PORTAL_DOWNLOADS_URL = ("https://www.incometax.gov.in/iec/foportal/downloads/"
                        "income-tax-returns")
# The build the verification kit has actually been run against (docs/MACOS_UTILITY_TEST.md,
# "Test outcome"). The automation presses buttons by position, which is why an untested
# build must not be driven with real data: a moved button is a silent misclick. Bump this
# only after the kit has passed on the new build.
VERIFIED_UTILITY_VERSION = "1.2.3"


def installed_utility_version() -> tuple[str | None, str | None]:
    """(version, main process name) read from the app bundle.

    The main binary is named ``ITDe-Filing-2026-Setup-<version>``; that name is also the
    accessibility process name the rest of this script drives, so deriving both here means
    a new build changes one thing in one place instead of silently mismatching a hardcoded
    constant. Info.plist is useless for this (it says 1.0.0 for every release).
    """
    best_v = None
    best_name = None
    for path in glob.glob(f"{APP_PATH}/Contents/MacOS/ITDe-Filing-2026-Setup-*"):
        m = re.search(r"(\d+\.\d+\.\d+)$", os.path.basename(path))
        if not m:
            continue
        v = m.group(1)
        if best_v is None or _vtuple(v) > _vtuple(best_v):
            best_v = v
            best_name = os.path.basename(path)
    return best_v, best_name


def _vtuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def portal_mac_version() -> str | None:
    """The version of *Utility for MAC* currently published on the portal's downloads
    page, or None if the page is unreachable or its structure changed beyond recognition.
    Stdlib only, on purpose: this check must work in the same environment the rest of the
    script does."""
    req = urllib.request.Request(
        PORTAL_DOWNLOADS_URL,
        headers={"User-Agent": "Mozilla/5.0 (itr-prep macos version check)"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        html = resp.read(4_000_000).decode("utf-8", "replace")
    # The Windows "Utility" block appears first with its own version number, so anchor on
    # the MAC label specifically and take the nearest version after it.
    i = html.find("Utility for MAC")
    if i < 0:
        return None
    m = re.search(r"version\s*(\d+\.\d+\.\d+)", html[i:i + 1200], re.IGNORECASE)
    return m.group(1) if m else None


def report_versions() -> int:
    """Print installed vs portal version. Exit 0 when up to date, 3 when the portal is
    ahead, 1 when the portal could not be read."""
    installed, _ = installed_utility_version()
    print(f"installed : {installed or 'unknown'}")
    try:
        portal = portal_mac_version()
    except Exception as exc:
        print(f"portal    : UNREACHABLE ({exc.__class__.__name__})")
        return 1
    print(f"portal    : {portal or 'UNREADABLE (page structure changed?)'}")
    if portal is None:
        return 1
    if installed is None:
        print("cannot compare: installed version not detected")
        return 1
    if _vtuple(portal) > _vtuple(installed):
        print("A NEWER BUILD IS PUBLISHED. Re-validate before running on real data:")
        print(f"  1. download Utility for MAC {portal} from {PORTAL_DOWNLOADS_URL}")
        print("  2. install it over /Applications/ITDe-Filing-2026.app and clear "
              "quarantine")
        print("  3. re-run the verification kit against the new build:")
        print("       .venv/bin/python scripts/macos_import_to_utility.py \\")
        print("         --json macos-utility-test/out/complete_return_2025.json "
              "--year 2025")
        print("     (regenerate the kit first if its schema is superseded)")
        return 3
    print("up to date")
    return 0


def running_processes() -> list[str]:
    r = subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to get name of every process whose '
         'background only is false and name contains "ITDe"'],
        capture_output=True, text=True, timeout=30)
    return [p.strip() for p in r.stdout.strip().split(",") if p.strip()]


def osa(script: str, timeout: int = 60) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"osascript failed: {r.stderr.strip()}")
    return r.stdout.strip()


def screen_text() -> str:
    return osa('''
tell application "System Events"
  tell process "''' + PROCESS + '''"
    set uiElems to entire contents of front window
    set out to ""
    repeat with e in uiElems
      try
        set v to (value of e as string)
        if v is not "" and v is not "missing value" then set out to out & v & linefeed
      end try
    end repeat
    return out
  end tell
end tell''', timeout=120)


def wait_for(text: str, timeout: float = 45, poll: float = 1.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if text in screen_text():
                return True
        except Exception:
            pass
        time.sleep(poll)
    return False


def fresh_launch() -> None:
    """Kill any running instance and start a pristine one.

    The DMG ships two executables: a small updater (process `ITDe-Filing-2026`) that shows
    the splash, and the real app (`ITDe-Filing-2026-Setup-1.2.3`) that launches after
    Continue. A pristine run means killing both.
    """
    subprocess.run(["osascript", "-e", f'tell application "{PROCESS}" to quit'],
                   capture_output=True)
    subprocess.run(["osascript", "-e", f'tell application "{SPLASH_PROCESS}" to quit'],
                   capture_output=True)
    time.sleep(2)
    subprocess.run(["pkill", "-f", "ITDe-Filing"], capture_output=True)
    time.sleep(2)
    subprocess.run(["open", "-a", APP_PATH], check=True)
    deadline = time.time() + 40
    while time.time() < deadline:
        if SPLASH_PROCESS in running_processes():
            return
        time.sleep(1)
    raise SystemExit("the utility did not reach its splash screen")


def frontmost() -> None:
    osa(f'tell application "System Events" to tell process "{PROCESS}" to set frontmost to true')


def click_splash_continue() -> None:
    """The splash is the updater process; Continue hands off to the main app.

    The updater's webview needs a few seconds to render its Continue button, and a click
    that lands before it is ready is silently swallowed, so click in a loop until the real
    app process exists.
    """
    deadline = time.time() + 120
    while time.time() < deadline:
        if PROCESS in running_processes():
            return
        try:
            osa(f'''
tell application "System Events"
  tell process "{SPLASH_PROCESS}"
    set frontmost to true
    delay 0.3
    set uiElems to entire contents of front window
    repeat with e in uiElems
      try
        if (role of e) is "AXButton" and (description of e) is not in {{"close button", "full screen button", "minimize button"}} then
          click e
          exit repeat
        end if
      end try
    end repeat
  end tell
end tell''', timeout=30)
        except Exception:
            pass
        # Give the hand-off time to happen before re-clicking.
        for _ in range(6):
            time.sleep(1)
            if PROCESS in running_processes():
                return
    raise SystemExit("the main utility did not launch after Continue")


def press_rightmost_unlabeled(min_y: int = 0, min_w: int = 0) -> str:
    """Press the rightmost unlabeled enabled button in the bottom action area.

    The window may sit anywhere on screen, so no absolute position is assumed: candidates
    are filtered only by width (real action buttons are wide, window chrome is not) and by
    being enabled. With min_y=0 the whole window is eligible, which matters because action
    buttons can render below the visible fold.
    """
    # Scroll to the bottom first so a below-fold Continue button becomes actionable.
    osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    try
      set uiElems to entire contents of front window
      repeat with e in uiElems
        try
          if (role of e) is "AXScrollBar" then
            set value of e to 1
          end if
        end try
      end repeat
    end try
  end tell
end tell''', timeout=60)
    time.sleep(0.5)
    return osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    set frontmost to true
    delay 0.3
    set uiElems to entire contents of front window
    set idx to 0
    set bestX to 0
    repeat with i from 1 to (count of uiElems)
      try
        set e to item i of uiElems
        if (role of e) is "AXButton" then
          try
            set d to description of e
          on error
            set d to ""
          end try
          if d is "" or d is "missing value" then
            set p to position of e
            set s to size of e
            if enabled of e and (item 2 of p) > {min_y} and (item 1 of s) > {min_w} and (item 1 of p) > bestX then
              set bestX to (item 1 of p)
              set idx to i
            end if
          end if
        end if
      end try
    end repeat
    if idx > 0 then
      perform action "AXPress" of (item idx of uiElems)
      return "pressed"
    end if
    return "none"
  end tell
end tell''', timeout=60)


def answer_no_to_all_radios() -> int:
    """Click the second radio of every yes/no pair (the "No" answer)."""
    out = osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    set frontmost to true
    delay 0.3
    set uiElems to entire contents of front window
    set radioCount to 0
    set clicked to 0
    repeat with i from 1 to (count of uiElems)
      try
        set e to item i of uiElems
        if (role of e) is "AXRadioButton" then
          set radioCount to radioCount + 1
          if radioCount mod 2 is 0 then
            click e
            set clicked to clicked + 1
          end if
        end if
      end try
    end repeat
    return (radioCount as string) & "," & (clicked as string)
  end tell
end tell''', timeout=120)
    return int(out.split(",")[0])


def select_excel_html_import() -> None:
    osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    set frontmost to true
    delay 0.3
    set uiElems to entire contents of front window
    repeat with e in uiElems
      try
        if (role of e) is "AXRadioButton" and (description of e) contains "Excel/HTML" then
          click e
          delay 0.8
        end if
      end try
    end repeat
  end tell
end tell''', timeout=60)


def attach_json(json_path: str) -> None:
    """Press Attach File, drive the native open panel to the JSON, press Open.

    A discard-earlier-details dialog can interpose instead of the panel; when it does,
    confirm it and press Attach File again.
    """
    for _attempt in range(3):
        # Find the Attach File button: the unlabeled button nearest the "Attach file"
        # label. (Strict containment fails by 1px of rendering jitter.)
        attach_result = osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    set frontmost to true
    delay 0.3
    set uiElems to entire contents of front window
    set tx to 0
    set ty to 0
    repeat with e in uiElems
      try
        if (role of e) is "AXStaticText" and (value of e) is "Attach file" then
          set p to position of e
          set tx to (item 1 of p)
          set ty to (item 2 of p)
          exit repeat
        end if
      end try
    end repeat
    if tx = 0 then return "no-label"
    set bestDist to 100000
    set bestIdx to 0
    repeat with i from 1 to (count of uiElems)
      try
        set e to item i of uiElems
        if (role of e) is "AXButton" then
          try
            set d to description of e
          on error
            set d to ""
          end try
          if d is "" or d is "missing value" then
            set p to position of e
            set s to size of e
            set cx to (item 1 of p) + ((item 1 of s) / 2)
            set cy to (item 2 of p) + ((item 2 of s) / 2)
            set dist to (cx - tx) * (cx - tx) + (cy - ty) * (cy - ty)
            if dist < bestDist and (item 1 of s) > 60 and (item 2 of s) > 20 then
              set bestDist to dist
              set bestIdx to i
            end if
          end if
        end if
      end try
    end repeat
    if bestIdx = 0 then return "no-button"
    perform action "AXPress" of (item bestIdx of uiElems)
    return "clicked"
  end tell
end tell''', timeout=60)
        if attach_result == "no-label":
            raise SystemExit("the Attach file label is not on screen; not on the attach step")
        # Wait for either the open panel or the discard dialog.
        for _ in range(20):
            try:
                if osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    return (count of sheets of window 1) as string
  end tell
end tell''', timeout=30) != "0":
                    break
            except Exception:
                pass
            if "discarded" in screen_text():
                dismiss_discard_dialog()
                break
            time.sleep(0.5)
        try:
            if osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    return (count of sheets of window 1) as string
  end tell
end tell''', timeout=30) == "0":
                # No panel: either a dialog consumed the attempt, or the click landed early.
                time.sleep(1)
                continue
        except Exception:
            continue
        osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    keystroke "g" using {{command down, shift down}}
    delay 1.5
    keystroke "{json_path}"
    delay 0.5
    key code 36
    delay 2.5
    set sh to sheet 1 of window 1
    set elems to entire contents of sh
    set openIdx to 0
    set bestX to 0
    repeat with i from 1 to (count of elems)
      try
        set e to item i of elems
        if (role of e) is "AXButton" then
          try
            set d to description of e
          on error
            set d to ""
          end try
          if d is "" or d is "missing value" or d is "button" then
            set p to position of e
            if (item 2 of p) > 550 and (item 1 of p) > bestX then
              set bestX to (item 1 of p)
              set openIdx to i
            end if
          end if
        end if
      end try
    end repeat
    if openIdx = 0 then error "Open button not found in panel"
    perform action "AXPress" of (item openIdx of elems)
    return "attached"
  end tell
end tell''', timeout=120)
        return
    raise SystemExit("the open panel never appeared after Attach File")


def close_popup_if_any() -> None:
    osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    set uiElems to entire contents of front window
    repeat with e in uiElems
      try
        if (description of e) is "Pop-up close" then
          perform action "AXPress" of e
          exit repeat
        end if
      end try
    end repeat
  end tell
end tell''', timeout=60)


def press_button_by_description(substring: str) -> bool:
    """Press the first enabled button whose accessibility description contains the
    substring. The utility labels some buttons with raw i18n keys (for example the PDF
    preview's `common.buttons.download_form_itr`), so description matching is the reliable
    handle for them."""
    out = osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    set frontmost to true
    delay 0.3
    set uiElems to entire contents of front window
    repeat with e in uiElems
      try
        if (role of e) is "AXButton" and enabled of e then
          try
            set d to description of e
            if d is not "missing value" and d contains "{substring}" then
              perform action "AXPress" of e
              return "pressed:" & d
            end if
          end try
        end if
      end try
    end repeat
    return "none"
  end tell
end tell''', timeout=60)
    return out.startswith("pressed:")


def press_labeled_button(substrings: tuple[str, ...]) -> bool:
    """Press the first enabled button whose visible text or description matches any
    substring (case-insensitive; AppleScript string comparison is case-insensitive by
    default). Returns True if a button was pressed."""
    needle_literal = ", ".join('"' + s.lower() + '"' for s in substrings)
    out = osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    set frontmost to true
    delay 0.3
    set uiElems to entire contents of front window
    set needles to {{{needle_literal}}}
    repeat with e in uiElems
      try
        if (role of e) is "AXButton" and enabled of e then
          set label to ""
          try
            set label to value of e as string
          end try
          if label is "missing value" then set label to ""
          try
            set label to label & ((value of static texts of e) as string)
          end try
          try
            set d to description of e
            if d is not "missing value" then set label to label & " " & d
          end try
          repeat with n in needles
            if label contains (n as string) then
              perform action "AXPress" of e
              return "pressed:" & label
            end if
          end repeat
        end if
      end try
    end repeat
    return "none"
  end tell
end tell''', timeout=90)
    return out.startswith("pressed:")


def press_download_json_button() -> bool:
    """Press the Internal Validation screen's Download JSON button by position.

    The webview renders button labels onto its canvas, so these buttons carry no value,
    description or text children in the accessibility tree — label matching can never see
    them. Position is stable instead. The template is: Back (float-left), then Preview
    (*ngIf validationSuccesful, iconsAfter) and Download JSON, both floatRight; CSS floats
    the DOM-first element furthest right, so visually right-to-left they read Preview,
    Download JSON. Hence Download JSON is the SECOND-from-left of the wide bottom buttons:
    exclude Back (the smallest x) and press the next-smallest x. If Preview is hidden the
    same rule lands on Download JSON as the only remaining wide button.
    """
    out = osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    set frontmost to true
    delay 0.3
    set elems to entire contents of front window
    set minX to 100000
    set minIdx to 0
    set secondX to 100000
    set secondIdx to 0
    repeat with i from 1 to (count of elems)
      try
        set e to item i of elems
        if (role of e) is "AXButton" then
          set d to ""
          try
            set d to description of e
          end try
          if d is "" or d is "missing value" then
            set p to position of e
            set s to size of e
            if enabled of e and (item 1 of s) > 80 and (item 2 of p) > 400 then
              set x to (item 1 of p)
              if x < minX then
                set minX to x
                set minIdx to i
              else if x < secondX then
                set secondX to x
                set secondIdx to i
              end if
            end if
          end if
        end if
      end try
    end repeat
    if secondIdx > 0 then
      perform action "AXPress" of (item secondIdx of elems)
      return "pressed-second:" & secondX
    else if minIdx > 0 then
      perform action "AXPress" of (item minIdx of elems)
      return "pressed-only:" & minX
    end if
    return "none"
  end tell
end tell''', timeout=60)
    return out.startswith("pressed")


def dismiss_discard_dialog() -> str:
    """If the utility asks to discard details saved earlier for the same PAN/AY, confirm.

    The dialog's Yes/No buttons carry no accessibility labels, so the confirm button is
    found by walking up from the static text "Yes" to its enclosing button, falling back
    to the rightmost unlabeled button inside the dialog box.
    """
    if "discarded" not in screen_text():
        return "absent"
    out = osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    set frontmost to true
    delay 0.3
    set uiElems to entire contents of front window
    repeat with i from 1 to (count of uiElems)
      try
        set e to item i of uiElems
        if (role of e) is "AXStaticText" and (value of e) is "Yes" then
          set p to e
          repeat 4 times
            try
              set p to value of attribute "AXParent" of p
            on error
              exit repeat
            end try
            try
              if (role of p) is "AXButton" then
                perform action "AXPress" of p
                return "pressed-yes"
              end if
            end try
          end repeat
        end if
      end try
    end repeat
    -- fallback: rightmost unlabeled button in the dialog (bottom-right of screen)
    set bestX to 0
    set idx to 0
    repeat with i from 1 to (count of uiElems)
      try
        set e to item i of uiElems
        if (role of e) is "AXButton" then
          try
            set d to description of e
          on error
            set d to ""
          end try
          if d is "" or d is "missing value" then
            set p to position of e
            set s to size of e
            if (item 2 of p) > 550 and (item 2 of s) < 60 and (item 1 of s) < 120 and (item 1 of p) > bestX then
              set bestX to (item 1 of p)
              set idx to i
            end if
          end if
        end if
      end try
    end repeat
    if idx > 0 then
      perform action "AXPress" of (item idx of uiElems)
      return "pressed-fallback"
    end if
    return "none"
  end tell
end tell''', timeout=90)
    time.sleep(4)
    return out


def tick_declaration() -> None:
    osa(f'''
tell application "System Events"
  tell process "{PROCESS}"
    set frontmost to true
    set uiElems to entire contents of front window
    repeat with e in uiElems
      try
        if (role of e) is "AXCheckBox" and (description of e) is "Declaration" then
          click e
          exit repeat
        end if
      end try
    end repeat
  end tell
end tell''', timeout=60)


def find_export(pan: str, ay_start: str, started_after: float) -> str | None:
    """The utility names its upload JSON <PAN>_upload_<AY>-<AY+1><timestamp>.json."""
    patterns = [
        os.path.expanduser(f"~/Downloads/{pan}_upload_*.json"),
        os.path.expanduser(f"~/Documents/{pan}_upload_*.json"),
        os.path.expanduser(f"~/Desktop/{pan}_upload_*.json"),
    ]
    candidates = []
    for pat in patterns:
        candidates.extend(glob.glob(pat))
    candidates = [c for c in candidates if os.path.getmtime(c) >= started_after]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def readback(input_json: str, export_json: str) -> int:
    """Field-by-field comparison of Schedule FA between input and the utility's export.

    The macOS analog of the Windows script's cell-by-cell readback: the utility's importer
    can reshape or drop rows (its Excel sibling demonstrably does), so the exported upload
    JSON is compared against what we sent, for every Table A2 and A3 row.
    """
    with open(input_json, encoding="utf-8") as fh:
        sent = json.load(fh)["ITR"]["ITR2"]["ScheduleFA"]
    with open(export_json, encoding="utf-8") as fh:
        got_doc = json.load(fh)
    itr2 = got_doc["ITR"]["ITR2"]
    got = itr2.get("ScheduleFA")
    problems: list[str] = []
    if got is None:
        print("FAIL  the utility's export contains no Schedule FA at all")
        return 1

    def rows(table: str, sent_fa: dict, got_fa: dict) -> tuple[list, list]:
        return sent_fa.get(table, []) or [], got_fa.get(table, []) or []

    for table in ("DtlsForeignEquityDebtInterest", "DtlsForeignCustodialAcc",
                  "DtlsForeignBankAccount", "DtlsForeignImmovableProperty",
                  "DtlsForeignTrust", "DtlsOthAssetsInForeign"):
        sent_rows, got_rows = rows(table, sent, got)
        if not sent_rows and not got_rows:
            continue
        if len(sent_rows) != len(got_rows):
            problems.append(f"{table}: sent {len(sent_rows)} row(s), export has "
                            f"{len(got_rows)}")
            continue
        for n, (s, g) in enumerate(zip(sent_rows, got_rows), start=1):
            for key in sorted(set(s) | set(g)):
                sv, gv = s.get(key), g.get(key)
                # the utility may render dates dd/mm/yyyy; normalise both ways
                if sv != gv:
                    if isinstance(sv, str) and isinstance(gv, str):
                        if sv.replace("-", "") == gv.replace("/", "").replace("-", ""):
                            continue
                        # dd/mm/yyyy vs yyyy-mm-dd
                        parts = gv.split("/")
                        if len(parts) == 3 and f"{parts[2]}-{parts[1]}-{parts[0]}" == sv:
                            continue
                    problems.append(f"{table} row {n}, {key}: sent {sv!r}, export {gv!r}")
    if problems:
        print(f"FAIL  {len(problems)} read-back difference(s):")
        for p in problems[:50]:
            print("  -", p)
        if len(problems) > 50:
            print(f"  ... and {len(problems) - 50} more")
        return 1
    a3 = len(sent.get("DtlsForeignEquityDebtInterest") or [])
    a2 = len(sent.get("DtlsForeignCustodialAcc") or [])
    print(f"ok    Schedule FA verified field by field: Table A3 {a3} row(s), "
          f"Table A2 {a2} row(s), every value identical")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", help="complete-return JSON (build --merge-into)")
    ap.add_argument("--year", type=int, help="reporting calendar year, e.g. 2025")
    ap.add_argument("--keep-open", action="store_true", help="leave the utility open afterwards")
    ap.add_argument("--check-version", action="store_true",
                    help="only report installed vs portal utility version and exit")
    ap.add_argument("--force", action="store_true",
                    help="run even on a build the verification kit has not passed on "
                         "(you have re-validated it yourself)")
    args = ap.parse_args()

    if sys.platform != "darwin":
        print("this script only runs on macOS", file=sys.stderr)
        return 2

    if args.check_version:
        return report_versions()

    if not args.json or args.year is None:
        print("error: --json and --year are required (unless using --check-version)",
              file=sys.stderr)
        return 2

    if not os.path.exists(APP_PATH):
        print(f"utility not found at {APP_PATH}; install the department's "
              f"Common Offline Utility first", file=sys.stderr)
        return 2
    if not os.path.exists(args.json):
        print(f"no such file: {args.json}", file=sys.stderr)
        return 2

    # --- version gate ---------------------------------------------------------------
    global PROCESS
    installed, proc_name = installed_utility_version()
    if installed is None or proc_name is None:
        print(f"cannot detect the installed utility version under {APP_PATH}/Contents/MacOS",
              file=sys.stderr)
        return 2
    PROCESS = proc_name  # accessibility process name matches the installed binary

    try:
        portal = portal_mac_version()
    except Exception as exc:
        portal = None
        print(f"note: portal version check failed ({exc.__class__.__name__}); "
              f"continuing with the installed build", file=sys.stderr)

    print(f"utility installed : {installed}")
    print(f"utility on portal : {portal or 'unreadable'}")

    if portal is not None and _vtuple(portal) > _vtuple(installed):
        print(f"WARNING: the portal publishes {portal}; {installed} is installed. Old "
              f"builds stay valid, but fetch {portal} and re-validate before relying on "
              f"this further (see docs/MACOS_UTILITY_TEST.md).", file=sys.stderr)

    if installed != VERIFIED_UTILITY_VERSION:
        msg = (f"the installed build is {installed}, but the verification kit has only "
               f"been run against {VERIFIED_UTILITY_VERSION}. This automation presses "
               f"buttons by POSITION, so an untested build can misclick silently. Either "
               f"re-run the kit on {installed} (it is the run you are about to do, with "
               f"--force), or install {VERIFIED_UTILITY_VERSION} again.")
        if args.force:
            print(f"proceeding with unverified build {installed} because of --force",
                  file=sys.stderr)
        else:
            print(msg, file=sys.stderr)
            return 3
    # --- end version gate -----------------------------------------------------------

    with open(args.json, encoding="utf-8") as fh:
        doc = json.load(fh)
    pan = doc["ITR"]["ITR2"]["PartA_GEN1"]["PersonalInfo"]["PAN"]
    ay = args.year + 1

    started = time.time()
    print("1/6 fresh launch of the utility")
    fresh_launch()

    print("2/6 splash -> Home -> ITR selection")
    click_splash_continue()
    if not wait_for("File your tax return", timeout=45):
        raise SystemExit("did not reach the Home screen")
    # Home -> File Return (rightmost unlabeled button). It can sit below the visible fold,
    # and the traffic-light window buttons are excluded by their descriptions, so position
    # filtering stays loose (rightmost wins regardless).
    press_rightmost_unlabeled(min_y=0, min_w=0)
    if not wait_for("select download or import option", timeout=45):
        # If we are already on the attach screen (e.g. a resumed draft skipped ahead),
        # carry on; otherwise fail with diagnostics.
        if not wait_for("Attach file", timeout=10):
            sys.stderr.write("screen state when it failed:\n" + screen_text()[:2500] + "\n")
            raise SystemExit("did not reach the import-option screen")

    print("3/6 select the Excel/HTML utility import option")
    select_excel_html_import()
    press_rightmost_unlabeled()
    if not wait_for("Attach file", timeout=30):
        raise SystemExit("did not reach the attach screen")

    print(f"4/6 attach {os.path.basename(args.json)} through the app's own import path")
    attach_json(os.path.abspath(args.json))
    # The utility may interpose a discard-earlier-details dialog here (or instead of the
    # success banner). Poll for either, dismissing the dialog whenever it appears.
    deadline = time.time() + 60
    ok = False
    while time.time() < deadline:
        text = screen_text()
        if "Imported online downloaded draft JSON file successfully" in text:
            ok = True
            break
        if "discarded" in text:
            dismiss_discard_dialog()
            # After discarding, the app may need the file attached again.
            time.sleep(2)
            if "Attach file" in screen_text() and os.path.basename(args.json) not in screen_text():
                attach_json(os.path.abspath(args.json))
        time.sleep(2)
    if not ok:
        text = screen_text()
        print("the utility did not report a successful import. Screen state:", file=sys.stderr)
        print(text[:2000], file=sys.stderr)
        return 1
    press_rightmost_unlabeled()  # Proceed

    print("5/6 through schedule questions to Verification")
    # The questionnaire is a sequence of yes/no pages; answer No to all until the
    # Return Summary appears. Some pages have no radios, so keep pressing the rightmost
    # action button either way.
    for _ in range(12):
        if "Return Summary" in screen_text():
            break
        answer_no_to_all_radios()
        press_rightmost_unlabeled()
        time.sleep(4)
    if not wait_for("Return Summary", timeout=30):
        raise SystemExit("never reached the Return Summary screen")
    close_popup_if_any()
    time.sleep(1)
    press_rightmost_unlabeled()  # Proceed To Verification
    if not wait_for("Preview and Submit", timeout=40):
        raise SystemExit("did not reach Verification")

    tick_declaration()
    time.sleep(1)
    press_rightmost_unlabeled()  # Generate upload JSON (runs Internal Validation first)

    print("6/6 wait for the utility's own upload JSON and verify every row")
    # The Internal Validation screen shows three buttons: Back, Preview (only rendered
    # when validation passes) and "Download JSON". It is Download JSON that invokes the
    # app's own generateJson() and writes <PAN>_upload_<AY>....json through the native
    # DownloadFile call (with a success toast) — the PDF preview is not part of the path
    # at all. The previous version of this step pressed the rightmost unlabeled button,
    # which is Preview, and walked the run into the preview and on toward the login
    # screen. Also: if validation fails, the screen lists the defects and Download JSON
    # is never the answer — report the defects instead.
    deadline = time.time() + 120
    export = None
    pressed_download_json = False
    while time.time() < deadline:
        export = find_export(pan, f"{ay}", started)
        if export:
            break
        text = screen_text()
        # Never let the run walk into the login/submission path.
        if "Enter your User ID" in text:
            print("reached the login screen; stopping before submission", file=sys.stderr)
            break
        if "Validation successful" in text and not pressed_download_json:
            if press_download_json_button():
                pressed_download_json = True
        # (No proactive failure detection here: the screen's error-table headers are
        # rendered even on a clean validation, so "error in text" is not a signal. If
        # validation genuinely fails, no export appears and the timeout below dumps the
        # screen, which lists the defects.)
        time.sleep(2)
    if not export:
        text = screen_text()
        if "Internal Validation" in text and "error" in text.lower():
            print("the utility's Internal Validation rejected the return:", file=sys.stderr)
        else:
            print("the utility never produced an upload JSON. Screen state:", file=sys.stderr)
        print(text[:3000], file=sys.stderr)
        return 1
    print(f"export produced: {export}")
    rc = readback(args.json, export)
    if not args.keep_open:
        # Terminate the utility after read-back. Quitting ends the session and deletes the
        # app's upload JSON, so this comes only after verification is done. The app
        # ignores `tell application <process name> to quit` (not an app specifier), and
        # its menu structure is not stable enough for a menu-item click, so signal it.
        for proc_name in (PROCESS, SPLASH_PROCESS):
            out = subprocess.run(["pgrep", "-x", proc_name], capture_output=True, text=True)
            for pid in out.stdout.split():
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
    if rc == 0:
        print("\nIMPORT VERIFIED: every Schedule FA row the utility now holds matches the "
              "JSON this tool produced.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
