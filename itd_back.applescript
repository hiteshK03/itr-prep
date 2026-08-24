-- Go back from the attach screen (element 61 = Back button) to try the next JSON shape.
tell application "System Events"
	tell process "ITDe-Filing-2026-Setup-1.2.3"
		set frontmost to true
		delay 0.3
		set uiElems to entire contents of front window
		-- Back button: unlabeled button at left (~x=196), y~615
		set backIdx to 0
		set bestX to 99999
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
						set y to item 2 of p
						if y > 600 and x < bestX then
							set bestX to x
							set backIdx to i
						end if
					end if
				end if
			end try
		end repeat
		if backIdx > 0 then
			click item backIdx of uiElems
			return "clicked Back at index " & backIdx
		end if
		return "no Back button found"
	end tell
end tell
