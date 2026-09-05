# macOS

macOS 11 (Big Sur) or newer, Apple silicon or Intel. Nothing here needs administrator rights.

## Click to run

1. Download the `.dmg` for your machine from the
   [latest release](https://github.com/lblogan14/astro-canvas/releases):
   `astro-canvas-<version>-macos-arm64.dmg` on Apple silicon (M1 and later),
   `…-macos-x64.dmg` on Intel. Not sure? `uname -m` prints `arm64` or `x86_64`.
2. Open it and drag **Astro Canvas** into Applications.
3. **The first open needs a right-click** — see below.

The first launch downloads Python 3.12 and the science packages. A progress page opens in your
browser and swaps itself for the app when the server is ready. Expect several minutes on a first
run and a few seconds afterwards.

## Gatekeeper

The app is not signed with an Apple Developer ID or notarized yet, so a double-click gets you
either *"Astro Canvas cannot be opened because it is from an unidentified developer"* or, on
recent macOS, the more alarming *"Astro Canvas is damaged and can't be opened"*. Neither is
about the file being corrupt: quarantined unsigned apps are simply refused.

**Right-click (or Control-click) the app → Open → Open.** macOS remembers the decision, so this
is once per install.

If that dialog does not offer *Open*, clear the quarantine flag by hand:

```sh
xattr -dr com.apple.quarantine "/Applications/Astro Canvas.app"
```

To check what you downloaded first, the release page publishes SHA-256 checksums:

```sh
shasum -a 256 ~/Downloads/astro-canvas-0.1.0a1-macos-arm64.dmg
```

!!! note "Why it is unsigned"

    Signing and notarizing needs an Apple Developer Program membership ($99/year). The
    build pipeline has the hooks ready (`CODESIGN_IDENTITY`, `NOTARY_PROFILE`) and will use them
    the moment a certificate exists; until then the honest answer is a right-click.

## One line

```sh
curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.sh | sh
```

For the pre-alpha packages on TestPyPI:

```sh
curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.sh \
  | ASTRO_CANVAS_INDEX=https://test.pypi.org/simple/ sh
```

The script installs `uv` if it is missing, installs the app and the rbcodes pack into a private
environment, creates `~/Applications/Astro Canvas.app` and `~/Astro Canvas.command`, and opens
the browser. It does not touch a system Python, Homebrew, or conda.

## Where things live

| | |
|---|---|
| Application (click-to-run) | `/Applications/Astro Canvas.app` |
| Application (one-line) | `~/Applications/Astro Canvas.app`, plus `uv tool dir` |
| Config (token, chosen workspace, registry cache) | `~/Library/Application Support/AstroCanvas` |
| Workspace | `~/Documents/AstroCanvas` |

## Apple silicon and PyQt5

rbcodes' own GUI modules import PyQt5. Astro Canvas never does — Qt is imported lazily inside the
handful of node functions that need a Qt-adjacent code path, and `astro-canvas doctor` checks
that nothing pulled it into the process. PyQt5 does publish `macosx_11_0_arm64` wheels, so it
installs cleanly if a pack does ask for it; no Rosetta, no conda.

## Removing it

Drag the app to the Trash, or:

```sh
curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/uninstall.sh | sh
```

Your workspace is never removed. See [upgrading and removing](upgrading.md).
