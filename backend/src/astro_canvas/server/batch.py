"""``/api/workflows/{id}/batch``: run a workflow over a table of rows (design 8.4).

Starting a batch is asynchronous: the response carries the ``batch_id``, per-row progress
arrives as ``batch.row`` events on ``/ws``, and the results grid is polled (or read once
``batch.finished`` lands) from ``GET .../batch/{batch_id}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from astro_canvas.engine.batch import BatchResults, BatchRun, BatchSpec, RowState, spec_from_layout
from astro_canvas.server.runtime import EngineRuntime, UnknownWorkflowError
from astro_canvas.server.workflows import get_runtime

router = APIRouter(tags=["batch"])


class BatchRequest(BaseModel):
    """Rows plus the spec; omitting ``spec`` uses the document's ``layouts.batch``."""

    rows: list[dict[str, Any]] = Field(default_factory=list)
    spec: BatchSpec | None = None


class BatchRowInfo(BaseModel):
    index: int
    state: RowState
    error: str | None = None
    elapsed_ms: float | None = None


class BatchInfo(BaseModel):
    """A batch's state; ``results`` is filled in as rows finish."""

    batch_id: str
    workflow_id: str
    status: str
    n_rows: int
    counts: dict[str, int]
    started: float
    finished: float | None = None
    rows: list[BatchRowInfo]
    results: BatchResults


def _info(run: BatchRun) -> BatchInfo:
    return BatchInfo(
        batch_id=run.batch_id,
        workflow_id=run.workflow_id,
        status=run.status,
        n_rows=run.n_rows,
        counts=run.counts(),
        started=run.started,
        finished=run.finished,
        rows=[
            BatchRowInfo(index=r.index, state=r.state, error=r.error, elapsed_ms=r.elapsed_ms)
            for r in run.records
        ],
        results=run.results(),
    )


def _batch(runtime: EngineRuntime, workflow_id: str, batch_id: str) -> BatchRun:
    run = runtime.batches.get(batch_id)
    if run is None or run.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail=f"unknown batch {batch_id!r}")
    return run


@router.post(
    "/workflows/{workflow_id}/batch",
    response_model=BatchInfo,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_batch(request: Request, workflow_id: str, body: BatchRequest) -> BatchInfo:
    """Run the stored document once per row; returns immediately with the batch record."""
    runtime = get_runtime(request)
    try:
        doc = runtime.get(workflow_id)
    except UnknownWorkflowError:
        raise HTTPException(status_code=404, detail=f"unknown workflow {workflow_id!r}") from None
    spec = body.spec or spec_from_layout(doc.layouts.get("batch") or {})
    if not spec.collect:
        raise HTTPException(
            status_code=400,
            detail="the batch has nothing to collect: add layouts.batch.collect or a spec",
        )
    if not body.rows:
        raise HTTPException(status_code=400, detail="a batch needs at least one row")
    try:
        run = runtime.batches.start(doc, body.rows, spec)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _info(run)


@router.get("/workflows/{workflow_id}/batch/{batch_id}", response_model=BatchInfo)
async def get_batch(request: Request, workflow_id: str, batch_id: str) -> BatchInfo:
    """The batch's per-row states and the results assembled so far."""
    return _info(_batch(get_runtime(request), workflow_id, batch_id))


@router.post("/workflows/{workflow_id}/batch/{batch_id}/cancel", response_model=BatchInfo)
async def cancel_batch(request: Request, workflow_id: str, batch_id: str) -> BatchInfo:
    """Stop queued rows and cancel the ones in flight (expensive nodes have their worker killed)."""
    runtime = get_runtime(request)
    run = _batch(runtime, workflow_id, batch_id)
    runtime.batches.cancel(batch_id)
    return _info(run)
