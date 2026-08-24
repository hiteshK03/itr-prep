#!/usr/bin/env python3
"""Probe: reset the ITD macOS utility to a pristine state, import the complete-return
JSON through the utility's own Excel/HTML-utility import path (driven by AppleScript
Accessibility -- deterministic, no vision), then dump the app's localStorage to see what
the utility persisted.

This establishes the offline read-back channel for the row-level verification.
"""
from __future__ import annotations

import glob
import os
import sqlite3
import subprocess
import sys
import time

APP_PROCESS = "ITDe-Filing-2026-Setup-1.2.3"
APP_PATH = "/Applications/ITDe-Filing-2026.app"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_STORAGE_GLOB = os.path.expanduser(
    "~/Library/WebKit/com.wails.ITDe-Filing-2026/WebsiteData/Default/*/*/LocalStorage/localstorage.sqlite3"
)


def osa(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        sys.stderr.write(f"osascript error: {r.stderr}\n")
    return r.stdout


def osa_file(path: str, *args: str) -> str:
    r = subprocess.run(["osascript", path, *args], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        sys.stderr.write(f"osascript-file error: {r.stderr}\n")
    return r.stdout


def quit_app() -> None:
    osa(f'''tell application "{APP_PROCESS}" to quit''')
    time.sleep(2)
    subprocess.run(["pkill", "-f", "ITDe-Filing"], capture_output=True)
    time.sleep(1)


def reset_local_storage() -> None:
    for db in glob.glob(LOCAL_STORAGE_GLOB):
        for suffix in ("", "-wal", "-shm"):
            p = db + suffix
            if os.path.exists(p):
                os.remove(p)
                print(f"removed {p}")


def dump_local_storage() -> list[tuple[str, int]]:
    dbs = glob.glob(LOCAL_STORAGE_GLOB)
    rows: list[tuple[str, int]] = []
    for db in dbs:
        # checkpoint any WAL so we read everything
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            cur = con.execute("SELECT key, length(value) FROM ItemTable")
            for k, ln in cur.fetchall():
                rows.append((k, ln))
            con.close()
        except Exception as e:
            sys.stderr.write(f"sqlite read failed for {db}: {e}\n")
    return rows


def main(json_path: str) -> int:
    print("== quit app & reset local storage ==")
    quit_app()
    reset_local_storage()

    print("== relaunch app ==")
    subprocess.run(["open", "-a", APP_PATH])
    time.sleep(8)

    print("== click Continue on splash ==")
    print(osa_file(os.path.join(REPO, "itd_press_named.applescript"), "Continue"))
    time.sleep(5)

    print("== navigate to File Return screen and Continue ==")
    # On the ITR selection screen, press the rightmost unlabeled button (Continue)
    print(osa_file(os.path.join(REPO, "itd_press_rightmost.applescript")))
    time.sleep(5)

    print("== select Excel/HTML import option & Continue ==")
    print(osa_file(os.path.join(REPO, "itd_select_continue.applescript")))
    time.sleep(5)

    print("== attach JSON via open panel ==")
    print(osa_file(os.path.join(REPO, "itd_attach.applescript"), json_path))
    time.sleep(6)

    print("== press Proceed ==")
    print(osa_file(os.path.join(REPO, "itd_press_proceed.applescript")))
    time.sleep(12)

    print("== localStorage after import ==")
    for k, ln in sorted(dump_local_storage()):
        print(f"  {k!r}: {ln} bytes")

    print("== screen text ==")
    out = osa_file(os.path.join(REPO, "itd_dump_text.applescript"))
    sys.stdout.write(out[:3000])
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: macos_probe.py <complete_return.json>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
