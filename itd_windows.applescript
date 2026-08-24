tell application "System Events"
	tell process "ITDe-Filing-2026-Setup-1.2.3"
		set winNames to name of every window
		set winCount to count of windows
		set out to "windows: " & winCount & " -> " & (winNames as string) & return
		try
			set shCount to count of sheets of window 1
			set out to out & "sheets: " & shCount & return
		on error
			set out to out & "sheets: 0" & return
		end try
		return out
	end tell
end tell
