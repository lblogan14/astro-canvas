# astro-canvas (backend)

FastAPI server, execution engine, and CLI for [Astro Canvas](../README.md). The node SDK lives in
[`sdk/`](sdk/README.md) as the separate distribution `astro-canvas-sdk` (namespace portion `astro_canvas.sdk`), so
packs can depend on it without the server.

Managed exclusively with [uv](https://docs.astral.sh/uv/):

    uv sync --all-extras          # install with dev tools and workspace packs
    uv run astro-canvas serve     # http://127.0.0.1:8765
    uv run pytest
