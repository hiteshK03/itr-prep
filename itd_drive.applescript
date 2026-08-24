-- ITDe-Filing macOS driver: check sheets, type path into open panel, confirm.
-- Usage: osascript itd_drive.applescript
-- Requires full disk access / accessibility already granted.

on listSheets()
	set out to ""
	tell application "System Events"
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			try
				set sh to sheets of window 1
				set out to out & "sheets=" & (count of sh) & return
				repeat with s in sh
					try
						set out to out & "  sheet: " & (description of s) & return
					on error
						set out to out & "  sheet (no desc)" & return
					end try
					try
						set kids to UI elements of s
						repeat with k in kids
							try
								set out to out & "    " & (role of k) & " [" & (description of k) & "]" & return
							end try
						end repeat
					end try
				end repeat
			on error errMsg
				set out to out & "no sheets: " & errMsg & return
			end try
		end tell
	end tell
	return out
end listSheets

on run
	set result1 to listSheets()
	return result1
end run
