#!/bin/bash
# Watch for files written by the ITDe-Filing app (or anywhere plausible) during the session.
MARKER=/tmp/itd_watch_marker
touch "$MARKER"
OUT=/tmp/itd_newfiles.log
: > "$OUT"
for i in $(seq 1 120); do
  find ~/Library/WebKit/com.wails.ITDe-Filing-2026 \
       ~/Library/Caches/com.wails.ITDe-Filing-2026 \
       ~/Library/Preferences/com.wails.ITDe-Filing-2026.plist \
       ~/Documents ~/Downloads ~/Desktop /tmp 2>/dev/null \
       -type f -newer "$MARKER" 2>/dev/null | grep -viE 'Trash|\.DS_Store' >> "$OUT"
  sleep 2
done
sort -u "$OUT" -o "$OUT"
echo "watch done: $(wc -l < "$OUT") candidate files"
