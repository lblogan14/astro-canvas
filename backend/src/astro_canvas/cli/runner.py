"""``astro-canvas run``: execute a workflow document headlessly and report per node."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer

from astro_canvas.logging import configure_logging
from astro_canvas.settings import Settings, apply_array_settings, get_settings


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
    settings = get_settings(workspace=workspace, process_pool=not no_processes, auth="none")
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


__all__ = ["run", "run_headless"]
