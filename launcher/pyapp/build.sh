#!/usr/bin/env bash
# Build one click-to-run launcher binary with PyApp (design 4.3 tier 2).
#
#     launcher/pyapp/build.sh [--target <rust triple>] [--out <dir>] [--version <version>]
#
# PyApp is a Rust crate: `cargo install pyapp` compiles a launcher configured entirely by the
# PYAPP_* environment variables in `pyapp.env`. The result is one executable that, on its first
# launch, downloads a python-build-standalone interpreter and installs `astro-canvas` plus both
# packs into it with its embedded uv.
#
# The version comes from the tag when GITHUB_REF_NAME looks like `v1.2.3`, and from
# backend/src/astro_canvas/_version.py otherwise, so the launcher can never advertise a version
# that was never published.
#
# Requirements: a Rust toolchain (`rustup`). Nothing here touches pip (CONTRIBUTING).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$ROOT/launcher/pyapp"
OUT="$ROOT/launcher/dist"
TARGET=""
VERSION=""
PYAPP_VERSION="${PYAPP_VERSION:-latest}"

while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      TARGET="$2"
      shift 2
      ;;
    --out)
      OUT="$2"
      shift 2
      ;;
    --version)
      VERSION="$2"
      shift 2
      ;;
    --pyapp-version)
      PYAPP_VERSION="$2"
      shift 2
      ;;
    -h | --help)
      sed -n '2,18p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

command -v cargo >/dev/null 2>&1 || {
  echo "error: cargo is required (install Rust from https://rustup.rs)" >&2
  exit 1
}

# --- the version -------------------------------------------------------------------------------

if [ -z "$VERSION" ]; then
  case "${GITHUB_REF_NAME:-}" in
    v*) VERSION="${GITHUB_REF_NAME#v}" ;;
    *)
      VERSION="$(sed -n 's/^__version__ *= *"\(.*\)"$/\1/p' \
        "$ROOT/backend/src/astro_canvas/_version.py")"
      ;;
  esac
fi
[ -n "$VERSION" ] || {
  echo "error: could not determine the version" >&2
  exit 1
}

# --- the configuration -------------------------------------------------------------------------

# `pyapp.env` is the single source of truth; everything in it becomes an environment variable.
set -a
# shellcheck source=/dev/null
. "$HERE/pyapp.env"
set +a
export PYAPP_PROJECT_VERSION="$VERSION"

# TestPyPI for a pre-release: its mirror of the dependency tree is incomplete, so PyPI has to
# stay in the list as a fallback index.
if [ -n "${ASTRO_CANVAS_INDEX:-}" ]; then
  export PYAPP_PIP_EXTRA_ARGS="${PYAPP_PIP_EXTRA_ARGS:-} --index ${ASTRO_CANVAS_INDEX} --index-strategy unsafe-best-match"
fi

echo "==> building the launcher for astro-canvas $VERSION"
echo "    python      ${PYAPP_PYTHON_VERSION}"
echo "    entry point ${PYAPP_EXEC_SPEC}"
echo "    extras      ${PYAPP_PIP_EXTRA_ARGS:-none}"
echo "    target      ${TARGET:-host}"

# --- the build ---------------------------------------------------------------------------------

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

install_args=(pyapp --force --root "$STAGE" --no-track)
[ "$PYAPP_VERSION" != "latest" ] && install_args+=(--version "$PYAPP_VERSION")
[ -n "$TARGET" ] && install_args+=(--target "$TARGET")

cargo install "${install_args[@]}"

# --- the artefact ------------------------------------------------------------------------------

mkdir -p "$OUT"
case "${TARGET:-$(rustc -vV | sed -n 's/^host: //p')}" in
  *windows*) suffix=".exe" ;;
  *) suffix="" ;;
esac

built="$STAGE/bin/pyapp$suffix"
[ -f "$built" ] || {
  echo "error: cargo did not produce $built" >&2
  exit 1
}

case "${TARGET:-$(rustc -vV | sed -n 's/^host: //p')}" in
  x86_64-pc-windows-*) name="astro-canvas-launcher-windows-x64.exe" ;;
  aarch64-apple-darwin) name="astro-canvas-launcher-macos-arm64" ;;
  x86_64-apple-darwin) name="astro-canvas-launcher-macos-x64" ;;
  x86_64-unknown-linux-*) name="astro-canvas-launcher-linux-x64" ;;
  aarch64-unknown-linux-*) name="astro-canvas-launcher-linux-arm64" ;;
  *) name="astro-canvas-launcher$suffix" ;;
esac

cp "$built" "$OUT/$name"
chmod +x "$OUT/$name"

echo
echo "wrote $OUT/$name ($(du -h "$OUT/$name" | cut -f1))"
echo "first launch downloads Python ${PYAPP_PYTHON_VERSION} and the wheels; later launches exec directly."
