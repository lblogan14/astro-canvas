"""``/api/manager/trust`` and ``/api/workflows/{id}/trust``: decisions about code snippets.

These routes read and write the *workspace's* ``trust`` table, not the Python environment, so
they are deliberately not part of the admin-only pack manager: on a ``--auth users`` server every
user reviews the code in their own documents, and one user's decision must not run in another
user's session. The paths keep their phase-11 shape so the quarantine banner and the trust dialog
are unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astro_canvas.manager.trust import Decision, TrustRecord, TrustReview
from astro_canvas.server.deps import get_runtime

router = APIRouter(tags=["trust"])


class TrustRequest(BaseModel):
    hash: str
    decision: Decision = "trusted"


@router.get("/manager/trust", response_model=list[TrustRecord])
def list_trust(request: Request) -> list[TrustRecord]:
    """Every code-snippet decision this workspace has made."""
    return get_runtime(request).trust.records()


@router.post("/manager/trust", response_model=TrustRecord)
def set_trust(request: Request, body: TrustRequest) -> TrustRecord:
    """Trust or block one snippet hash; every node with that snippet follows."""
    runtime = get_runtime(request)
    record = runtime.trust.set(body.hash, body.decision)
    runtime.recompile_all()
    return record


@router.get("/workflows/{workflow_id}/trust", response_model=TrustReview)
def review_workflow(request: Request, workflow_id: str) -> TrustReview:
    """The code snippets of one workflow with their decisions: the quarantine banner's source."""
    runtime = get_runtime(request)
    try:
        doc = runtime.get(workflow_id)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"unknown workflow {workflow_id!r}") from None
    blocked = runtime.trust.quarantined(doc)
    return TrustReview(
        workflow_id=workflow_id,
        quarantined=bool(blocked),
        snippets=runtime.trust.review(doc),
        blocked_nodes=sorted(blocked),
    )


@router.delete("/manager/trust/{snippet_hash}", status_code=204)
def forget_trust(request: Request, snippet_hash: str) -> None:
    """Forget a decision, so the snippet is quarantined again."""
    runtime = get_runtime(request)
    if not runtime.trust.forget(snippet_hash):
        raise HTTPException(status_code=404, detail=f"unknown snippet {snippet_hash!r}")
    runtime.recompile_all()


__all__ = ["router"]
