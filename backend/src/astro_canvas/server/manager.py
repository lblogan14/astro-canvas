"""``/api/manager/*``: installed packs, the registry, resolution plans, snapshots and trust.

Every route that changes the environment is two calls: ``resolve`` returns the plan the dialog
shows, ``install`` (or ``update``/``uninstall``) acts on it. Nothing here installs without a plan
that resolved cleanly, and everything that touches the environment snapshots first.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from astro_canvas.manager.packs import (
    ImportTest,
    InstallResult,
    ManagerError,
    PackInfo,
    PackManager,
    SnapshotInfo,
)
from astro_canvas.manager.plan import InstallPlan, PlanAction, SourceError
from astro_canvas.manager.registry import RegistryIndex
from astro_canvas.manager.settings import (
    SECURITY_HELP,
    SECURITY_LEVELS,
    ManagerSettings,
    ManagerSettingsUpdate,
)
from astro_canvas.manager.trust import Decision, TrustRecord, TrustReview
from astro_canvas.manager.uv import UvError, UvNotFoundError
from astro_canvas.settings import apply_security_level

log = structlog.get_logger("astro_canvas.manager")
router = APIRouter(tags=["manager"])


class ManagerStatus(BaseModel):
    """What Manager > Settings shows about this installation."""

    uv_path: str | None = None
    uv_version: str = ""
    uv_error: str | None = None
    python: str
    settings: ManagerSettings
    security_levels: list[str] = Field(default_factory=lambda: list(SECURITY_LEVELS))
    security_help: dict[str, str] = Field(default_factory=lambda: dict(SECURITY_HELP))
    restart_required: bool = False


class ResolveRequest(BaseModel):
    source: str
    action: PlanAction = "install"


class InstallRequest(BaseModel):
    source: str
    confirm: bool = Field(
        default=False,
        description="Must be true: the plan is shown first and the user confirms it (design 9).",
    )


class EnableRequest(BaseModel):
    enabled: bool = True


class SnapshotRequest(BaseModel):
    label: str = ""


class TrustRequest(BaseModel):
    hash: str
    decision: Decision = "trusted"


def get_manager(request: Request) -> PackManager:
    manager: PackManager | None = getattr(request.app.state, "manager", None)
    if manager is None:
        raise HTTPException(status_code=404, detail="the pack manager is disabled on this server")
    return manager


def _fail(exc: Exception) -> HTTPException:
    """Manager failures are user errors (bad source, blocked plan, no uv), not 500s."""
    if isinstance(exc, UvNotFoundError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, UvError):
        return HTTPException(status_code=502, detail=exc.result.output or str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/manager/status", response_model=ManagerStatus)
def get_status(request: Request) -> ManagerStatus:
    """uv, the interpreter packs are installed into, and the current preferences."""
    manager = get_manager(request)
    path, version = manager.uv_status()
    return ManagerStatus(
        uv_path=path,
        uv_version=version if path else "",
        uv_error=None if path else version,
        python=str(manager.uv.python) if path else "",
        settings=manager.settings.get(),
        restart_required=manager.restart_required,
    )


@router.post("/manager/settings", response_model=ManagerSettings)
def update_settings(request: Request, body: ManagerSettingsUpdate) -> ManagerSettings:
    """Persist the security level, uv path or registry URL for this workspace."""
    manager = get_manager(request)
    updated = manager.settings.update(body)
    manager._uv = None  # noqa: SLF001 - the runner is rebuilt from the new settings on next use
    apply_security_level(updated.security)
    log.info("manager settings updated", security=updated.security)
    return updated


@router.get("/manager/packs", response_model=list[PackInfo])
def list_packs(request: Request) -> list[PackInfo]:
    """Every discovered pack with its database state and load error."""
    return get_manager(request).installed()


@router.post("/manager/packs/resolve", response_model=InstallPlan)
def resolve(request: Request, body: ResolveRequest) -> InstallPlan:
    """Dry-run a source and return the resolution diff (or the conflicts that block it)."""
    manager = get_manager(request)
    try:
        if body.action == "uninstall":
            return manager.resolve_uninstall(body.source)
        return manager.resolve(body.source, action=body.action)
    except (SourceError, ManagerError, UvError, UvNotFoundError) as exc:
        raise _fail(exc) from exc


@router.post("/manager/packs/install", response_model=InstallResult)
def install(request: Request, body: InstallRequest) -> InstallResult:
    """Install a source the user has confirmed a plan for."""
    manager = get_manager(request)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm the resolution plan first")
    try:
        return manager.install(body.source)
    except (SourceError, ManagerError, UvError, UvNotFoundError) as exc:
        raise _fail(exc) from exc


@router.post("/manager/packs/{name}/update", response_model=InstallResult)
def update_pack(request: Request, name: str) -> InstallResult:
    manager = get_manager(request)
    try:
        return manager.update(name)
    except (ManagerError, UvError, UvNotFoundError) as exc:
        raise _fail(exc) from exc


@router.delete("/manager/packs/{name}", response_model=InstallResult)
def uninstall_pack(request: Request, name: str) -> InstallResult:
    manager = get_manager(request)
    try:
        return manager.uninstall(name)
    except (ManagerError, UvError, UvNotFoundError) as exc:
        raise _fail(exc) from exc


@router.post("/manager/packs/{name}/enabled", response_model=PackInfo)
def set_enabled(request: Request, name: str, body: EnableRequest) -> PackInfo:
    """Enable or disable a pack; disabled packs stay installed but are not registered."""
    manager = get_manager(request)
    try:
        return manager.set_enabled(name, body.enabled)
    except ManagerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/manager/packs/{name}/import-test", response_model=ImportTest)
def import_test(request: Request, name: str) -> ImportTest:
    """Import the pack in a subprocess and report the traceback if it fails."""
    manager = get_manager(request)
    try:
        return manager.import_test(name)
    except UvNotFoundError as exc:
        raise _fail(exc) from exc


@router.get("/manager/snapshots", response_model=list[SnapshotInfo])
def list_snapshots(request: Request) -> list[SnapshotInfo]:
    return get_manager(request).snapshots()


@router.post("/manager/snapshots", response_model=SnapshotInfo)
def create_snapshot(request: Request, body: SnapshotRequest | None = None) -> SnapshotInfo:
    """Record ``uv pip freeze`` so this environment can be restored later."""
    manager = get_manager(request)
    try:
        return manager.snapshot(body.label if body else "")
    except (UvError, UvNotFoundError) as exc:
        raise _fail(exc) from exc


@router.get("/manager/snapshots/{snapshot_id}", response_model=list[str])
def snapshot_packages(request: Request, snapshot_id: int) -> list[str]:
    try:
        return get_manager(request).snapshot_packages(snapshot_id)
    except ManagerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/manager/snapshots/{snapshot_id}/rollback", response_model=InstallResult)
def rollback(request: Request, snapshot_id: int) -> InstallResult:
    """Restore a snapshot exactly (``uv pip sync`` against the recorded freeze)."""
    manager = get_manager(request)
    try:
        return manager.rollback(snapshot_id)
    except (ManagerError, UvError, UvNotFoundError) as exc:
        raise _fail(exc) from exc


@router.get("/manager/registry", response_model=RegistryIndex)
def get_registry(
    request: Request, refresh: bool = False, q: str = "", category: str | None = None
) -> RegistryIndex:
    """The registry index, filtered. Never fails: a stale cached copy beats an empty tab."""
    manager = get_manager(request)
    index = manager.index.fetch(refresh=refresh)
    if not q and category is None:
        return index
    return index.model_copy(update={"entries": index.search(q, category)})


@router.get("/manager/trust", response_model=list[TrustRecord])
def list_trust(request: Request) -> list[TrustRecord]:
    """Every code-snippet decision this workspace has made."""
    return get_manager(request).trust.records()


@router.post("/manager/trust", response_model=TrustRecord)
def set_trust(request: Request, body: TrustRequest) -> TrustRecord:
    """Trust or block one snippet hash; every node with that snippet follows."""
    manager = get_manager(request)
    record = manager.trust.set(body.hash, body.decision)
    manager.recompile()
    return record


@router.get("/workflows/{workflow_id}/trust", response_model=TrustReview)
def review_workflow(request: Request, workflow_id: str) -> TrustReview:
    """The code snippets of one workflow with their decisions: the quarantine banner's source."""
    manager = get_manager(request)
    runtime = request.app.state.runtime
    try:
        doc = runtime.get(workflow_id)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"unknown workflow {workflow_id!r}") from None
    blocked = manager.trust.quarantined(doc)
    return TrustReview(
        workflow_id=workflow_id,
        quarantined=bool(blocked),
        snippets=manager.trust.review(doc),
        blocked_nodes=sorted(blocked),
    )


@router.delete("/manager/trust/{snippet_hash}", status_code=204)
def forget_trust(request: Request, snippet_hash: str) -> None:
    """Forget a decision, so the snippet is quarantined again."""
    manager = get_manager(request)
    if not manager.trust.forget(snippet_hash):
        raise HTTPException(status_code=404, detail=f"unknown snippet {snippet_hash!r}")
    manager.recompile()


__all__ = ["ManagerStatus", "get_manager", "router"]
