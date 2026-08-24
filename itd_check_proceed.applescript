tell application "System Events"
	tell process "ITDe-Filing-2026-Setup-1.2.3"
		set uiElems to entire contents of front window
		set e to item 60 of uiElems
		try
			return "proceed enabled=" & (enabled of e as string)
		on error errMsg
			return "err " & errMsg
		end try
	end tell
end tell
