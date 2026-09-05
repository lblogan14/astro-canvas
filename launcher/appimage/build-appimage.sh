#!/usr/bin/env bash
# Wrap the Linux launcher in an AppImage (design 4.3 tier 2).
#
#     launcher/appimage/build-appimage.sh \
#         --launcher launcher/dist/astro-canvas-launcher-linux-x64 --version 0.1.0a1
#
# An AppImage is a single executable file: `chmod +x` and run it, no package manager and no root.
# It is not sandboxed (research R4 section 7) - it is a wrapper around the same PyApp launcher,
# which downloads Python and the wheels into the user's home on first launch.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_NAME="Astro Canvas"
LAUNCHER=""
VERSION=""
OUT="$ROOT/launcher/dist"
ARCH="${ARCH:-x86_64}"

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
    --arch)
      ARCH="$2"
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

# --- appimagetool ------------------------------------------------------------------------------

TOOL="${APPIMAGETOOL:-}"
if [ -z "$TOOL" ]; then
  TOOL="$(command -v appimagetool || true)"
fi
if [ -z "$TOOL" ]; then
  TOOL="$(mktemp -d)/appimagetool"
  url="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  echo "==> fetching appimagetool"
  curl -fsSL "$url" -o "$TOOL"
  chmod +x "$TOOL"
fi

# --- the AppDir --------------------------------------------------------------------------------

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
APPDIR="$STAGE/AstroCanvas.AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
  "$APPDIR/usr/share/icons/hicolor/256x256/apps"

install -m 755 "$LAUNCHER" "$APPDIR/usr/bin/astro-canvas"

cat >"$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
# Entry point: reuse a running server, else start one and show the splash page.
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/astro-canvas" open --first-run "$@"
APPRUN
chmod 755 "$APPDIR/AppRun"

cat >"$APPDIR/astro-canvas.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Node-based canvas for astronomical data
Exec=astro-canvas open
Icon=astro-canvas
Terminal=false
Categories=Science;Astronomy;Education;
Keywords=astronomy;spectra;FITS;workflow;
StartupNotify=true
DESKTOP
cp "$APPDIR/astro-canvas.desktop" "$APPDIR/usr/share/applications/"

icon="$ROOT/launcher/appimage/astro-canvas.png"
if [ -f "$icon" ]; then
  cp "$icon" "$APPDIR/astro-canvas.png"
  cp "$icon" "$APPDIR/usr/share/icons/hicolor/256x256/apps/astro-canvas.png"
else
  # appimagetool refuses an AppDir without an icon; a 1x1 placeholder keeps the build honest
  # about what is missing instead of failing.
  printf '\211PNG\r\n\032\n' >"$APPDIR/astro-canvas.png"
  echo "note: launcher/appimage/astro-canvas.png is missing; using a placeholder" >&2
fi

# --- the image ---------------------------------------------------------------------------------

mkdir -p "$OUT"
target="$OUT/astro-canvas-$VERSION-$ARCH.AppImage"
rm -f "$target"

echo "==> building $(basename "$target")"
# --appimage-extract-and-run: no FUSE on a CI runner.
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "$target" >/dev/null
chmod +x "$target"

echo
echo "wrote $target ($(du -h "$target" | cut -f1))"
