# Install

Four ways in, in order of how much you want to know about Python.

| Tier | You get | You need |
|---|---|---|
| [**Click to run**](#click-to-run) | One file to download and open | Nothing |
| [**One line**](#one-line) | `astro-canvas` on your PATH, plus a shortcut | A terminal |
| [**uvx**](#run-it-without-installing) | A throwaway run | `uv` |
| [**Server**](../deploy/server.md) | A shared install for a group | Docker, a machine |

Whichever you pick, the first launch downloads Python 3.12 and the science stack — numpy,
astropy, pyarrow, scipy and friends, a few hundred megabytes. That happens once. Later launches
start in seconds.

!!! warning "Pre-alpha: installing from TestPyPI"

    Until the first release, the packages live on
    [TestPyPI](https://test.pypi.org/project/astro-canvas/). Every command below therefore needs
    an extra index; the per-OS pages show the exact form. TestPyPI does not mirror the whole
    dependency tree, which is why PyPI stays in the list as a fallback
    (`--index-strategy unsafe-best-match`).

## Click to run

Download the launcher for your machine from the
[latest release](https://github.com/lblogan14/astro-canvas/releases), then follow the page for
your system — each has a different first-launch ritual to get past its gatekeeper:

- [**Windows**](windows.md) — `astro-canvas-<version>-setup.exe`, and what SmartScreen will say.
- [**macOS**](macos.md) — `astro-canvas-<version>-macos-arm64.dmg`, and the right-click-Open step.
- [**Linux**](linux.md) — `astro-canvas-<version>-x86_64.AppImage`, `chmod +x`, run.

The launcher is a [PyApp](https://ofek.dev/pyapp/) binary: it carries no Python of its own but
fetches a private one on first launch and installs the app into it with an embedded
[uv](https://docs.astral.sh/uv/). Nothing is installed system-wide, and nothing else on your
machine is touched.

## One line

=== "macOS and Linux"

    ```sh
    curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.sh | sh
    ```

=== "Windows (PowerShell)"

    ```powershell
    irm https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.ps1 | iex
    ```

The script installs `uv` if you do not have it, runs
`uv tool install astro-canvas --python 3.12 --with astro-canvas-rbcodes`, makes a desktop or
Start-menu shortcut that runs `astro-canvas open`, checks the result with `astro-canvas doctor`
and opens the app.

Options, as environment variables (POSIX) or parameters (PowerShell):

| | What it does |
|---|---|
| `ASTRO_CANVAS_VERSION` / `-Version` | Install an exact version instead of the latest |
| `ASTRO_CANVAS_INDEX` / `-Index` | Use another package index (TestPyPI for a pre-release) |
| `ASTRO_CANVAS_PACKS` / `-Packs` | Packs to install alongside; default `astro-canvas-rbcodes` |
| `NO_SHORTCUT=1` / `-NoShortcut` | Skip the shortcut |
| `NO_OPEN=1` / `-NoOpen` | Do not start the app afterwards |

!!! tip "Read it before you pipe it"

    Piping a script from the internet into a shell is a reasonable thing to be uneasy about.
    Both installers are short and commented:
    [install.sh](https://github.com/lblogan14/astro-canvas/blob/main/launcher/install.sh),
    [install.ps1](https://github.com/lblogan14/astro-canvas/blob/main/launcher/install.ps1).
    Neither needs administrator rights, and neither calls `pip`.

## Run it without installing

If you already have `uv`:

```sh
uvx --with astro-canvas-rbcodes astro-canvas open
```

`uvx` builds a temporary environment, runs the app and throws the environment away afterwards —
useful for a look, wasteful as a habit, because the next run downloads everything again.

## What gets written where

| | |
|---|---|
| **Workspace** | `<Documents>/AstroCanvas` — your workflows, data, results and cache. Change it with `astro-canvas workspace use <path>`. |
| **Config** | `%LOCALAPPDATA%\AstroCanvas` (Windows), `~/Library/Application Support/AstroCanvas` (macOS), `~/.config/AstroCanvas` (Linux) — the access token, the chosen workspace, the registry cache. |
| **The app itself** | `%LOCALAPPDATA%\astro-canvas` (Windows) or uv's tool directory (`uv tool dir`). |

Uninstalling never touches the workspace. See
[upgrading and removing](upgrading.md).

## Check an install

```console
$ astro-canvas doctor
[ok  ] astro-canvas             0.1.0a1 on macOS-15.0-arm64
[ok  ] python                   3.12.14 (/Users/you/.local/share/uv/tools/astro-canvas/bin/python)
[ok  ] bundled interface        7 files, index.html 494 B
[ok  ] uv                       uv 0.11.33 at /Users/you/.local/bin/uv
[ok  ] workspace                /Users/you/Documents/AstroCanvas
[ok  ] disk                     412.8 GB free of 994.7 GB
[ok  ] pack core                0.1.0a1, 28 nodes, 20 types
[ok  ] pack rbcodes             0.1.0a1, 38 nodes, 6 types
[ok  ] qt not imported          no Qt binding in sys.modules
[ok  ] port                     127.0.0.1:8765

all checks passed
```

Paste that into a bug report and most questions are already answered. If something is `FAIL` or
`warn`, [Troubleshooting](../faq.md) covers each line.
