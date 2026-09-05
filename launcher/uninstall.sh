#!/usr/bin/env sh
# Remove Astro Canvas from macOS or Linux. Your workspace is never touched.
#
#     sh launcher/uninstall.sh          # remove the tool and the shortcuts
#     PURGE=1 sh launcher/uninstall.sh  # also remove the config folder (token, secret, cache)
#
# The workspace (<Documents>/AstroCanvas by default, or whatever `astro-canvas workspace list`
# shows) holds your workflows and data and is deliberately left alone. Delete it yourself if you
# really mean to.

set -eu

APP_NAME="Astro Canvas"

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

find_uv() {
  have uv && {
    command -v uv
    return 0
  }
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /usr/local/bin/uv /opt/homebrew/bin/uv; do
    [ -x "$candidate" ] && {
      printf '%s' "$candidate"
      return 0
    }
  done
  return 1
}

step "removing the tool"
UV="$(find_uv || true)"
if [ -n "$UV" ]; then
  "$UV" tool uninstall astro-canvas || say "astro-canvas was not installed as a uv tool"
else
  say "uv not found; nothing to uninstall"
fi

step "removing shortcuts"
for path in \
  "${XDG_DATA_HOME:-$HOME/.local/share}/applications/astro-canvas.desktop" \
  "$HOME/Applications/$APP_NAME.app" \
  "$HOME/Astro Canvas.command"; do
  if [ -e "$path" ]; then
    rm -rf "$path"
    say "removed $path"
  fi
done

if [ "${PURGE:-0}" = "1" ]; then
  step "removing the config folder"
  for path in \
    "$HOME/Library/Application Support/AstroCanvas" \
    "${XDG_CONFIG_HOME:-$HOME/.config}/AstroCanvas"; do
    if [ -d "$path" ]; then
      rm -rf "$path"
      say "removed $path"
    fi
  done
fi

step "done"
say "Your workspace was left in place. Remove it by hand if you want it gone."
