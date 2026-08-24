-- Full probe: pristine relaunch, select Excel/HTML import, attach the complete return,
-- proceed through schedules/questions to Verification, tick declaration, generate upload JSON.
-- Usage: osascript itd_probe_run.applescript <json path>
on run argv
	set jsonPath to item 1 of argv
	set log1 to ""

	tell application "System Events"
		-- Step A: select Excel/HTML option + Continue (assumes we're on the options screen)
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			set frontmost to true
			delay 0.5
			set uiElems to entire contents of front window
			repeat with e in uiElems
				try
					if (role of e) is "AXRadioButton" and (description of e) contains "Excel/HTML" then
						click e
						delay 0.8
					end if
				end try
			end repeat
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
			if contIdx > 0 then click item contIdx of uiElems
		end tell
	end tell

	delay 4

	-- Step B: attach file
	tell application "System Events"
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			set frontmost to true
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
			if attachIdx > 0 then perform action "AXPress" of (item attachIdx of uiElems)
			delay 2.5
			set tries to 0
			repeat while (count of sheets of window 1) = 0 and tries < 12
				delay 0.5
				set tries to tries + 1
			end repeat
			if (count of sheets of window 1) > 0 then
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
				if openIdx > 0 then perform action "AXPress" of (item openIdx of elems)
			end if
		end tell
	end tell

	delay 8

	-- Step C: press Proceed (rightmost enabled unlabeled button below y=600)
	tell application "System Events"
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			set frontmost to true
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
							if enabled of e and (item 2 of p) > 600 and (item 1 of p) > bestX3 then
								set bestX3 to (item 1 of p)
								set procIdx to i
							end if
						end if
					end if
				end try
			end repeat
			if procIdx > 0 then perform action "AXPress" of (item procIdx of uiElems)
		end tell
	end tell

	delay 10

	-- Step D: answer the two questions (opt-out regime = No, then continue)
	tell application "System Events"
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			set frontmost to true
			set uiElems to entire contents of front window
			set radioCount to 0
			repeat with i from 1 to (count of uiElems)
				try
					set e to item i of uiElems
					if (role of e) is "AXRadioButton" then
						set radioCount to radioCount + 1
						if radioCount mod 2 is 0 then click e
					end if
				end try
			end repeat
			delay 0.8
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
							if enabled of e and (item 2 of p) > 600 and (item 1 of p) > bestX then
								set bestX to (item 1 of p)
								set contIdx to i
							end if
						end if
					end if
				end try
			end repeat
			if contIdx > 0 then perform action "AXPress" of (item contIdx of uiElems)
		end tell
	end tell

	delay 6
	return "flow completed through questions"
end run
