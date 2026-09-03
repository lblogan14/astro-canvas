"""``astro-canvas`` command line interface."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import webbrowser
from pathlib import Path
from typing import Annotated, Any

import httpx
import structlog
import typer
import uvicorn

from astro_canvas._version import __version__
from astro_canvas.logging import configure_logging
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings, apply_array_settings, get_settings

app = typer.Typer(
    name="astro-canvas",
    help="Node-based canvas for exploring astronomical data.",
    no_args_is_help=True,
    add_completion=False,
)

log = structlog.get_logger("astro_canvas.cli")


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


def open_when_ready(url: str, *, timeout: float = 30.0, interval: float = 0.2) -> bool:
    """Poll ``url/api/health`` until it answers, then open ``url`` in the browser.

    Returns:
        ``True`` if the browser was opened, ``False`` on timeout.
    """
    deadline = time.monotonic() + timeout
    health = f"{url.split('?', 1)[0].rstrip('/')}/api/health"
    while time.monotonic() < deadline:
        try:
            if httpx.get(health, timeout=1.0).status_code == 200:
                webbrowser.open(url)
                return True
        except httpx.HTTPError:
            pass
        time.sleep(interval)
    log.warning("server did not become ready; not opening browser", url=url)
    return False


def run_server(settings: Settings, *, open_browser: bool) -> None:
    """Start uvicorn with the app built from ``settings`` (blocking)."""
    url = f"http://{settings.host}:{settings.port}"
    log.info("starting", url=url, workspace=str(settings.workspace))
    app = create_app(settings)
    token = getattr(app.state, "token", None)
    if token:
        typer.echo(f"Open {url}/?token={token}")
        url = f"{url}/?token={token}"
    if open_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address (default 127.0.0.1).")] = None,
    port: Annotated[int | None, typer.Option(help="Port (default 8765).")] = None,
    workspace: Annotated[
        Path | None, typer.Option(help="Workspace folder (default <Documents>/AstroCanvas).")
    ] = None,
    open_browser: Annotated[
        bool, typer.Option("--open", help="Open the browser once the server is up.")
    ] = False,
) -> None:
    """Run the Astro Canvas server."""
    settings = get_settings(host=host, port=port, workspace=workspace)
    configure_logging(settings.log_level)
    run_server(settings, open_browser=open_browser)


async def run_headless(
    settings: Settings, doc_path: Path, targets: list[str] | None
) -> dict[str, Any]:
    """Compile and execute ``doc_path`` to completion; returns a JSON-able summary."""
    apply_array_settings(settings)
    # Lazy imports keep ``astro-canvas version`` fast.
    from astro_canvas.engine.graph import WorkflowDoc  # noqa: PLC0415
    from astro_canvas.sdk import discover  # noqa: PLC0415
    from astro_canvas.server.runtime import EngineRuntime  # noqa: PLC0415

    doc = WorkflowDoc.model_validate_json(doc_path.read_text(encoding="utf-8"))
    runtime = EngineRuntime(settings, discover().registry)
    try:
        scheduler = runtime.load(doc)
        scheduler.set_auto_run(False)
        run_id = await scheduler.run(targets or None)
        info = scheduler.run_history[-1]
        nodes: dict[str, Any] = {}
        for nid, rec in sorted(scheduler.records.items()):
            outputs = scheduler.cache.lookup(rec.key) if rec.state == "done" else None
            nodes[nid] = {
                "state": rec.state,
                "stale": rec.stale,
                "cache_hit": rec.cache_hit,
                "elapsed_ms": rec.elapsed_ms,
                "error": rec.error,
                "outputs": {p: v.type_id() for p, v in (outputs or {}).items()},
            }
        return {
            "run_id": run_id,
            "status": info.status,
            "workflow_id": doc.id,
            "node_errors": {k: [i.model_dump() for i in v] for k, v in scheduler.issues.items()},
            "nodes": nodes,
        }
    finally:
        await runtime.shutdown()


@app.command()
def run(
    workflow: Annotated[Path, typer.Argument(help="Path to a workflow.json document.")],
    target: Annotated[
        list[str] | None, typer.Option("--target", "-t", help="Run only up to these node ids.")
    ] = None,
    workspace: Annotated[
        Path | None, typer.Option(help="Workspace folder (default <Documents>/AstroCanvas).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the summary as JSON.")] = False,
    no_processes: Annotated[
        bool, typer.Option("--no-processes", help="Run expensive nodes on threads.")
    ] = False,
) -> None:
    """Execute a workflow headlessly and print a per-node summary."""
    settings = get_settings(workspace=workspace, process_pool=not no_processes, auth=False)
    configure_logging("warning")
    summary = asyncio.run(run_headless(settings, workflow, target))
    if as_json:
        typer.echo(json.dumps(summary, indent=2))
    else:
        typer.echo(f"run {summary['run_id']}: {summary['status']}")
        for nid, issues in summary["node_errors"].items():
            for issue in issues:
                typer.echo(f"  ! {nid}: {issue['code']}: {issue['message']}")
        for nid, node in summary["nodes"].items():
            elapsed = f"{node['elapsed_ms']:.0f} ms" if node["elapsed_ms"] is not None else "-"
            flags = " cached" if node["cache_hit"] else ""
            flags += " stale" if node["stale"] else ""
            outputs = ", ".join(f"{p}:{t}" for p, t in node["outputs"].items())
            line = f"  {nid:<24} {node['state']:<10} {elapsed:>9}{flags}  {outputs}"
            typer.echo(line.rstrip())
            if node["error"]:
                typer.echo(f"      {node['error']}")
    if summary["status"] != "done" or summary["node_errors"]:
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
