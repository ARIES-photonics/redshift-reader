#!/bin/bash
# REDSHiFT_Reader.command  --  double-click this to turn a book file into an audiobook.
# Pops up: pick a file, pick a Mac voice, pick a speed. Then it builds the audio and
# opens the folder. No Terminal typing needed. Keep this next to redshift_reader.py.

DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/redshift_reader.py"

if [ ! -f "$PY" ]; then
  osascript -e 'display alert "Missing engine" message "redshift_reader.py must sit in the same folder as this launcher."'
  exit 1
fi

# 1. pick the book file
BOOK=$(osascript <<'EOF'
try
  set f to choose file with prompt "Pick a book file (.md .txt .tex .pdf .epub)" of type {"md","markdown","txt","text","tex","pdf","epub","public.text","public.plain-text","com.adobe.pdf"}
  POSIX path of f
on error
  ""
end try
EOF
)
[ -z "$BOOK" ] && exit 0

# 2. pick a voice from the ones installed on this Mac (name only, locale stripped)
VOICELIST=$(say -v '?' | sed -E 's/ +[a-z]{2,3}[-_][A-Z]{2,3}.*$//' | sed -E 's/ +$//')
VOICE=$(osascript <<EOF
set theList to paragraphs of "$VOICELIST"
try
  set chosen to choose from list theList with prompt "Pick a voice (Premium / Enhanced ones sound best)" default items {item 1 of theList} without multiple selections allowed
  if chosen is false then
    ""
  else
    item 1 of chosen
  end if
on error
  ""
end try
EOF
)
[ -z "$VOICE" ] && exit 0

# 3. pick a speed, 0.5x to 2.5x in 0.1 steps (Octatrack-style, pitch unchanged)
SPEED=$(osascript <<'EOF'
set speeds to {}
repeat with i from 5 to 25
  set end of speeds to ((i / 10) as string) & "x"
end repeat
try
  set chosen to choose from list speeds with prompt "Playback speed (1.0x = natural)" default items {"1.0x"} without multiple selections allowed
  if chosen is false then
    ""
  else
    item 1 of chosen
  end if
on error
  ""
end try
EOF
)
[ -z "$SPEED" ] && exit 0
SPEED_NUM="${SPEED%x}"

# 4. run the engine in a visible Terminal-ish log, then reveal the output folder
echo "Reading: $BOOK"
echo "Voice:   $VOICE"
echo "Speed:   ${SPEED_NUM}x"
echo "--------------------------------------------"

/usr/bin/python3 "$PY" "$BOOK" --voice "$VOICE" --speed "$SPEED_NUM"
STATUS=$?

if [ $STATUS -eq 0 ]; then
  STEM=$(/usr/bin/python3 - "$BOOK" <<'PYEOF'
import os, re, sys
stem = os.path.splitext(os.path.basename(sys.argv[1]))[0]
print(re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "audiobook")
PYEOF
)
  OUTDIR="$(cd "$(dirname "$BOOK")" && pwd)/${STEM}_audio"
  [ -d "$OUTDIR" ] && open "$OUTDIR"
  osascript -e "display notification \"Audiobook ready\" with title \"REDSHiFT Reader\""
else
  osascript -e 'display alert "Something went wrong" message "See the Terminal window for details. Often the fix is feeding the .md or .tex version instead of a PDF/EPUB."'
fi

echo
echo "Done. You can close this window."
