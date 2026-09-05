#!/usr/bin/env bash
# Smoke test for launcher/install.sh without installing anything from the network.
#
#     launcher/tests/install-smoke.sh
#
# What it checks is the *script*, not PyPI: a stub `uv` on PATH records the arguments it was
# called with, so the assertions are about the requirement, the interpreter, the packs and the
# shortcut - the parts that break silently. The real network install is what the fresh-VM job in
# CI does (`.github/workflows/release.yml`).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/launcher/install.sh"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

pass=0
fail=0

check() { # check <description> <file> <pattern>
  if grep -qF -- "$3" "$2"; then
    echo "  ok   $1"
    pass=$((pass + 1))
  else
    echo "  FAIL $1" >&2
    echo "       expected to find: $3" >&2
    echo "       in:" >&2
    sed 's/^/         /' "$2" >&2
    fail=$((fail + 1))
  fi
}

refute() { # refute <description> <file> <pattern>
  if grep -qF -- "$3" "$2"; then
    echo "  FAIL $1 (found $3)" >&2
    fail=$((fail + 1))
  else
    echo "  ok   $1"
    pass=$((pass + 1))
  fi
}

# --- the stub uv -------------------------------------------------------------------------------

BIN="$STAGE/bin"
TOOLBIN="$STAGE/toolbin"
LOG="$STAGE/uv.log"
mkdir -p "$BIN" "$TOOLBIN"

cat >"$BIN/uv" <<STUB
#!/bin/sh
# Records its arguments; answers the two queries install.sh makes of it.
printf '%s\n' "\$*" >>"$LOG"
case "\$1" in
  --version) echo "uv 0.0.0-stub"; exit 0 ;;
  tool)
    case "\$2" in
      dir) printf '%s\n' "$TOOLBIN"; exit 0 ;;
      install)
        cat >"$TOOLBIN/astro-canvas" <<'EXE'
#!/bin/sh
case "\$1" in
  version) echo "0.0.0-stub" ;;
  doctor) echo "all checks passed" ;;
  *) echo "stub: \$*" ;;
esac
EXE
        chmod +x "$TOOLBIN/astro-canvas"
        exit 0
        ;;
    esac
    ;;
esac
exit 0
STUB
chmod +x "$BIN/uv"

echo "==> install.sh with uv already present"
HOME="$STAGE/home" \
  XDG_DATA_HOME="$STAGE/home/.local/share" \
  PATH="$BIN:$PATH" \
  NO_OPEN=1 \
  ASTRO_CANVAS_VERSION=1.2.3 \
  ASTRO_CANVAS_PACKS="astro-canvas-rbcodes astro-canvas-extra" \
  sh "$SCRIPT" >"$STAGE/out.txt" 2>&1 || {
  echo "install.sh exited non-zero:" >&2
  cat "$STAGE/out.txt" >&2
  exit 1
}

check "installs the pinned version" "$LOG" "tool install astro-canvas==1.2.3"
check "targets Python 3.12" "$LOG" "--python 3.12"
check "brings the rbcodes pack" "$LOG" "--with astro-canvas-rbcodes"
check "passes extra packs through" "$LOG" "--with astro-canvas-extra"
check "runs doctor" "$STAGE/out.txt" "all checks passed"
# The tooling rule: uv only. Any pip at all in the recorded arguments is a failure.
refute "never invokes pip" "$LOG" "pip"

echo "==> the shortcut"
DESKTOP_ENTRY="$STAGE/home/.local/share/applications/astro-canvas.desktop"
case "$(uname -s)" in
  Linux)
    if [ -f "$DESKTOP_ENTRY" ]; then
      check "desktop entry runs \`open\`" "$DESKTOP_ENTRY" "astro-canvas open"
      check "desktop entry is an application" "$DESKTOP_ENTRY" "Type=Application"
      check "desktop entry is categorised" "$DESKTOP_ENTRY" "Categories=Science;Astronomy"
    else
      echo "  FAIL no desktop entry at $DESKTOP_ENTRY" >&2
      fail=$((fail + 1))
    fi
    ;;
  Darwin)
    SHIM="$STAGE/home/Applications/Astro Canvas.app/Contents/MacOS/astro-canvas-open"
    if [ -f "$SHIM" ]; then
      check "app shim runs \`open\`" "$SHIM" "astro-canvas\" open"
    else
      echo "  FAIL no app bundle at $SHIM" >&2
      fail=$((fail + 1))
    fi
    ;;
  *)
    echo "  skip shortcut checks on $(uname -s)"
    ;;
esac

echo "==> a TestPyPI install keeps PyPI as a fallback index"
: >"$LOG"
HOME="$STAGE/home2" \
  XDG_DATA_HOME="$STAGE/home2/.local/share" \
  PATH="$BIN:$PATH" \
  NO_OPEN=1 NO_SHORTCUT=1 \
  ASTRO_CANVAS_INDEX="https://test.pypi.org/simple/" \
  sh "$SCRIPT" >"$STAGE/out2.txt" 2>&1
check "uses the given index" "$LOG" "--index https://test.pypi.org/simple/"
check "allows the fallback index" "$LOG" "--index-strategy unsafe-best-match"

echo "==> uninstall.sh removes the tool and the shortcuts"
: >"$LOG"
HOME="$STAGE/home" \
  XDG_DATA_HOME="$STAGE/home/.local/share" \
  PATH="$BIN:$PATH" \
  sh "$ROOT/launcher/uninstall.sh" >"$STAGE/out3.txt" 2>&1
check "uninstalls the uv tool" "$LOG" "tool uninstall astro-canvas"
if [ -e "$DESKTOP_ENTRY" ]; then
  echo "  FAIL the desktop entry survived the uninstall" >&2
  fail=$((fail + 1))
else
  echo "  ok   the shortcut is gone"
  pass=$((pass + 1))
fi
check "keeps the workspace" "$STAGE/out3.txt" "workspace was left in place"

echo
if [ "$fail" -gt 0 ]; then
  echo "$fail check(s) failed, $pass passed" >&2
  exit 1
fi
echo "$pass checks passed"
