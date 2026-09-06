# Astro Canvas

[![CI](https://github.com/lblogan14/astro-canvas/actions/workflows/ci.yml/badge.svg)](https://github.com/lblogan14/astro-canvas/actions/workflows/ci.yml)
[![Nightly e2e](https://github.com/lblogan14/astro-canvas/actions/workflows/nightly.yml/badge.svg)](https://github.com/lblogan14/astro-canvas/actions/workflows/nightly.yml)
[![Docs](https://github.com/lblogan14/astro-canvas/actions/workflows/docs.yml/badge.svg)](https://lblogan14.github.io/astro-canvas/)
[![PyPI](https://img.shields.io/pypi/v/astro-canvas)](https://pypi.org/project/astro-canvas/)
[![Python](https://img.shields.io/pypi/pyversions/astro-canvas)](https://pypi.org/project/astro-canvas/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A node-based infinite canvas for exploring astronomical data.**

Load spectra, images and IFU cubes, wire analysis nodes together, watch results appear as you
edit, and share the whole thing — document, data hashes, results and provenance — as a single
file. The science lives in installable **node packs**; the first two ship with the app and
rebuild [rbcodes](https://github.com/rongmon/rbcodes) as headless, web-native nodes.

**[Documentation](https://lblogan14.github.io/astro-canvas/)** ·
**[Install](docs/install/index.md)** ·
**[Quick start](docs/quickstart.md)** ·
**[Coming from rbcodes](docs/migrating/index.md)** ·
**[Changelog](CHANGELOG.md)**

---

## Contents

- [Overview](#overview)
- [Highlights](#highlights)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Node packs](#node-packs)
- [Command line](#command-line)
- [Configuration](#configuration)
- [Deploying a lab server](#deploying-a-lab-server)
- [Architecture](#architecture)
- [Development](#development)
- [Documentation index](#documentation-index)
- [Roadmap and known limitations](#roadmap-and-known-limitations)
- [Contributing](#contributing)
- [Citing](#citing)
- [License](#license)

---

## Overview

Astro Canvas is a desktop-and-server application for interactive astronomical data analysis. It
runs a local FastAPI server with a reactive execution engine, serves a Vue 3 canvas to your
browser, and executes analysis graphs as you edit them.

It is aimed at two audiences at once:

- **Researchers and students** who want the tools from `launch_specgui`, `rb_zfind`,
  `rb_multispec` and `rb_ifuview` without a matplotlib window, a Qt install or a Python session —
  in a browser tab, on a laptop or a shared lab server.
- **Method developers** who want to publish an analysis step as a node that anyone can wire into
  a graph, with the parameter form, the type checking and the preview generated from the function
  signature.

A workflow is a plain JSON document. It can be edited on the canvas, driven as a form or a wizard,
run over a table of targets in batch, executed headlessly on a cluster, or exported as a
reproducible bundle.

**Status: v0.1.0, the first release.** See the [changelog](CHANGELOG.md) for what is in it and the
[release notes](docs/release-notes/v0.1.0.md) for the longer form.

## Highlights

### Reactive execution, not a Run button

Every node carries a content-hash cache key:

```
key = blake3(type | version | canonical_json(params) | fingerprint | upstream keys)
```

Change a parameter and that node and everything downstream is dirty and re-runs. Rename a node,
move it or resize it and **nothing** runs, because the key does not change. Dirtiness is derived
from content, never from edit events.

Cheap nodes run on a thread pool after a 250 ms debounce. Expensive nodes run in a process pool
and wait for an explicit **Run**, as does everything downstream of them; `auto` nodes promote
themselves to expensive once their moving-average runtime passes two seconds. Cancellation is
cooperative for threads and fatal for workers. Partial execution is a first-class case — a graph
with errors still runs the part that compiles.

### Nodes are plain Python functions

A pack registers nodes through `astro_canvas.sdk`, and the entire schema is derived by
introspection:

```python
@node(id="core.math.expr", category="Math", cost="cheap")
def expression(x: Float, expression: str = "x ** 2") -> Float:
    """Evaluate a small arithmetic expression.

    Args:
        x: The value the expression refers to.
        expression: Python arithmetic over ``x``.
    """
```

`x: Float` is an **input port** because `Float` is a registered port type. `expression: str` is a
**param**, rendered as a text widget — and connectable too, because any param can be driven by an
edge instead. The docstring becomes the help text shown in the app: it is part of the contract,
not decoration. Full rules in [docs/formats/node-schema.md](docs/formats/node-schema.md); a
walkthrough in [docs/packs/tutorial.md](docs/packs/tutorial.md).

### One document, four interfaces

Star a parameter, pin a preview, and the same workflow renders as:

| Mode | What it is |
|---|---|
| **Canvas** | The graph — node library, typed connections, inspector, undo/redo, groups, subgraphs |
| **App** | A form of the promoted parameters, grouped |
| **Wizard** | The same parameters as ordered steps, completable with the keyboard alone |
| **Dashboard** | A grid of pinned views with linked selection — drag a range on a spectrum and the table fed by it highlights the matching rows |

The layout lives in the URL, so `/w/<id>/wizard` is a link you can send someone.

### Data in, results out

A **workspace** folder you browse, upload into and drag files from. Loaders for spectra, tables,
images and cubes with instrument-specific readers. Archive fetch nodes for SDSS, SIMBAD, VizieR
and MAST. Previews are decimated server-side — a million-point spectrum previews in about 10 ms —
and the full-size viewer gives you Plotly with server-side resampling, a Canvas2D image view with
WCS readout, and Arrow tables.

### Batch, packs and bundles

- **Batch mode** runs one workflow over a table of rows, with concurrency, continue-on-error and
  cache reuse between rows that share a prefix. `specgui`'s batch CSV imports directly.
- **The pack manager** installs node packs into the shared uv environment, shows the resolution
  diff before touching anything, refuses a plan that conflicts with the app's pins, snapshots the
  environment before every install and rolls back exactly.
- **`.acw` bundles** carry the document, a dependency lock, the hash of every input, the cached
  results, the figures and a per-node provenance record. Import reports missing packs and missing
  inputs rather than guessing. Python code nodes inside an imported bundle stay **quarantined**
  until you have read them.

### Measured, not asserted

| | |
|---|---|
| Pan and zoom over 500 nodes | **56.2 fps** — 93 % of the same interaction over 20 nodes |
| Open a 500-node document, cold cache | 1.45 s |
| Cheap re-run latency, debounces excluded | 35 ms |
| Compile a 500-node document | 4 ms |
| Accessibility | WCAG 2.1 AA, zero serious or critical axe-core violations across every surface |

Methodology and the full tables: [docs/dev/performance.md](docs/dev/performance.md) and
[docs/dev/accessibility.md](docs/dev/accessibility.md).

## Installation

**Requirements.** Nothing, for the click-to-run launchers — they fetch a private Python 3.12 on
first launch. Everything else needs a terminal. Python 3.10–3.13 is supported; 3.12 is the tested
default. Windows 10/11, macOS 11 (Big Sur) or newer on Apple silicon or Intel, and modern 64-bit
Linux are all supported.

### Click to run

Download the launcher for your platform from the
[latest release](https://github.com/lblogan14/astro-canvas/releases):

| Platform | File | Notes |
|---|---|---|
| Windows | `astro-canvas-<version>-setup.exe` | [SmartScreen will warn](docs/install/windows.md#smartscreen) — nothing is code-signed yet |
| macOS | `astro-canvas-<version>-macos-arm64.dmg` (Apple silicon) or `-macos-x64.dmg` (Intel) | [Right-click → Open](docs/install/macos.md) the first time |
| Linux | `astro-canvas-<version>-x86_64.AppImage` | `chmod +x`, then run |

The first launch downloads Python and the science stack — a few hundred megabytes, once. Later
launches start in seconds. Nothing is installed system-wide.

### One line

```sh
# macOS and Linux
curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.sh | sh
```

```powershell
# Windows
irm https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.ps1 | iex
```

Either script installs [uv](https://docs.astral.sh/uv/) if it is missing, installs the app and the
rbcodes pack, creates a desktop or Start-menu shortcut that runs `astro-canvas open`, checks the
result with `astro-canvas doctor` and opens the app. Neither needs administrator rights, and
neither calls `pip`. Both are short and commented — [read them](launcher/) before you pipe them.

### With uv, no install

```sh
uvx --with astro-canvas-rbcodes astro-canvas open
```

Builds a temporary environment, runs the app and discards it afterwards. Useful for a look,
wasteful as a habit.

Per-platform detail, including where files are written and how to upgrade or remove:
[Windows](docs/install/windows.md) · [macOS](docs/install/macos.md) ·
[Linux](docs/install/linux.md) · [upgrading](docs/install/upgrading.md).

## Quick start

Ten minutes, no data of your own required — every template ships with its sample files.

```sh
astro-canvas open
```

That reuses a server that is already running rather than fighting it for the port, and opens a
browser tab on `http://127.0.0.1:8765` authenticated by a token in the URL.

**1. Run a template.** Open the gallery (**Templates** in the toolbar) and pick one. Sample data
is copied into `<workspace>/samples/` on first run, so every template works immediately:

| Template | The rbcodes tool it replaces | What you get |
|---|---|---|
| **Absorption Line Measurement** | `launch_specgui` | An SDSS quasar shifted to the absorber rest frame, a continuum fit, equivalent widths and column densities |
| **Redshift Finder** | `rb_zfind` | A star-forming galaxy cross-correlated against templates, with the χ² curve and the best redshift |
| **Multi-Spectrum Viewer** | `rb_multispec` | Three SDSS spectra stacked, with line identifications at a shared redshift |
| **IFU Cube Explorer** | `rb_ifuview` | A KCWI cube collapsed to a white-light image, an aperture spectrum and moment maps |

Each opens straight into the interface it was designed for — a form, a wizard or a dashboard.
Press **Show graph** to see the nodes underneath.

**2. Change something.** Everything downstream of the edit goes dirty and re-runs after a 250 ms
pause; everything else does not. Rename or move a node and nothing re-runs at all.

**3. Bring your own data.** Drop a FITS file onto the canvas. The server sniffs it and offers the
loader that fits — spectrum, image, cube or table — already wired up.

**4. Run it headlessly.** The same document, no browser:

```sh
astro-canvas run workflow.json --workspace ~/papers/lya
```

Longer walkthrough: [docs/quickstart.md](docs/quickstart.md). The ideas the rest of the docs
assume: [docs/concepts.md](docs/concepts.md).

## Node packs

Two packs ship with the app — 66 nodes and 26 port types between them. Both are ordinary Python
distributions; a pack declares an `astro_canvas.nodes` entry point and the server discovers it.

### `astro-canvas-core` — 28 nodes, 20 port types

| Category | Nodes |
|---|---|
| Data/Load | 4 — spectra, tables, images, cubes, with instrument-specific readers |
| Data/Fetch | 4 — SDSS spectra, SIMBAD resolve, VizieR query, MAST search |
| Data/Save | 3 — spectra, tables, JSON |
| Spectra/Transform | 7 — air↔vacuum, crop, normalise, rebin, smooth, rest frame, velocity |
| Spectra/Measure | 1 — signal-to-noise |
| Plot | 4 — spectrum, image, table, figure export |
| Math, Lists, Utilities | 4 — constants, expressions, collect, markdown notes |
| Code | 1 — the Python **code node**, behind a trust gate |

### `astro-canvas-rbcodes` — 38 nodes, 6 port types

| Category | Nodes | Replaces |
|---|---|---|
| rbcodes/Absorption | 7 | `rb_spec`, `launch_specgui` |
| rbcodes/Continuum | 2 | the specgui continuum fitter |
| rbcodes/Redshift | 10 | `rb_zfind` — five search methods, MARZ and redrock templates |
| rbcodes/Multispec | 7 | `rb_multispec` |
| rbcodes/IFU | 10 | `rb_ifuview` |
| rbcodes/Lines | 2 | the line lists |

Nodes call rbcodes where it imports and a vendored copy of the same kernel where it does not; the
two are checked against each other at `rtol=1e-9`. Six interactive editors (continuum masks,
velocity range, line picker, z-accept, multi-spectrum viewer, aperture drawer) replace the
matplotlib canvases.

Installing more: [docs/guide/packs.md](docs/guide/packs.md). Writing one:
[docs/packs/tutorial.md](docs/packs/tutorial.md) and
[docs/packs/publishing.md](docs/packs/publishing.md).

## Command line

The CLI is the whole app — the desktop shortcut runs `astro-canvas open`, and the Docker image
runs `astro-canvas serve`. Full reference: [docs/cli.md](docs/cli.md).

| Command | What it does |
|---|---|
| `astro-canvas open` | Reuse the running server or start one, then open the browser |
| `astro-canvas serve` | Run the server (`--host`, `--port`, `--auth none\|token\|users`) |
| `astro-canvas run <workflow.json>` | Execute a document headlessly and print a per-node summary |
| `astro-canvas doctor` | Python, uv, packs, disk, ports, Qt — paste into a bug report |
| `astro-canvas workspace list\|use\|new` | Choose the folder the app opens |
| `astro-canvas pack list\|install\|remove\|snapshot\|rollback` | Manage node packs |
| `astro-canvas bundle export\|import` | Read and write `.acw` bundles |

```sh
astro-canvas doctor
astro-canvas workspace new ~/papers/lya
astro-canvas pack install astro-canvas-rbcodes --yes
astro-canvas bundle export wf-123 --out share.acw
astro-canvas run absorption.json --workspace ~/papers/lya --json
```

## Configuration

Every setting is an `ASTRO_CANVAS_*` environment variable or a `serve` flag:

| Group | Variables |
|---|---|
| Server | `HOST`, `PORT`, `WORKSPACE`, `LOG_LEVEL` |
| Auth | `TOKEN`, `AUTH` |
| Cache | `CACHE_MEMORY_MB`, `CACHE_DISK_GB`, `CACHE_MAX_AGE_DAYS` |
| Execution | `MAX_WORKERS`, `PROCESS_POOL`, `RUN_TIMEOUT_S`, `DEBOUNCE_MS`, `AUTO_THRESHOLD_MS` |
| Workspace | `WATCH_WORKSPACE` |

**Where things live.** The **workspace** (`<Documents>/AstroCanvas` by default) holds your
workflows, data, results, bundles and cache; change it with `astro-canvas workspace use <path>`.
The **config directory** (`%LOCALAPPDATA%\AstroCanvas`, `~/Library/Application Support/AstroCanvas`
or `~/.config/AstroCanvas`) holds the access token, the chosen workspace and the registry cache.
Uninstalling never touches the workspace.

**Authentication.** Everything except `/api/health`, `/api/openapi.json` and `/api/docs` requires
a bearer token, generated at startup and printed in the URL. `/ws` is same-origin only. Binding a
non-loopback address refuses to start without `--auth users`, because the one token is shared by
everyone who reaches it and the pack manager installs into the server's own environment.

## Deploying a lab server

Docker Compose: the app behind Caddy, accounts in Postgres, one private workspace per person and a
shared read-only folder. See [docs/deploy/server.md](docs/deploy/server.md).

```sh
cp deploy/.env.example deploy/.env     # POSTGRES_PASSWORD, CANVAS_DOMAIN, ADMIN_EMAILS
docker compose -f deploy/compose.yaml up -d --build
```

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│ Browser                                                       │
│   Vue 3 + Vue Flow behind a CanvasAdapter seam                │
│   canvas · app · wizard · dashboard · generated forms         │
└───────────────────────────────────────────────────────────────┘
        ▲                          ▲
        │ REST /api                │ /ws  JSON + binary frames
        ▼                          ▼
┌───────────────────────────────────────────────────────────────┐
│ FastAPI server — routers, bearer auth, bundled SPA            │
│ ┌───────────────────────────────────────────────────────────┐ │
│ │ Engine   compile → cache keys → schedule → execute        │ │
│ │   thread pool (cheap) · process pool (expensive)          │ │
│ │   memory LRU → content-addressed blobs → SQLite           │ │
│ └───────────────────────────────────────────────────────────┘ │
│ Registry ← astro_canvas.sdk ← node packs (entry points)       │
└───────────────────────────────────────────────────────────────┘
```

**Four distributions**, released together:

| Package | Contents |
|---|---|
| [`astro-canvas`](https://pypi.org/project/astro-canvas/) | The app: engine, server, store, manager, CLI, bundled SPA |
| [`astro-canvas-sdk`](https://pypi.org/project/astro-canvas-sdk/) | `@node`, `@port_type`, specs, registry — deliberately tiny deps; this is what packs depend on |
| [`astro-canvas-core`](https://pypi.org/project/astro-canvas-core/) | The core node pack |
| [`astro-canvas-rbcodes`](https://pypi.org/project/astro-canvas-rbcodes/) | The rbcodes node pack |

`astro_canvas` is a PEP 420 namespace package split across the app and the SDK, so a pack never
has to depend on the application it runs in.

**Repository layout:**

| Path | What it holds |
|---|---|
| [`backend/`](backend/) | FastAPI server, execution engine, store, pack manager, CLI |
| [`backend/sdk/`](backend/sdk/) | The node SDK, published separately |
| [`frontend/`](frontend/) | Vue 3 + Vite SPA, Playwright e2e suite |
| [`packs/core/`](packs/core/), [`packs/rbcodes/`](packs/rbcodes/) | The bundled node packs (uv workspace members) |
| [`launcher/`](launcher/), [`deploy/`](deploy/) | Installers and the Docker Compose lab server |
| [`registry/`](registry/) | The seed pack index |
| [`docs/`](docs/), [`scripts/`](scripts/) | Documentation site and repository checks |

## Development

**Prerequisites:** [uv](https://docs.astral.sh/uv/) 0.5+, Node 22 LTS, [pnpm](https://pnpm.io) 9,
[Task](https://taskfile.dev) 3. Details in [CONTRIBUTING.md](CONTRIBUTING.md).

```sh
git clone https://github.com/lblogan14/astro-canvas
cd astro-canvas
task install                 # uv sync + pnpm install + Playwright chromium
task dev                     # backend :8765 · Vite :5173 (proxies /api and /ws)
task lint typecheck test     # ruff, mypy, oxlint, eslint, vue-tsc, pytest, vitest, playwright
task build                   # SPA → wheel with bundled static/ → backend/dist/*.whl
```

Run the built wheels anywhere:

```sh
uv run --with backend/dist/astro_canvas_sdk-*.whl --with backend/dist/astro_canvas-*.whl \
  astro-canvas serve --open
```

Serve the documentation site with `task docs` (`task docs:build` builds it with `--strict`, so a
broken link fails).

> [!IMPORTANT]
> **Tooling rule.** The frontend is managed **only with pnpm** and the backend **only with uv**.
> Never `npm`, `npx`, `yarn`, `bun`, `pip`, `poetry`, `conda` or a bare `venv`. A `preinstall`
> guard in `frontend/` refuses other package managers, and `task check:tooling` greps the
> Taskfile, workflows, docs and manifests for violations in CI. See
> [CONTRIBUTING.md](CONTRIBUTING.md#tooling-rule-hard-requirement).

## Documentation index

The full site is at **[lblogan14.github.io/astro-canvas](https://lblogan14.github.io/astro-canvas/)**.

**Using it**

- [Quick start](docs/quickstart.md) — ten minutes, with the bundled sample data.
- [Concepts](docs/concepts.md) — nodes, ports, reactivity, cost gating, workspaces, bundles.
- [The canvas](docs/guide/canvas.md) — panels, nodes, connections, every shortcut and gesture.
- [Data](docs/guide/data.md) — the workspace folder, loaders, fetch nodes, previews, the viewer.
- [App modes](docs/guide/modes.md) — promoting parameters, pinning views, App/Wizard/Dashboard.
- [Batch mode](docs/guide/batch.md) — one workflow over a table of rows.
- [Packs](docs/guide/packs.md) and [bundles](docs/guide/bundles.md) — installing, sharing, trust.
- [Code nodes](docs/guide/code-nodes.md) — the Python node, its ports and its restrictions.
- [Command line](docs/cli.md) · [FAQ and troubleshooting](docs/faq.md)

**The rbcodes tools**

- [Coming from rbcodes](docs/migrating/index.md) — where every button went:
  [`launch_specgui`](docs/migrating/specgui.md) · [`rb_zfind`](docs/migrating/rb_zfind.md) ·
  [`rb_multispec`](docs/migrating/rb_multispec.md) · [`rb_ifuview`](docs/migrating/rb_ifuview.md)
- [Absorption lines](docs/guide/absorption.md) · [Redshift](docs/guide/redshift.md) ·
  [Multi-spectrum](docs/guide/multispec.md) · [IFU cubes](docs/guide/ifu.md)

**Building on it**

- [Pack tutorial](docs/packs/tutorial.md) — wrap a function as a node, end to end.
- [Publishing a pack](docs/packs/publishing.md) — shipping it and listing it in the registry.
- [SDK reference](backend/sdk/README.md) — writing nodes with `@node` and `@port_type`.
- [Node schema](docs/formats/node-schema.md) — the `/api/nodes` JSON contract.
- [Workflow format](docs/formats/workflow.md) — `workflow.json` v1, compile rules, the `/ws`
  protocol and binary frames.
- [Bundle format](docs/formats/bundle.md) — the `.acw` layout and import safety rules.
- [HTTP API](docs/api.md) — every endpoint, generated from the OpenAPI snapshot.

**Operating it**

- [Server deployment](docs/deploy/server.md) · [Performance](docs/dev/performance.md) ·
  [Accessibility](docs/dev/accessibility.md) ·
  [rbcodes on Python 3.12](docs/dev/rbcodes-compat.md)

## Roadmap and known limitations

v0.1.0 is a complete, usable release, and it ships with these gaps stated plainly:

- **Not ported from rbcodes:** LLS and Voigt profile fitting (`IGM.LLSFitter`,
  `LLSVoigtFitter`), `rb_align` and `rb_zgui`. See
  [coming from rbcodes](docs/migrating/index.md).
- **Nothing is code-signed.** Windows SmartScreen and macOS Gatekeeper will warn about the
  click-to-run installers; the workarounds are on the install pages.
- **A lab server is sized by its concurrent users.** Each account's engine — cache, thread pool
  and, after its first expensive node, a process pool — lives until the process restarts.
- **The code node's sandbox is a denylist, not a jail.** The trust gate is the real protection.
- **`core.list.collect` takes four inputs.** The SDK has no variadic input ports yet, so stacking
  ten spectra means chaining collects.
- **English only**, though every user-facing string already goes through `t()`.

## Contributing

Issues and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers the toolchain, the
task list, the commit convention (`feat(engine): …`, one logical change per commit) and the
requirement that tests ship in the same commit as the code they cover. Every change should leave
`task lint typecheck test` green.

## Citing

If Astro Canvas is part of work you publish, [CITATION.cff](CITATION.cff) has the metadata — GitHub
renders it as *Cite this repository*. Please cite [rbcodes](https://github.com/rongmon/rbcodes) as
well when you use its nodes; the science in them is Rongmon Bordoloi's.

## License

[MIT](LICENSE) © 2026 Bin Liu and contributors. rbcodes is © Rongmon Bordoloi, MIT.
