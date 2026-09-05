#!/usr/bin/env bash
# Wrap the macOS launcher in a drag-to-Applications disk image (design 4.3 tier 2).
#
#     launcher/dmg/build-dmg.sh --launcher launcher/dist/astro-canvas-launcher-macos-arm64 \
#                               --version 0.1.0a1 [--out launcher/dist]
#
# The `.app` is a shim: its executable runs the PyApp launcher with `open --first-run`, so the
# Dock icon behaves like an app while the actual work stays in the CLI. The Python interpreter and
# the wheels are fetched on first launch, which is what keeps this image ~10 MB instead of ~1 GB.
#
# Signing is optional and env-gated (see docs/install/macos.md):
#   CODESIGN_IDENTITY="Developer ID Application: ... (TEAMID)"   sign the app and the dmg
#   NOTARY_PROFILE=astro-canvas                                  notarize and staple
# Without them the image is unsigned and Gatekeeper needs the documented right-click-Open (or
# `xattr -dr com.apple.quarantine`) - stated plainly in the docs rather than papered over.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_NAME="Astro Canvas"
BUNDLE_ID="dev.astrocanvas.launcher"
LAUNCHER=""
VERSION=""
OUT="$ROOT/launcher/dist"

while [ $# -gt 0 ]; do
  case "$1" in
    --launcher)
      LAUNCHER="$2"
      shift 2
      ;;
    --version)
      VERSION="$2"
      shift 2
      ;;
    --out)
      OUT="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

[ -n "$LAUNCHER" ] || {
  echo "error: --launcher is required" >&2
  exit 2
}
[ -f "$LAUNCHER" ] || {
  echo "error: no launcher at $LAUNCHER" >&2
  exit 1
}
[ -n "$VERSION" ] || VERSION="$(sed -n 's/^__version__ *= *"\(.*\)"$/\1/p' \
  "$ROOT/backend/src/astro_canvas/_version.py")"
[ "$(uname -s)" = "Darwin" ] || {
  echo "error: this script needs macOS (hdiutil, codesign)" >&2
  exit 1
}

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
APP="$STAGE/$APP_NAME.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "==> building $APP_NAME.app $VERSION"

# The real launcher, and a shim that gives it the arguments a double-click should imply.
install -m 755 "$LAUNCHER" "$APP/Contents/MacOS/astro-canvas"
cat >"$APP/Contents/MacOS/AstroCanvas" <<'SHIM'
#!/bin/sh
# The app bundle's entry point: reuse a running server, else start one and show the splash.
here="$(cd "$(dirname "$0")" && pwd)"
exec "$here/astro-canvas" open --first-run
SHIM
chmod 755 "$APP/Contents/MacOS/AstroCanvas"

if [ -f "$ROOT/launcher/dmg/astro-canvas.icns" ]; then
  cp "$ROOT/launcher/dmg/astro-canvas.icns" "$APP/Contents/Resources/astro-canvas.icns"
  icon_key='  <key>CFBundleIconFile</key><string>astro-canvas</string>'
else
  icon_key=''
fi

cat >"$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>AstroCanvas</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
$icon_key
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <!-- The app opens the user's browser; it draws nothing itself. -->
  <key>LSUIElement</key><false/>
</dict>
</plist>
PLIST

# --- signing (optional) ------------------------------------------------------------------------

if [ -n "${CODESIGN_IDENTITY:-}" ]; then
  echo "==> signing the app"
  codesign --force --deep --options runtime --timestamp \
    --sign "$CODESIGN_IDENTITY" "$APP"
  codesign --verify --strict --verbose=2 "$APP"
else
  echo "==> not signing (CODESIGN_IDENTITY is unset)"
fi

# --- the image ---------------------------------------------------------------------------------

case "$(basename "$LAUNCHER")" in
  *arm64*) arch="arm64" ;;
  *x64* | *x86_64*) arch="x64" ;;
  *) arch="$(uname -m)" ;;
esac
DMG="$OUT/astro-canvas-$VERSION-macos-$arch.dmg"
mkdir -p "$OUT"
rm -f "$DMG"

VOLUME="$STAGE/volume"
mkdir -p "$VOLUME"
cp -R "$APP" "$VOLUME/"
ln -s /Applications "$VOLUME/Applications"
cat >"$VOLUME/Read me.txt" <<TXT
Astro Canvas $VERSION

Drag "$APP_NAME" into the Applications folder, then open it.

The first launch downloads Python and the science packages (a few hundred MB) and can take
several minutes; a progress page opens in your browser. Later launches start in seconds.

If macOS says the app "cannot be opened because it is from an unidentified developer",
right-click it and choose Open - or run:

    xattr -dr com.apple.quarantine "/Applications/$APP_NAME.app"

Documentation: https://github.com/lblogan14/astro-canvas
TXT

echo "==> building $(basename "$DMG")"
hdiutil create -volname "$APP_NAME $VERSION" -srcfolder "$VOLUME" \
  -ov -format UDZO -fs HFS+ "$DMG" >/dev/null

if [ -n "${CODESIGN_IDENTITY:-}" ]; then
  codesign --force --sign "$CODESIGN_IDENTITY" --timestamp "$DMG"
fi

if [ -n "${NOTARY_PROFILE:-}" ]; then
  echo "==> notarizing"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
else
  echo "==> not notarizing (NOTARY_PROFILE is unset)"
fi

echo
echo "wrote $DMG ($(du -h "$DMG" | cut -f1))"
