-- Select the "Excel/HTML utility" radio option, then click Continue.
tell application "System Events"
	tell process "ITDe-Filing-2026-Setup-1.2.3"
		set frontmost to true
		delay 0.3
		set uiElems to entire contents of front window
		-- 1. select the radio whose description mentions Excel/HTML
		repeat with e in uiElems
			try
				if (role of e) is "AXRadioButton" and (description of e) contains "Excel/HTML" then
					click e
					delay 1
				end if
			end try
		end repeat
		-- 2. click Continue: rightmost unlabeled button
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
						set x to item 1 of p
						if x > bestX then
							set bestX to x
							set contIdx to i
						end if
					end if
				end if
			end try
		end repeat
		if contIdx > 0 then
			click item contIdx of uiElems
			return "continue clicked"
		end if
		return "no continue button"
	end tell
end tell
