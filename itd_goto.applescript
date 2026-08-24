-- In the open panel sheet: press Cmd+Shift+G to open "Go to the folder",
-- type the full JSON path, press Return to navigate, then press the Open button.
on run argv
	set jsonPath to item 1 of argv
	tell application "System Events"
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			set frontmost to true
			delay 0.5
			-- open the Go-to-folder popover
			keystroke "g" using {command down, shift down}
			delay 1.5
			-- type the full path
			keystroke jsonPath
			delay 0.5
			key code 36 -- Return
			delay 2.0
			return "path entered"
		end tell
	end tell
end run
