"""``POST /api/workflows/{id}/run``, ``GET /api/runs/{id}``, ``POST /api/runs/{id}/cancel``."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from astro_canvas.server.deps import get_runtime
from astro_canvas.server.runtime import EngineRuntime, UnknownWorkflowError

router = APIRouter(tags=["runs"])


class RunRequest(BaseModel):
    targets: list[str] | None = Field(
        default=None, description="Node ids to run to (default: every leaf node)."
    )


class RunAccepted(BaseModel):
    run_id: str
    workflow_id: str


class NodeRunInfo(BaseModel):
    node_id: str
    key: str
    status: str
    elapsed_ms: float | None = None
    cache_hit: bool = False
    error: str | None = None


class RunDetail(BaseModel):
    id: str
    workflow_id: str
    status: str
    started: str
    finished: str | None = None
    targets: list[str] | None = None
    nodes: list[NodeRunInfo] = []


class CancelResult(BaseModel):
    cancelled: bool


@router.post(
    "/workflows/{workflow_id}/run", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def start_run(
    request: Request, workflow_id: str, body: RunRequest | None = None
) -> RunAccepted:
    """Queue a run (stale expensive nodes included) and return its id immediately."""
    runtime = get_runtime(request)
    try:
        scheduler = runtime.scheduler(workflow_id)
    except UnknownWorkflowError:
        raise HTTPException(status_code=404, detail=f"unknown workflow {workflow_id!r}") from None
    targets = body.targets if body is not None else None
    unknown = [t for t in targets or [] if t not in scheduler.graph.nodes]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown or invalid target nodes {unknown}")
    return RunAccepted(run_id=scheduler.start_run(targets), workflow_id=workflow_id)


def _detail(runtime: EngineRuntime, run_id: str) -> RunDetail:
    run = runtime.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    import json  # noqa: PLC0415

    return RunDetail(
        id=run.id,
        workflow_id=run.workflow_id,
        status=run.status,
        started=run.started.isoformat(),
        finished=run.finished.isoformat() if run.finished else None,
        targets=json.loads(run.targets_json) if run.targets_json else None,
        nodes=[
            NodeRunInfo(
                node_id=n.node_id,
                key=n.key,
                status=n.status,
                elapsed_ms=n.elapsed_ms,
                cache_hit=n.cache_hit,
                error=n.error,
            )
            for n in runtime.runs.node_runs(run_id)
        ],
    )


@router.get("/runs", response_model=list[RunDetail])
async def list_runs(
    request: Request, workflow_id: str | None = None, limit: int = 50
) -> list[RunDetail]:
    """Recent runs (persisted across restarts), newest first."""
    runtime = get_runtime(request)
    return [_detail(runtime, r.id) for r in runtime.runs.list(workflow_id, limit)]


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(request: Request, run_id: str) -> RunDetail:
    return _detail(get_runtime(request), run_id)


@router.post("/runs/{run_id}/cancel", response_model=CancelResult)
async def cancel_run(request: Request, run_id: str) -> CancelResult:
    """Cancel the run if it is still executing (kills process workers, flags threads)."""
    runtime = get_runtime(request)
    run = runtime.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    scheduler = runtime.schedulers.get(run.workflow_id)
    cancelled = scheduler.cancel(run_id=run_id) if scheduler is not None else False
    return CancelResult(cancelled=cancelled)
