#!/usr/bin/env sh
# Astro Canvas one-line installer for macOS and Linux (design 4.3 tier 1).
#
#     curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.sh | sh
#
# What it does: install uv if it is missing, `uv tool install astro-canvas` on Python 3.12,
# create a desktop entry (Linux) or an app shim (macOS) that runs `astro-canvas open`, and open
# the browser. Nothing here calls pip: uv owns the environment (CONTRIBUTING, tooling rule).
#
# Environment:
#   ASTRO_CANVAS_VERSION   version specifier, e.g. 0.1.0a1 (default: latest)
#   ASTRO_CANVAS_INDEX     package index URL (set to TestPyPI for a pre-release)
#   ASTRO_CANVAS_PACKS     extra packs, space separated (default: astro-canvas-rbcodes)
#   ASTRO_CANVAS_PYTHON    interpreter version to build the tool env with (default: 3.12)
#   NO_SHORTCUT=1          skip the desktop entry
#   NO_OPEN=1              do not open the browser at the end

set -eu

VERSION="${ASTRO_CANVAS_VERSION:-}"
INDEX="${ASTRO_CANVAS_INDEX:-}"
PACKS="${ASTRO_CANVAS_PACKS:-astro-canvas-rbcodes}"
PYTHON="${ASTRO_CANVAS_PYTHON:-3.12}"
APP_NAME="Astro Canvas"

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

have() { command -v "$1" >/dev/null 2>&1; }

# --- uv ----------------------------------------------------------------------------------------

find_uv() {
  if have uv; then
    command -v uv
    return 0
  fi
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /usr/local/bin/uv /opt/homebrew/bin/uv; do
    [ -x "$candidate" ] && {
      printf '%s' "$candidate"
      return 0
    }
  done
  return 1
}

install_uv() {
  step "installing uv"
  if have curl; then
    curl -fsSL https://astral.sh/uv/install.sh | sh
  elif have wget; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    die "neither curl nor wget is available; install uv from https://docs.astral.sh/uv/ first"
  fi
}

UV="$(find_uv || true)"
if [ -z "$UV" ]; then
  install_uv
  UV="$(find_uv || true)"
  [ -n "$UV" ] || die "uv was installed but is not on PATH; open a new shell and re-run this script"
fi
say "uv: $UV ($("$UV" --version))"

# --- the tool ----------------------------------------------------------------------------------

step "installing astro-canvas (Python $PYTHON)"
REQUIREMENT="astro-canvas"
[ -n "$VERSION" ] && REQUIREMENT="astro-canvas==$VERSION"

set -- tool install "$REQUIREMENT" --python "$PYTHON" --force
for pack in $PACKS; do
  set -- "$@" --with "$pack"
done
if [ -n "$INDEX" ]; then
  # A pre-release lives on TestPyPI, whose mirror of the dependency tree is incomplete, so
  # PyPI stays in the list as a fallback index.
  set -- "$@" --index "$INDEX" --index-strategy unsafe-best-match
fi
"$UV" "$@"

BIN_DIR="$("$UV" tool dir --bin 2>/dev/null || printf '%s' "$HOME/.local/bin")"
EXE="$BIN_DIR/astro-canvas"
[ -x "$EXE" ] || die "astro-canvas was installed but $EXE is missing"
say "installed: $("$EXE" version)"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "note: $BIN_DIR is not on your PATH; run \`$UV tool update-shell\` to add it" ;;
esac

# --- the shortcut ------------------------------------------------------------------------------

make_linux_shortcut() {
  applications="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons"
  mkdir -p "$applications" "$icons"
  entry="$applications/astro-canvas.desktop"
  cat >"$entry" <<DESKTOP
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Node-based canvas for astronomical data
Exec=$EXE open
Icon=astro-canvas
Terminal=false
Categories=Science;Astronomy;Education;
Keywords=astronomy;spectra;FITS;workflow;
StartupNotify=true
DESKTOP
  chmod 644 "$entry"
  have update-desktop-database && update-desktop-database "$applications" >/dev/null 2>&1 || true
  say "menu entry: $entry"
}

make_macos_shortcut() {
  # A `.app` whose only job is to run the CLI, so it can live in /Applications and in the Dock.
  bundle="$HOME/Applications/$APP_NAME.app"
  mkdir -p "$bundle/Contents/MacOS"
  cat >"$bundle/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>dev.astrocanvas.launcher</string>
  <key>CFBundleExecutable</key><string>astro-canvas-open</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSBackgroundOnly</key><false/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
PLIST
  launch="$bundle/Contents/MacOS/astro-canvas-open"
  cat >"$launch" <<LAUNCH
#!/bin/sh
exec "$EXE" open
LAUNCH
  chmod 755 "$launch"
  # The double-clickable equivalent for people who prefer a file in their home folder.
  command_file="$HOME/Astro Canvas.command"
  cat >"$command_file" <<COMMAND
#!/bin/sh
exec "$EXE" open
COMMAND
  chmod 755 "$command_file"
  say "app: $bundle"
  say "shortcut: $command_file"
}

if [ "${NO_SHORTCUT:-0}" != "1" ]; then
  step "creating the shortcut"
  case "$(uname -s)" in
    Darwin) make_macos_shortcut ;;
    Linux) make_linux_shortcut ;;
    *) say "no shortcut for $(uname -s); run \`astro-canvas open\` instead" ;;
  esac
fi

# --- first run ---------------------------------------------------------------------------------

step "checking the installation"
"$EXE" doctor || say "note: doctor reported a problem above; the app may still work"

if [ "${NO_OPEN:-0}" != "1" ]; then
  step "starting Astro Canvas"
  say "Close this terminal to stop the server; run \`astro-canvas open\` to start it again."
  exec "$EXE" open
fi

say ""
say "Done. Run \`astro-canvas open\` to start."
