#!/bin/bash
# Pristine relaunch of the ITD utility and dump of the splash screen.
set -e
osascript -e 'tell application "ITDe-Filing-2026" to quit' 2>/dev/null || true
sleep 2
pkill -f "ITDe-Filing" 2>/dev/null || true
sleep 2
open -a /Applications/ITDe-Filing-2026.app
sleep 8
osascript - <<'APPLESCRIPT'
tell application "System Events"
	tell process "ITDe-Filing-2026"
		set frontmost to true
		delay 1
		set uiElems to entire contents of front window
		set out to "total=" & (count of uiElems) & return
		repeat with e in uiElems
			try
				set v to (value of e as string)
				if v is not "" and v is not "missing value" then set out to out & v & return
			end try
		end repeat
		return out
	end tell
end tell
APPLESCRIPT
