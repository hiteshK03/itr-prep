-- Generic radio-button clicker: find the radio whose FOLLOWING static-text label matches,
-- or by ordinal index among radios. Usage: osascript itd_radio.applescript <match>
-- match can be "1" (first radio) ... or a substring of nearby label text.
on run argv
	set target to item 1 of argv
	tell application "System Events"
		tell process "ITDe-Filing-2026-Setup-1.2.3"
			set frontmost to true
			delay 0.3
			set uiElems to entire contents of front window
			set radioIdx to 0
			set radioCount to 0
			set lastSeenText to ""
			-- build ordered list of radios with their index
			set radios to {}
			repeat with i from 1 to (count of uiElems)
				try
					set e to item i of uiElems
					if (role of e) is "AXRadioButton" then
						set radioCount to radioCount + 1
						set end of radios to i
					end if
				end try
			end repeat
			if target is a number or target is in {"1", "2", "3", "4"} then
				set n to target as integer
				if n >= 1 and n <= radioCount then
					set radioIdx to item n of radios
				end if
			else
				-- find radio followed by matching text within next few elements
				repeat with r from 1 to radioCount
					set ri to item r of radios
					repeat with j from ri to (ri + 4)
						if j <= (count of uiElems) then
							try
								set v to value of (item j of uiElems) as string
								if v contains target then
									set radioIdx to ri
									exit repeat
								end if
							end try
						end if
					end repeat
					if radioIdx > 0 then exit repeat
				end repeat
			end if
			if radioIdx = 0 then return "no radio matched: " & target
			click item radioIdx of uiElems
			return "clicked radio index " & radioIdx & " of " & radioCount
		end tell
	end tell
end run
