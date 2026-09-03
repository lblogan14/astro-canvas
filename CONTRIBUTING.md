# Contributing to Astro Canvas

Thanks for helping build a node-based canvas for astronomical data. This page covers the
toolchain, the day-to-day commands, and the conventions every change must follow.

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.5+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (or `irm https://astral.sh/uv/install.ps1 \| iex`) |
| Python | 3.12 (also tested on 3.10) | `uv python install 3.12` |
| Node.js | 22 LTS | https://nodejs.org |
| [pnpm](https://pnpm.io/installation) | 9.x | pnpm reads `packageManager` from `frontend/package.json` and switches itself to the pinned version |
| [Task](https://taskfile.dev/installation/) | 3.x | `winget install Task.Task` · `brew install go-task` · `sh -c "$(curl -sL https://taskfile.dev/install.sh)"` |

## Tooling rule (hard requirement)

- The **frontend** is managed **only with pnpm**. Never `npm`, `npx`, `yarn`, or `bun`; use `pnpm dlx` where you would use `npx`.
  `frontend/package.json` has a `preinstall` guard that refuses other package managers, and only `pnpm-lock.yaml` is committed.
- The **backend** and every Python environment are managed **only with uv**. Never `pip`, `pip-tools`, `poetry`, `conda`, or a bare `venv`;
  use `uv add`, `uv sync`, `uv run`, `uv build`. Only `uv.lock` is committed, never `requirements*.txt`.
- `task check:tooling` (also run in CI) greps the Taskfile, workflows, docs, and manifests for violations.

## Quick start

```sh
git clone https://github.com/bkoservices/astro-canvas
cd astro-canvas
task install        # uv sync + pnpm install + Playwright chromium
task dev            # backend on http://127.0.0.1:8765, Vite on http://127.0.0.1:5173
```

Open http://127.0.0.1:5173. The Vite dev server proxies `/api` and `/ws` to the backend.

## Everyday tasks

| Command | What it does |
|---|---|
| `task lint` | ruff (backend, sdk, packs, scripts), oxlint, eslint, prettier check, tooling rule |
| `task typecheck` | mypy (strict on `sdk/` and `engine/`) and vue-tsc |
| `task test` | `test:py` (pytest with coverage and per-package gates: `sdk/` >= 90 %), `test:fe` (Vitest), `test:e2e` (Playwright against a real backend) |
| `task fmt` | ruff format/fix, oxlint/eslint fix, prettier write |
| `task build` | `pnpm build` → copy `dist/` into `backend/src/astro_canvas/static/` → build the `astro-canvas-sdk` and `astro-canvas` wheels → verify the app wheel bundles `index.html` |
| `task build:smoke` | install both wheels in a throwaway env and check `astro-canvas serve` serves the SPA |
| `task api:gen` | export `/api/openapi.json` to `backend/src/astro_canvas/server/openapi/` and regenerate `frontend/src/api/schema.d.ts` (CI fails if the snapshot is stale) |

Headless runs set `MPLBACKEND=Agg` and `QT_QPA_PLATFORM=offscreen` (the Taskfile and CI do this for you).
Point the server at a scratch workspace with `ASTRO_CANVAS_WORKSPACE=<dir>`.

## Repository layout

```
backend/    uv workspace root → PyPI "astro-canvas" (engine, server, store, manager, cli)
backend/sdk uv workspace member → PyPI "astro-canvas-sdk" (the `astro_canvas.sdk` namespace portion packs depend on)
frontend/   pnpm + Vite + Vue 3 + TypeScript (Pinia, Vue Router, Tailwind 4, shadcn-vue, vue-i18n)
packs/      node packs, uv workspace members: core/ and rbcodes/
launcher/   installers and PyApp launcher (phase 12)
deploy/     Docker Compose for lab servers (phase 12)
registry/   seed index for the git-backed pack registry
docs/       user and developer docs
scripts/    cross-platform helpers used by the Taskfile and CI
```

## Git workflow

- Work happens on a branch per phase: `phase/NN-<slug>`, merged to `main` with `--no-ff` and tagged `v0.1.0-phaseNN`.
- [Conventional commits](https://www.conventionalcommits.org/): `feat(engine): …`, `fix(canvas): …`, `test(sdk): …`, `docs: …`, `chore(ci): …`.
  Scope is the top-level module. No emojis. **No `Co-Authored-By` trailers.**
- One logical change per commit; every commit leaves `task lint typecheck test` green.
- Never commit built assets (`frontend/dist`, `backend/src/astro_canvas/static/*`), secrets, or `docs/designs/`.
- Update `uv.lock` / `pnpm-lock.yaml` in the same commit as the dependency change.

## Code standards

**Python**: ruff (line length 100; rules `E,F,I,UP,B,SIM,PL`), mypy strict on `astro_canvas.sdk` and `astro_canvas.engine`.
Type hints on all public APIs, Pydantic v2 for every wire type, Google-style docstrings (they become node descriptions).
No `print`; use `structlog`. No pickle for persisted data. Never import PyQt5 in server code paths.

**TypeScript**: `strict` and `noUncheckedIndexedAccess`; `<script setup lang="ts">`; Pinia only for shared state;
no `any` without a comment; all user-facing strings go through vue-i18n `t()`.

**Tests**: new code ships with tests in the same commit. Backend tests live in `backend/tests/<layer>/`, frontend
unit tests in `frontend/src/**/__tests__/`, e2e in `frontend/e2e/`. Coverage gates: backend ≥ 85 % on `sdk/`,
`engine/`, `store/`; frontend stores ≥ 80 %.
