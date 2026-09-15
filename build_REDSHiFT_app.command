#!/bin/bash
# build_REDSHiFT_app.command  --  package the app into a standalone REDSHiFT.app
# you can hand to people / sell on Gumroad. Run this ONCE on your Mac.
# Output: dist/REDSHiFT.app  (self-contained; the buyer needs no Python).

cd "$(dirname "$0")" || exit 1
echo "REDSHiFT // building distributable .app ..."

/usr/bin/python3 -m pip install --user pywebview pyinstaller \
  || /usr/bin/python3 -m pip install --user --break-system-packages pywebview pyinstaller \
  || { echo "Could not install build tools. Run: python3 -m pip install --user pywebview pyinstaller"; exit 1; }

# icon: use the prebuilt REDSHiFT.icns (her face). If missing but the 1024 png is here,
# rebuild the icns with macOS's own iconutil so the Dock icon is always correct.
ICON_ARG=()
if [ -f "REDSHiFT.icns" ]; then
  ICON_ARG=(--icon "REDSHiFT.icns")
elif [ -f "REDSHiFT_icon_1024.png" ]; then
  echo "Rebuilding icon with iconutil..."
  rm -rf REDSHiFT.iconset && mkdir REDSHiFT.iconset
  for s in 16 32 64 128 256 512; do
    sips -z $s $s   REDSHiFT_icon_1024.png --out "REDSHiFT.iconset/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) REDSHiFT_icon_1024.png --out "REDSHiFT.iconset/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns REDSHiFT.iconset -o REDSHiFT.icns && ICON_ARG=(--icon "REDSHiFT.icns")
fi

/usr/bin/python3 -m PyInstaller --noconfirm --windowed \
  --name "REDSHiFT" \
  --osx-bundle-identifier "inc.ariesphotonics.redshift.reader" \
  --add-data "nerv_ui.html:." \
  "${ICON_ARG[@]}" \
  app.py

echo
echo "Built: $(pwd)/dist/REDSHiFT.app"
echo "Note: it is UNSIGNED. On another Mac, Gatekeeper will warn. To sell cleanly,"
echo "      sign + notarize with an Apple Developer ID (\$99/yr)."
open dist 2>/dev/null
