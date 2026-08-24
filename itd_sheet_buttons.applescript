on run
	set out to ""
	tell application "System Events"
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			set sh to sheet 1 of window 1
			set elems to entire contents of sh
			repeat with i from 1 to (count of elems)
				try
					set e to item i of elems
					if (role of e) is "AXButton" then
						try
							set p to position of e
							set s to size of e
							set px to item 1 of p
							set py to item 2 of p
							set sx to item 1 of s
							set sy to item 2 of s
							try
								set d to description of e
							on error
								set d to ""
							end try
							set out to out & i & " pos=(" & px & "," & py & ") " & sx & "x" & sy & " desc=[" & d & "]" & return
						end try
					end if
				end try
			end repeat
			return out
		end tell
	end tell
end run
