"""``/api/bundles``: export a workflow as a ``.acw`` and import one back (design 7.2).

Export writes into the workspace (``bundles/<name>.acw``) rather than streaming a download, so
the artefact stays next to the data it describes; ``GET /api/bundles/download`` serves it when
the user wants the file itself. Import is a multipart upload that is validated in memory before
anything is written.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from astro_canvas.manager.bundles import (
    DEFAULT_EMBED_MB,
    BundleError,
    BundleImportResult,
    BundleManifest,
    ExportOptions,
    OutputSelection,
    bundle_target,
    export_bundle,
    open_bundle,
    prepare_import,
)
from astro_canvas.server.deps import get_runtime
from astro_canvas.server.runtime import UnknownWorkflowError
from astro_canvas.store.workspace import PathOutsideWorkspaceError

log = structlog.get_logger("astro_canvas.bundles")
router = APIRouter(tags=["bundles"])

MAX_UPLOAD_BYTES = 2 * 1024**3
"""A bundle bigger than 2 GiB is refused before it is read into memory."""


class BundleExportRequest(BaseModel):
    """``POST /api/bundles/export``."""

    workflow_id: str
    embed_inputs_max_mb: int = Field(default=DEFAULT_EMBED_MB, ge=0)
    include_outputs: OutputSelection = "leaves"
    include_figures: bool = True
    dir: str | None = Field(default=None, description="Workspace folder; defaults to ``bundles``.")


@router.post("/bundles/export", response_model=BundleManifest)
async def create_bundle(request: Request, body: BundleExportRequest) -> BundleManifest:
    """Pack a workflow, its inputs, its finished outputs and its provenance into a ``.acw``."""
    runtime = get_runtime(request)
    try:
        doc = runtime.get(body.workflow_id)
        scheduler = runtime.scheduler(body.workflow_id)
    except UnknownWorkflowError:
        raise HTTPException(
            status_code=404, detail=f"unknown workflow {body.workflow_id!r}"
        ) from None
    try:
        target = bundle_target(runtime.workspace, doc, body.dir)
    except PathOutsideWorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    manager = getattr(request.app.state, "manager", None)
    requirements: list[str] = []
    if manager is not None:
        try:
            requirements = manager.uv.freeze()
        except Exception as exc:  # noqa: BLE001 - a lock without a freeze is still a lock
            log.warning("freeze unavailable for bundle lock", error=str(exc))
    return export_bundle(
        doc,
        scheduler,
        runtime.workspace,
        runtime.registry,
        request.app.state.packs,
        target=target,
        options=ExportOptions(
            embed_inputs_max_mb=body.embed_inputs_max_mb,
            include_outputs=body.include_outputs,
            include_figures=body.include_figures,
        ),
        requirements=requirements,
    )


@router.get("/bundles/download", response_model=None)
async def download_bundle(request: Request, path: str) -> FileResponse:
    """Serve a bundle that lives in the workspace."""
    runtime = get_runtime(request)
    try:
        target = runtime.workspace.safe_path(path)
    except PathOutsideWorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"no bundle at {path!r}")
    return FileResponse(target, filename=target.name, media_type="application/zip")


@router.post(
    "/bundles/import", response_model=BundleImportResult, status_code=status.HTTP_201_CREATED
)
async def import_bundle(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008 - FastAPI's dependency marker
    restore_into: str = Form("imports"),
    open_now: bool = Form(True),
) -> BundleImportResult:
    """Validate an uploaded ``.acw``, restore what it carries and save the workflow.

    The workflow is stored either way so the user can look at it; ``missing_packs``,
    ``layout_errors``, ``inputs`` and ``quarantined`` say what still needs attention.
    """
    runtime = get_runtime(request)
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="the bundle is larger than 2 GiB")
    try:
        contents = open_bundle(payload)
        doc, result = prepare_import(
            contents,
            runtime.workspace,
            runtime.registry,
            request.app.state.packs,
            restore_into=restore_into,
        )
    except BundleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PathOutsideWorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if open_now:
        runtime.save(doc, label=f"imported from {file.filename or 'bundle'}")
    log.info(
        "bundle imported",
        workflow=doc.id,
        quarantined=result.quarantined,
        missing_packs=sorted(result.missing_packs),
    )
    return result


__all__ = ["BundleExportRequest", "router"]
