on run
	set out to ""
	tell application "System Events"
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			set sh to sheet 1 of window 1
			set elems to entire contents of sh
			set out to out & "sheet elements=" & (count of elems) & return
			repeat with i from 1 to (count of elems)
				try
					set e to item i of elems
					set r to role of e
					-- look for selected file rows, table rows, and buttons
					if r is in {"AXRow", "AXStaticText", "AXButton"} then
						try
							set v to value of e as string
						on error
							set v to ""
						end try
						try
							set d to description of e
						on error
							set d to ""
						end try
						if v is not "" or d is not "" then
							set out to out & i & " " & r & " desc=[" & d & "] val=[" & v & "]" & return
						end if
					end if
				end try
			end repeat
			return out
		end tell
	end tell
end run
