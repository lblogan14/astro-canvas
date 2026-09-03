"""``/api/workflows``: CRUD, versions and the current per-node status snapshot."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from astro_canvas.engine.events import NodeIssue, NodeStatus
from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.server.runtime import (
    EngineRuntime,
    UnknownWorkflowError,
    WorkflowSummary,
    WorkflowVersionInfo,
)

router = APIRouter(tags=["workflows"])


def get_runtime(request: Request) -> EngineRuntime:
    runtime: EngineRuntime = request.app.state.runtime
    return runtime


class WorkflowSaved(BaseModel):
    """A stored document plus the compile result for its current content."""

    doc: WorkflowDoc
    node_errors: dict[str, list[NodeIssue]]


class WorkflowStatus(BaseModel):
    workflow_id: str
    node_errors: dict[str, list[NodeIssue]]
    nodes: dict[str, NodeStatus]
    current_run: str | None = None


def _not_found(workflow_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"unknown workflow {workflow_id!r}")


@router.get("/workflows", response_model=list[WorkflowSummary])
async def list_workflows(request: Request) -> list[WorkflowSummary]:
    """Stored workflows, most recently modified first."""
    return get_runtime(request).list_workflows()


@router.post("/workflows", response_model=WorkflowSaved, status_code=status.HTTP_201_CREATED)
async def create_workflow(request: Request, doc: WorkflowDoc) -> WorkflowSaved:
    """Store a new document (a fresh id is assigned when the given one already exists)."""
    runtime = get_runtime(request)
    if runtime.exists(doc.id):
        raise HTTPException(status_code=409, detail=f"workflow {doc.id!r} already exists")
    saved = runtime.save(doc)
    return WorkflowSaved(doc=saved, node_errors=runtime.scheduler(saved.id).issues)


@router.get("/workflows/{workflow_id}", response_model=WorkflowDoc)
async def get_workflow(request: Request, workflow_id: str) -> WorkflowDoc:
    try:
        return get_runtime(request).get(workflow_id)
    except UnknownWorkflowError:
        raise _not_found(workflow_id) from None


@router.put("/workflows/{workflow_id}", response_model=WorkflowSaved)
async def put_workflow(request: Request, workflow_id: str, doc: WorkflowDoc) -> WorkflowSaved:
    """Replace the document; the engine recompiles it and auto-runs cheap dirty nodes."""
    if doc.id != workflow_id:
        raise HTTPException(status_code=400, detail="document id does not match the URL")
    runtime = get_runtime(request)
    saved = runtime.save(doc)
    return WorkflowSaved(doc=saved, node_errors=runtime.scheduler(saved.id).issues)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(request: Request, workflow_id: str) -> Response:
    try:
        await get_runtime(request).delete(workflow_id)
    except UnknownWorkflowError:
        raise _not_found(workflow_id) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/workflows/{workflow_id}/versions", response_model=list[WorkflowVersionInfo])
async def list_versions(request: Request, workflow_id: str) -> list[WorkflowVersionInfo]:
    """Auto-snapshots (every changed save) and labelled versions, newest first."""
    try:
        return get_runtime(request).versions(workflow_id)
    except UnknownWorkflowError:
        raise _not_found(workflow_id) from None


@router.get("/workflows/{workflow_id}/versions/{version_id}", response_model=WorkflowDoc)
async def get_version(request: Request, workflow_id: str, version_id: int) -> WorkflowDoc:
    try:
        return get_runtime(request).version_doc(workflow_id, version_id)
    except UnknownWorkflowError:
        raise _not_found(workflow_id) from None


@router.get("/workflows/{workflow_id}/status", response_model=WorkflowStatus)
async def workflow_status(request: Request, workflow_id: str) -> WorkflowStatus:
    """Compile issues and the state of every node (what a reconnecting client needs)."""
    runtime = get_runtime(request)
    try:
        scheduler = runtime.scheduler(workflow_id)
    except UnknownWorkflowError:
        raise _not_found(workflow_id) from None
    current = scheduler.current_run
    return WorkflowStatus(
        workflow_id=workflow_id,
        node_errors=scheduler.issues,
        nodes=scheduler.snapshot(),
        current_run=current.run_id if current else None,
    )
