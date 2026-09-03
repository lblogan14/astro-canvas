# Astro Canvas

**A node-based infinite canvas for exploring astronomical data.** Load spectra, images, and IFU cubes;
wire analysis nodes together; see results inline and in expandable editors; share workflows as bundles.
The scientific core comes from node packs, starting with [rbcodes](https://github.com/rongmon/rbcodes)
(absorption-line measurements, redshift finding, multi-spectrum viewing, IFU cubes) rebuilt as web-native,
headless nodes so undergrads and researchers can run the same tools in a browser tab, on a laptop or a lab server.

## Status

**Pre-alpha, phase 00 of 13 (foundation).** The repository builds, lints, tests, and runs an empty FastAPI + Vue
shell on Windows, macOS, and Linux. No nodes, engine, or canvas yet. See the roadmap below.

| Phase | Outcome |
|---|---|
| 00 | Monorepo, toolchain, CI matrix, rbcodes Python 3.12 compatibility spike |
| 01–02 | Node SDK and registry; execution engine (cache, scheduler, cancellation, WebSocket events) |
| 03–04 | Canvas MVP (Vue Flow); data, transport, and visualization widgets |
| 05–08 | rbcodes packs: absorption lines, redshift, multi-spectrum viewer, IFU cubes |
| 09–13 | Batch and subgraphs, app modes, pack manager and bundles, distribution, hardening and `v0.1.0` |

## Quick start (developers)

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 22, [pnpm](https://pnpm.io) 9, [Task](https://taskfile.dev).
Details in [CONTRIBUTING.md](CONTRIBUTING.md).

```sh
git clone https://github.com/bkoservices/astro-canvas
cd astro-canvas
task install                 # uv sync + pnpm install + Playwright chromium
task dev                     # backend http://127.0.0.1:8765 · Vite http://127.0.0.1:5173
task lint typecheck test     # ruff, mypy, eslint, vue-tsc, pytest, vitest, playwright
task build                   # SPA → wheel with bundled static/ → backend/dist/*.whl
```

Run the built wheel anywhere with uv:

```sh
uv run --with backend/dist/astro_canvas-*.whl astro-canvas serve --open
```

Configuration is via `ASTRO_CANVAS_*` environment variables (`HOST`, `PORT`, `WORKSPACE`, `LOG_LEVEL`) or the
`astro-canvas serve --host --port --workspace --open` flags.

## Tooling rule

The frontend is managed **only with pnpm** and the backend **only with uv**. other package managers are refused by a preinstall guard in `frontend/`,
and CI greps for stray `npm`/`pip` invocations. See [CONTRIBUTING.md](CONTRIBUTING.md#tooling-rule-hard-requirement).

## Layout

`backend/` (FastAPI, engine, SDK, CLI) · `frontend/` (Vue 3, Vite) · `packs/core`, `packs/rbcodes` (node packs, uv
workspace members) · `launcher/`, `deploy/` (phase 12) · `registry/` (pack index seed) · `docs/` · `scripts/`.

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md): toolchain, tasks, conventions.
- [docs/dev/rbcodes-compat.md](docs/dev/rbcodes-compat.md): rbcodes on Python 3.12, test results, and the
  proposed upstream patch ([docs/dev/rbcodes-upstream.patch](docs/dev/rbcodes-upstream.patch)).
- User documentation (mkdocs) arrives with the first user-visible features.

## License

[MIT](LICENSE) © 2026 Bin Liu and contributors. rbcodes is © Rongmon Bordoloi, MIT.
