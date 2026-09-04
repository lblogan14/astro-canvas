"""``POST /api/workflows/{id}/exports``: write finished node outputs into the workspace.

App and Wizard modes end with "Export results": the layout names the outputs worth keeping and
each one becomes a file next to the user's data rather than a browser download, so a run stays
reproducible from the workspace alone. The format follows the value -- a table becomes CSV, a
value with arrays becomes ``.npz``, everything else becomes the same JSON body
``GET /api/outputs`` serves.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from astro_canvas.engine.scheduler import Scheduler
from astro_canvas.sdk import PortType
from astro_canvas.sdk.blob import encode_npz, split_binary, to_manifest_data
from astro_canvas.server.deps import get_runtime
from astro_canvas.server.outputs import ARROW_PART
from astro_canvas.server.runtime import UnknownWorkflowError
from astro_canvas.store.workspace import PathOutsideWorkspaceError

log = structlog.get_logger("astro_canvas.exports")
router = APIRouter(tags=["workflows"])

EXPORTS_DIR = "exports"
ExportFormat = Literal["csv", "npz", "json"]


class ExportRequest(BaseModel):
    """Which outputs to write, and where under the workspace to put them."""

    refs: list[str] = Field(
        default_factory=list, description="``'<node>.<port>'`` outputs to write."
    )
    dir: str | None = Field(
        default=None,
        description="Workspace-relative folder; defaults to ``exports/<workflow name>``.",
    )
    overwrite: bool = True


class ExportedFile(BaseModel):
    ref: str
    path: str
    """Workspace-relative path of the written file."""
    bytes: int
    format: ExportFormat


class SkippedExport(BaseModel):
    ref: str
    reason: Literal["no_output", "bad_ref", "not_written"]
    message: str


class ExportResult(BaseModel):
    dir: str
    files: list[ExportedFile] = Field(default_factory=list)
    skipped: list[SkippedExport] = Field(default_factory=list)


def slug(text: str, fallback: str) -> str:
    """A filesystem-safe folder name for a workflow title."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", text).strip().replace(" ", "-")
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-.")[:60]
    return cleaned or fallback


def _csv_bytes(value: PortType) -> bytes | None:
    """Arrow-backed tables as CSV; ``None`` when the value is not tabular."""
    blob = value.to_blob()
    if ARROW_PART not in blob.parts:
        return None
    import io  # noqa: PLC0415 - lazy: only for table exports

    import pyarrow as pa  # noqa: PLC0415
    import pyarrow.csv as pacsv  # noqa: PLC0415

    with pa.ipc.open_stream(blob.parts[ARROW_PART]) as reader:
        table = reader.read_all()
    sink = io.BytesIO()
    pacsv.write_csv(table, sink)
    return sink.getvalue()


def render_export(value: PortType) -> tuple[ExportFormat, bytes]:
    """Pick the file format for one output value and encode it."""
    csv = _csv_bytes(value)
    if csv is not None:
        return "csv", csv
    _, arrays, _ = split_binary(value.model_dump(mode="python"))
    if arrays:
        return "npz", encode_npz(arrays)
    import json  # noqa: PLC0415 - lazy: only for json exports

    body = {
        "type_id": value.type_id(),
        "data": to_manifest_data(value.model_dump(mode="json")),
    }
    return "json", json.dumps(body, indent=2, sort_keys=True).encode("utf-8")


def _write(target: Path, payload: bytes, *, overwrite: bool) -> Path:
    """Write ``payload``, appending ``-1``, ``-2``, … when the name is taken."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        stem, suffix, index = target.stem, target.suffix, 1
        while target.exists():
            target = target.with_name(f"{stem}-{index}{suffix}")
            index += 1
    target.write_bytes(payload)
    return target


def export_outputs(
    scheduler: Scheduler,
    refs: list[str],
    folder: Path,
    *,
    overwrite: bool = True,
) -> tuple[list[ExportedFile], list[SkippedExport], list[Path]]:
    """Write each ``'<node>.<port>'`` output into ``folder``; report what was skipped."""
    files: list[ExportedFile] = []
    skipped: list[SkippedExport] = []
    written: list[Path] = []
    for ref in refs:
        node, _, port = ref.rpartition(".")
        if not node or not port:
            skipped.append(
                SkippedExport(ref=ref, reason="bad_ref", message="expected '<node>.<port>'")
            )
            continue
        value = scheduler.output(node, port)
        if value is None:
            skipped.append(
                SkippedExport(ref=ref, reason="no_output", message=f"{ref} has no cached output")
            )
            continue
        try:
            fmt, payload = render_export(value)
        except Exception as exc:  # noqa: BLE001 - one bad value must not fail the export
            log.warning("export failed", ref=ref, error=str(exc))
            skipped.append(SkippedExport(ref=ref, reason="not_written", message=str(exc)))
            continue
        name = f"{node.replace('/', '-')}.{port}.{fmt}"
        path = _write(folder / name, payload, overwrite=overwrite)
        written.append(path)
        files.append(ExportedFile(ref=ref, path=path.name, bytes=len(payload), format=fmt))
    return files, skipped, written


@router.post("/workflows/{workflow_id}/exports", response_model=ExportResult)
async def create_export(request: Request, workflow_id: str, body: ExportRequest) -> ExportResult:
    """Write the named outputs into the workspace and return their paths."""
    runtime = get_runtime(request)
    try:
        scheduler = runtime.scheduler(workflow_id)
        doc = runtime.get(workflow_id)
    except UnknownWorkflowError:
        raise HTTPException(status_code=404, detail=f"unknown workflow {workflow_id!r}") from None
    relative = body.dir or f"{EXPORTS_DIR}/{slug(doc.name, workflow_id)}"
    try:
        folder = runtime.workspace.safe_path(relative)
    except PathOutsideWorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    files, skipped, written = export_outputs(scheduler, body.refs, folder, overwrite=body.overwrite)
    rel_dir = runtime.workspace.relative(folder)
    if written:
        log.info("exported outputs", workflow=workflow_id, files=len(written), dir=rel_dir)
    return ExportResult(
        dir=rel_dir,
        files=[f.model_copy(update={"path": f"{rel_dir}/{f.path}"}) for f in files],
        skipped=skipped,
    )


__all__ = ["ExportRequest", "ExportResult", "export_outputs", "render_export", "router", "slug"]
