-- Attach a JSON file through the native open panel.
-- Usage: osascript itd_attach.applescript <absolute json path>
on run argv
	set jsonPath to item 1 of argv
	tell application "System Events"
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			set frontmost to true
			delay 0.3
			set uiElems to entire contents of front window
			-- find the Attach file AXButton (the real button, y in ~480..520, width ~128)
			set attachIdx to 0
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
							set y to item 2 of p
							set sy to item 2 of s
							if y >= 480 and y <= 520 and sy > 30 and sy < 50 then
								set attachIdx to i
							end if
						end if
					end if
				end try
			end repeat
			if attachIdx = 0 then return "attach button not found"
			perform action "AXPress" of (item attachIdx of uiElems)
			delay 2.5
			-- wait for the sheet
			set tries to 0
			repeat while (count of sheets of window 1) = 0 and tries < 10
				delay 0.5
				set tries to tries + 1
			end repeat
			if (count of sheets of window 1) = 0 then return "open panel never appeared"
			-- Go to folder: Cmd+Shift+G
			keystroke "g" using {command down, shift down}
			delay 1.5
			keystroke jsonPath
			delay 0.5
			key code 36 -- Return
			delay 2.5
			-- click Open: rightmost unlabeled button in the sheet
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
						if d is "" or d is "missing value" then
							set p to position of e
							set x to item 1 of p
							set y to item 2 of p
							if y > 550 and x > bestX then
								set bestX to x
								set openIdx to i
							end if
						end if
					end if
				end try
			end repeat
			if openIdx = 0 then return "open button not found in panel"
			perform action "AXPress" of (item openIdx of elems)
			return "attached"
		end tell
	end tell
end run
