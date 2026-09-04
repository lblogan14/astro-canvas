# Launcher

The two desktop distribution tiers (design §4.3, research R4). Full user-facing instructions:
[docs/install/](../docs/install/).

## Tier 1 — one line in a terminal

```sh
curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.sh | sh
```

```powershell
irm https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.ps1 | iex
```

Install uv if missing → `uv tool install astro-canvas --python 3.12 --with astro-canvas-rbcodes`
→ a shortcut that runs `astro-canvas open` → the browser. `uninstall.sh` / `uninstall.ps1` undo
it; both leave the workspace alone.

| Variable / parameter | Effect |
|---|---|
| `ASTRO_CANVAS_VERSION` / `-Version` | Install an exact version instead of the latest |
| `ASTRO_CANVAS_INDEX` / `-Index` | Another index (TestPyPI for a pre-release; PyPI stays as fallback) |
| `ASTRO_CANVAS_PACKS` / `-Packs` | Packs to install alongside (default `astro-canvas-rbcodes`) |
| `NO_SHORTCUT=1` / `-NoShortcut` | Skip the desktop entry |
| `NO_OPEN=1` / `-NoOpen` | Do not start the app afterwards |

Windows installs into `%LOCALAPPDATA%\astro-canvas`: a venv of compiled scientific wheels under a
deep path runs into the 260-character `MAX_PATH` limit (R4 §7).

## Tier 2 — click to run

[PyApp](https://ofek.dev/pyapp/) builds one executable that downloads a
python-build-standalone interpreter and installs the app with its embedded uv on first launch.
That embedded uv also lands next to the interpreter, which is exactly where
[`manager/uv.py::find_uv`](../backend/src/astro_canvas/manager/uv.py) looks first — so the pack
manager works in a click-to-run install with no configuration.

```sh
launcher/pyapp/build.sh                                  # host target
launcher/pyapp/build.sh --target x86_64-pc-windows-msvc  # cross-compile
```

| Path | What it wraps the binary in |
|---|---|
| `pyapp/pyapp.env` | Every `PYAPP_*` setting, with the reasoning |
| `pyapp/build.sh` | `cargo install pyapp` → `launcher/dist/astro-canvas-launcher-<os>-<arch>` |
| `nsis/astro-canvas.nsi` | Windows installer: per-user, shortcut, uninstaller |
| `dmg/build-dmg.sh` | macOS `.dmg` with drag-to-Applications and an `.app` shim |
| `appimage/build-appimage.sh` | Linux `.AppImage` |

The launcher is signed once and its *payload* updates through
`astro-canvas-launcher self update`, so a new release needs no re-notarisation on macOS and no
fresh SmartScreen reputation on Windows. Signing is env-gated in both wrappers
(`CODESIGN_IDENTITY`, `NOTARY_PROFILE`, and `SIGNPATH_*` in the release workflow); without a
certificate the artefacts are unsigned and the docs say so plainly, with the workarounds.

## Tests

```sh
launcher/tests/install-smoke.sh                                  # POSIX installer
pwsh -File launcher/tests/install-smoke.ps1                      # Windows installer
```

Both drive the real installer against a stub `uv` that records its arguments: no network, and
the assertions are about the requirement, the interpreter, the packs and the shortcut. The
end-to-end network install on a clean runner is the `install` job in
[`.github/workflows/release.yml`](../.github/workflows/release.yml).

Everything Python here goes through `uv`; there is no `pip` in this folder (CONTRIBUTING).
