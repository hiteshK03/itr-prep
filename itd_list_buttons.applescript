-- List every button with its descendant static-text label, for the current screen.
tell application "System Events"
	tell process "ITDe-Filing-2026-Setup-1.2.3"
		set uiElems to entire contents of front window
		set out to ""
		repeat with i from 1 to (count of uiElems)
			try
				set e to item i of uiElems
				if (role of e) is "AXButton" then
					set label to ""
					try
						set txts to value of static texts of e
						set label to (txts as string)
					end try
					try
						set p to position of e
						set en to enabled of e
						set out to out & i & " label=[" & label & "] pos=(" & (item 1 of p) & "," & (item 2 of p) & ") enabled=" & (en as string) & return
					end try
				end if
			end try
		end repeat
		return out
	end tell
end tell
