-- Click the Open button (rightmost unlabeled button) in the open-panel sheet.
on run
	tell application "System Events"
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			set frontmost to true
			delay 0.3
			set sh to sheet 1 of window 1
			set elems to entire contents of sh
			set openIdx to 0
			set bestX to 0
			set bestY to 0
			repeat with i from 1 to (count of elems)
				try
					set e to item i of elems
					if (role of e) is "AXButton" then
						try
							set d to description of e
						on error
							set d to ""
						end try
						if d is "" or d is "missing value" then
							set p to position of e
							set x to item 1 of p
							set y to item 2 of p
							-- Open/Cancel are at the bottom of the sheet: highest y, rightmost x
							if y > bestY - 2 then
								if x > bestX then
									set bestX to x
									set bestY to y
									set openIdx to i
								end if
							end if
						end if
					end if
				end try
			end repeat
			if openIdx > 0 then
				click item openIdx of elems
				return "clicked Open (index " & openIdx & ")"
			end if
			return "no Open button found"
		end tell
	end tell
end run
