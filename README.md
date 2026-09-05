# Astro Canvas

**A node-based infinite canvas for exploring astronomical data.** Load spectra, images, and IFU cubes;
wire analysis nodes together; see results inline and in expandable editors; share workflows as bundles.
The scientific core comes from node packs, starting with [rbcodes](https://github.com/rongmon/rbcodes)
(absorption-line measurements, redshift finding, multi-spectrum viewing, IFU cubes) rebuilt as web-native,
headless nodes so undergrads and researchers can run the same tools in a browser tab, on a laptop or a lab server.

## Status

**Pre-alpha, phase 12 of 13 (distribution).** The repository builds, lints, tests, and runs a FastAPI + Vue app
on Windows, macOS, and Linux. Packs register nodes and port types through `astro_canvas.sdk`; the server lists their
schemas, stores `workflow.json` documents, and executes them reactively (content-hash cache, cost gating, thread/process
executors, cancellation) with events over `/ws`. The browser canvas (Vue Flow) lets you browse nodes, place and connect
them with type checking, edit parameters in schema-generated widgets, run, and watch status stream in, with undo/redo,
copy/paste, groups, autosave and version restore. Phase 04 adds the workspace folder (browse, upload, drag files onto the canvas),
loaders for spectra/tables/images/cubes, archive fetch nodes, inline previews (uPlot, image tiles, table heads) and a full-size
viewer (Plotly with server-side re-sampling, Canvas2D image view with WCS readout, Arrow tables).
Phase 10 turns a workflow into a GUI: star a parameter, pin a preview, and the same document renders as a
**form** (App), a step-by-step **Wizard**, or a **Dashboard** of linked views where a range dragged on a
spectrum highlights the matching rows of a table fed by it. The layout lives in the URL (`/w/<id>/wizard`),
the four rbcodes templates ship default layouts, and the templates gallery opens each one straight into its
own interface.
Phase 11 makes packs and workflows travel. **Node packs** install into the shared uv environment through a
manager that shows the resolution diff before it touches anything, blocks a pack whose pins conflict with the
app, snapshots the environment before every install and can roll back to any snapshot exactly. Workflows
export as reproducible **`.acw` bundles** (document, lock, input hashes, results, figures, provenance) and
import back with missing packs and missing inputs reported rather than guessed at. A **Python code node**
runs a snippet with ports you declare, and code that arrives inside a bundle stays **quarantined** until you
have read it.
See [docs/guide/canvas.md](docs/guide/canvas.md), [docs/guide/data.md](docs/guide/data.md),
[docs/guide/absorption.md](docs/guide/absorption.md), [docs/guide/redshift.md](docs/guide/redshift.md),
[docs/guide/multispec.md](docs/guide/multispec.md), [docs/guide/ifu.md](docs/guide/ifu.md),
[docs/guide/batch.md](docs/guide/batch.md), [docs/guide/modes.md](docs/guide/modes.md),
[docs/guide/packs.md](docs/guide/packs.md), [docs/guide/bundles.md](docs/guide/bundles.md),
[docs/guide/code-nodes.md](docs/guide/code-nodes.md) and the roadmap below.

| Phase | Outcome |
|---|---|
| 00 | Monorepo, toolchain, CI matrix, rbcodes Python 3.12 compatibility spike |
| 01–02 | Node SDK and registry; execution engine (cache, scheduler, cancellation, WebSocket events) |
| 03–04 | Canvas MVP (Vue Flow); data, transport, and visualization widgets |
| 05 | rbcodes pack I: absorption-line EW pipeline (`launch_specgui` as a template), continuum-mask / range / line-picker editors, workflow templates API |
| 06 | rbcodes pack II: `rb_zfind` redshift finding (line search, picket fence, MARZ templates, redrock PCA), z-accept editor, redshift-finder template |
| 07 | rbcodes pack III: multi-spectrum viewer (stacked panels, line identification, absorber catalogues, quick fits, rb_multispec file formats) |
| 08 | rbcodes pack IV: IFU cubes (`rb_ifuview` collapses, aperture editor, moment maps, ds9 regions, memory-mapped cubes) |
| 09 | Batch runner (a workflow over a table of rows, specgui batch import) and subgraphs (collapse, breadcrumb navigation, blueprints) with elk auto-layout |
| 10 | App modes: promoted parameters and pinned views rendered as App, Wizard and Dashboard layouts (linked selection), templates gallery |
| 11 | Pack manager (uv resolution plans, snapshots and rollback), git-backed registry, `.acw` bundles, Python code node behind a trust gate |
| 12 | Distribution: full CLI, one-line and click-to-run installers, Docker Compose lab server with user accounts, docs site |
| 13 | Hardening and `v0.1.0` |

## Install it

Not a developer? Start at the [documentation site](https://lblogan14.github.io/astro-canvas/) —
[Windows](docs/install/windows.md), [macOS](docs/install/macos.md), [Linux](docs/install/linux.md),
or a [lab server](docs/deploy/server.md).

```sh
# macOS and Linux
curl -fsSL https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.sh | sh
```

```powershell
# Windows
irm https://raw.githubusercontent.com/lblogan14/astro-canvas/main/launcher/install.ps1 | iex
```

Either installs [uv](https://docs.astral.sh/uv/) if it is missing, installs the app and the
rbcodes pack, makes a desktop shortcut that runs `astro-canvas open`, and opens the browser. The
click-to-run launchers (`.exe`, `.dmg`, `.AppImage`) are on the
[releases page](https://github.com/lblogan14/astro-canvas/releases).

## Quick start (developers)

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 22, [pnpm](https://pnpm.io) 9, [Task](https://taskfile.dev).
Details in [CONTRIBUTING.md](CONTRIBUTING.md).

```sh
git clone https://github.com/lblogan14/astro-canvas
cd astro-canvas
task install                 # uv sync + pnpm install + Playwright chromium
task dev                     # backend http://127.0.0.1:8765 · Vite http://127.0.0.1:5173
task lint typecheck test     # ruff, mypy, eslint, vue-tsc, pytest, vitest, playwright
task build                   # SPA → wheel with bundled static/ → backend/dist/*.whl
```

Run the built wheel anywhere with uv:

```sh
uv run --with backend/dist/astro_canvas_sdk-*.whl --with backend/dist/astro_canvas-*.whl astro-canvas serve --open
```

Configuration is via `ASTRO_CANVAS_*` environment variables (`HOST`, `PORT`, `WORKSPACE`, `LOG_LEVEL`, `TOKEN`, `AUTH`,
`CACHE_MEMORY_MB`, `CACHE_DISK_GB`, `CACHE_MAX_AGE_DAYS`, `MAX_WORKERS`, `PROCESS_POOL`, `RUN_TIMEOUT_S`, `DEBOUNCE_MS`,
`AUTO_THRESHOLD_MS`, `WATCH_WORKSPACE`) or the `astro-canvas serve` flags. The server prints a
`http://127.0.0.1:8765/?token=…` URL at startup; every `/api` and `/ws` request needs that bearer token
(also written to `<config>/token`). `--host 0.0.0.0` refuses to start without `--auth users`.

The CLI is the whole app — full reference in [docs/cli.md](docs/cli.md):

```sh
astro-canvas open                      # what the desktop shortcut runs
astro-canvas doctor                    # python, uv, packs, disk, ports, Qt: paste into a bug report
astro-canvas workspace new ~/papers/lya
astro-canvas pack install astro-canvas-rbcodes --yes
astro-canvas bundle export wf-123 --out share.acw
astro-canvas run tests/fixtures/workflows/math_chain.json --workspace /tmp/ws
```

A lab server is Docker Compose — the app behind Caddy, accounts in Postgres, one private
workspace per person ([docs/deploy/server.md](docs/deploy/server.md)):

```sh
cp deploy/.env.example deploy/.env     # POSTGRES_PASSWORD, CANVAS_DOMAIN, ADMIN_EMAILS
docker compose -f deploy/compose.yaml up -d --build
```

## Documentation

[mkdocs-material](https://squidfunk.github.io/mkdocs-material/) in [docs/](docs/):

```sh
task docs          # serve on http://127.0.0.1:8000
task docs:build    # build into site/ (--strict: a broken link fails)
```

## Tooling rule

The frontend is managed **only with pnpm** and the backend **only with uv**. other package managers are refused by a preinstall guard in `frontend/`,
and CI greps for stray `npm`/`pip` invocations. See [CONTRIBUTING.md](CONTRIBUTING.md#tooling-rule-hard-requirement).

## Layout

`backend/` (FastAPI, engine, SDK, CLI) · `frontend/` (Vue 3, Vite) · `packs/core`, `packs/rbcodes` (node packs, uv
workspace members) · `launcher/`, `deploy/` (phase 12) · `registry/` (pack index seed) · `docs/` · `scripts/`.

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md): toolchain, tasks, conventions.
- [docs/formats/node-schema.md](docs/formats/node-schema.md): the `/api/nodes` JSON contract (`NodeSpec`,
  `ParamSpec`, port types, packs, blobs).
- [docs/formats/workflow.md](docs/formats/workflow.md): `workflow.json` format v1, compile rules, execution model,
  REST endpoints for workflows/runs/outputs, the `/ws` event protocol and binary frames.
- [docs/guide/canvas.md](docs/guide/canvas.md): using the canvas (panels, nodes, connections, shortcuts).
- [docs/guide/data.md](docs/guide/data.md): the workspace folder, loaders, fetch nodes, previews and the viewer.
- [docs/guide/batch.md](docs/guide/batch.md): running a workflow over a table of rows, and the specgui batch import.
- [docs/guide/modes.md](docs/guide/modes.md): promoting parameters, pinning views, and the App, Wizard and
  Dashboard layouts (with linked selection) plus the templates gallery.
- [docs/guide/packs.md](docs/guide/packs.md): installing, enabling, updating and rolling back node packs.
- [docs/guide/bundles.md](docs/guide/bundles.md): sharing a workflow as a `.acw`, and the trust gate.
- [docs/guide/code-nodes.md](docs/guide/code-nodes.md): the Python code node, its ports and its restrictions.
- [docs/formats/bundle.md](docs/formats/bundle.md): the `.acw` layout, import safety rules and the
  `/api/manager` and `/api/bundles` contracts.
- [docs/packs/publishing.md](docs/packs/publishing.md): shipping a pack and listing it in the registry.
- [backend/sdk/README.md](backend/sdk/README.md): writing nodes with the SDK.
- [docs/dev/rbcodes-compat.md](docs/dev/rbcodes-compat.md): rbcodes on Python 3.12, test results, and the
  proposed upstream patch ([docs/dev/rbcodes-upstream.patch](docs/dev/rbcodes-upstream.patch)).

## License

[MIT](LICENSE) © 2026 Bin Liu and contributors. rbcodes is © Rongmon Bordoloi, MIT.
