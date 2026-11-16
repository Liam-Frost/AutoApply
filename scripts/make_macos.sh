#!/bin/bash
# Build the macOS package: AutoApply-<version>-macos.dmg with AutoApply.app and a shortcut to Applications
# (open the disk image, drag the app onto Applications - the usual way on a Mac).
#
#   scripts/make_macos.sh [out-dir]          run on macOS (uses sips, iconutil, hdiutil); needs dist-release/AutoApply-<version>.zip
#
# The app is not signed or notarised: the first time, right-click it and choose Open (Gatekeeper asks once).
# Signing and notarising need an Apple Developer ID.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/dist-release}"
VER="$(sed -n 's/^version *= *"\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
ZIP="$OUT/AutoApply-$VER.zip"
[ -f "$ZIP" ] || { echo "missing $ZIP: run scripts/make_release.py first" >&2; exit 1; }
[ "$(uname)" = Darwin ] || { echo "the macOS package is built on macOS" >&2; exit 1; }

STAGE="$(mktemp -d)"
APP="$STAGE/AutoApply.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/scripts/package/macos/AutoApply" "$APP/Contents/MacOS/AutoApply"
chmod +x "$APP/Contents/MacOS/AutoApply"
cp "$ZIP" "$APP/Contents/Resources/app.zip"
cp "$ROOT/scripts/package/common.sh" "$APP/Contents/Resources/common.sh"
# uv for both kinds of Mac, one fixed version checked against its SHA-256 (scripts/fetch_uv.py)
PY="$(command -v python3 || command -v python)"
"$PY" "$ROOT/scripts/fetch_uv.py" macos-aarch64 "$APP/Contents/Resources/uv-aarch64" --cache "$OUT/.cache"
"$PY" "$ROOT/scripts/fetch_uv.py" macos-x86_64 "$APP/Contents/Resources/uv-x86_64" --cache "$OUT/.cache"
printf '%s' "$VER" > "$APP/Contents/Resources/version.txt"

# the icon, from the brand mark
ICONSET="$STAGE/AppIcon.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" "$ROOT/frontend/public/favicon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  sips -z "$d" "$d" "$ROOT/frontend/public/favicon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>AutoApply</string>
  <key>CFBundleDisplayName</key><string>AutoApply</string>
  <key>CFBundleIdentifier</key><string>io.github.autoapply</string>
  <key>CFBundleExecutable</key><string>AutoApply</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VER</string>
  <key>CFBundleVersion</key><string>$VER</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

ln -s /Applications "$STAGE/Applications"
DMG="$OUT/AutoApply-$VER-macos.dmg"
rm -f "$DMG"
hdiutil create -volname "AutoApply $VER" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo "$DMG  $(du -h "$DMG" | cut -f1)  (not signed)"
