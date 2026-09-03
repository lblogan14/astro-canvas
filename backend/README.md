# astro-canvas (backend)

FastAPI server, execution engine, and CLI for [Astro Canvas](../README.md). The node SDK lives in
[`sdk/`](sdk/README.md) as the separate distribution `astro-canvas-sdk` (namespace portion `astro_canvas.sdk`), so
packs can depend on it without the server.

Managed exclusively with [uv](https://docs.astral.sh/uv/):

    uv sync --all-extras          # install with dev tools and workspace packs
    uv run astro-canvas serve     # http://127.0.0.1:8765
    uv run pytest

Layout: `astro_canvas/engine/` (document compiler, cache keys and stores, scheduler, executors, events),
`astro_canvas/store/` (SQLAlchemy models, Alembic migrations, `Workspace`), `astro_canvas/server/` (FastAPI
routers: nodes, workflows, runs, outputs, `/ws`), `astro_canvas/cli.py` (`serve`, `run`). Engine and store are
covered at >= 85 % and `astro_canvas.engine` is mypy-strict. Contracts: [`../docs/formats/workflow.md`](../docs/formats/workflow.md).

    uv run astro-canvas run tests/fixtures/workflows/math_chain.json --workspace /tmp/ws --json
