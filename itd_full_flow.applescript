-- Full clean flow: select Excel/HTML option -> Continue -> attach complete return ->
-- wait for success -> press Proceed -> wait -> dump all visible text.
on run argv
	set jsonPath to item 1 of argv
	tell application "System Events"
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			set frontmost to true
			delay 0.3

			-- Step 1: select the Excel/HTML radio
			set uiElems to entire contents of front window
			repeat with e in uiElems
				try
					if (role of e) is "AXRadioButton" and (description of e) contains "Excel/HTML" then
						click e
						delay 0.8
					end if
				end try
			end repeat

			-- Step 2: Continue (rightmost unlabeled button)
			set uiElems to entire contents of front window
			set contIdx to 0
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
							if (item 1 of p) > bestX then
								set bestX to (item 1 of p)
								set contIdx to i
							end if
						end if
					end if
				end try
			end repeat
			if contIdx = 0 then return "no continue"
			click item contIdx of uiElems
			delay 4

			-- Step 3: click Attach file button
			set uiElems to entire contents of front window
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
							if (item 2 of p) >= 480 and (item 2 of p) <= 520 and (item 2 of s) > 30 and (item 2 of s) < 50 then
								set attachIdx to i
							end if
						end if
					end if
				end try
			end repeat
			if attachIdx = 0 then return "no attach button"
			perform action "AXPress" of (item attachIdx of uiElems)
			delay 2.5
			set tries to 0
			repeat while (count of sheets of window 1) = 0 and tries < 10
				delay 0.5
				set tries to tries + 1
			end repeat
			if (count of sheets of window 1) = 0 then return "no open panel"

			-- Step 4: go to folder + select + open
			keystroke "g" using {command down, shift down}
			delay 1.5
			keystroke jsonPath
			delay 0.5
			key code 36
			delay 2.5
			set sh to sheet 1 of window 1
			set elems to entire contents of sh
			set openIdx to 0
			set bestX2 to 0
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
							if (item 2 of p) > 550 and (item 1 of p) > bestX2 then
								set bestX2 to (item 1 of p)
								set openIdx to i
							end if
						end if
					end if
				end try
			end repeat
			if openIdx = 0 then return "no open button in panel"
			perform action "AXPress" of (item openIdx of elems)
			delay 8

			-- Step 5: press Proceed (rightmost unlabeled button, enabled)
			set uiElems to entire contents of front window
			set procIdx to 0
			set bestX3 to 0
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
							set en to enabled of e
							if en and (item 1 of p) > bestX3 and (item 2 of p) > 600 then
								set bestX3 to (item 1 of p)
								set procIdx to i
							end if
						end if
					end if
				end try
			end repeat
			if procIdx = 0 then return "no enabled proceed"
			perform action "AXPress" of (item procIdx of uiElems)
			delay 18

			-- Step 6: dump all visible text
			set uiElems to entire contents of front window
			set out to "total=" & (count of uiElems) & return
			repeat with e in uiElems
				try
					set v to (value of e as string)
					if v is not "" and v is not "missing value" then set out to out & (role of e) & ": " & v & return
				end try
			end repeat
			return out
		end tell
	end tell
end run
