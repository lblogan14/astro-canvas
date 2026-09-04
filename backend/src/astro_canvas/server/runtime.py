"""``EngineRuntime``: workspace, caches, executors and one ``Scheduler`` per open workflow."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import select

from astro_canvas.engine.batch import BatchRunner
from astro_canvas.engine.cache import (
    BlobStore,
    MemoryLRU,
    OutputCache,
    OutputIndex,
    canonical_json,
    digest,
)
from astro_canvas.engine.events import EventBus
from astro_canvas.engine.executors import ProcessExecutor, ThreadExecutor
from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.engine.scheduler import RunInfo, Scheduler, SchedulerConfig
from astro_canvas.manager.trust import TrustStore
from astro_canvas.sdk import NodeRegistry, PortType
from astro_canvas.server.watcher import WorkspaceWatcher
from astro_canvas.settings import Settings
from astro_canvas.store.models import Workflow, WorkflowVersion, utcnow
from astro_canvas.store.recent import RecentWorkspaces
from astro_canvas.store.runs import NodeStatStore, RunStore
from astro_canvas.store.workspace import Workspace

log = structlog.get_logger("astro_canvas.engine")


class WorkflowSummary(BaseModel):
    id: str
    name: str
    description: str = ""
    created: str
    modified: str
    node_count: int
    hash: str


class WorkflowVersionInfo(BaseModel):
    id: int
    created: str
    label: str | None = None


class UnknownWorkflowError(LookupError):
    """No workflow with that id is stored."""


def seed_samples(workspace: Workspace, sample_dirs: Mapping[str, Path]) -> list[Path]:
    """Copy each pack's bundled sample files into ``<workspace>/samples/<pack>`` once.

    Existing files are left alone (users may edit or delete them); returns the copied paths.
    """
    copied: list[Path] = []
    for pack, source in sample_dirs.items():
        if not source.is_dir():
            continue
        dest = workspace.samples_dir / pack
        for item in sorted(source.rglob("*")):
            if not item.is_file() or item.name.startswith("."):
                continue
            target = dest / item.relative_to(source)
            if target.exists():
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                copied.append(target)
            except OSError as exc:  # pragma: no cover - read-only workspace
                log.warning("could not copy sample", file=str(item), error=str(exc))
    return copied


def doc_hash(doc: WorkflowDoc) -> str:
    """Content hash of a document, ignoring the ``meta`` timestamps the server maintains."""
    data = doc.model_dump(by_alias=True, mode="json")
    meta = dict(data.get("meta") or {})
    meta.pop("modified", None)
    meta.pop("created", None)
    data["meta"] = meta
    return digest(canonical_json(data).encode("utf-8"))


class EngineRuntime:
    """Process-wide engine state shared by REST, WebSocket and CLI entry points."""

    def __init__(self, settings: Settings, registry: NodeRegistry) -> None:
        self.settings = settings
        self.registry = registry
        self.bus = EventBus()
        self.threads = ThreadExecutor(settings.max_workers)
        self.processes: ProcessExecutor | None = (
            ProcessExecutor(
                **({"max_workers": settings.max_workers} if settings.max_workers else {})
            )
            if settings.process_pool
            else None
        )
        self.recent = RecentWorkspaces(settings.config_dir)
        self.schedulers: dict[str, Scheduler] = {}
        self.gate: Callable[[WorkflowDoc], Mapping[str, str]] | None = self._trust_gate
        """Trust gate: keeps untrusted code nodes out of the executable graph (design 11)."""
        self.before_save: Callable[[WorkflowDoc], None] | None = self._trust_save
        """Called on every save; trusts locally authored snippets and lifts a cleared quarantine."""
        self.watcher: WorkspaceWatcher | None = None
        self._open_workspace(Path(settings.workspace))
        self.batches = BatchRunner(
            registry=self.registry,
            cache=self.cache,
            bus=self.bus,
            workspace_root=self.workspace.root,
            scratch_root=self.workspace.scratch_dir,
            threads=self.threads,
            processes=self.processes,
            config=self.scheduler_config,
        )

    # --- workspace ---------------------------------------------------------------------------

    def _open_workspace(self, root: Path) -> None:
        """Bind caches, stores and sample data to ``root`` (fresh state for a new workspace)."""
        settings = self.settings
        self.workspace = Workspace(root)
        self.settings.workspace = self.workspace.root
        self.memory = MemoryLRU(settings.cache_memory_mb * 1024 * 1024)
        self.index = OutputIndex(self.workspace.sessions)
        self.cache = OutputCache(
            memory=self.memory,
            blobs=BlobStore(self.workspace.blobs_dir),
            index=self.index,
            types=self.registry.types,
            max_disk_bytes=int(settings.cache_disk_gb * 1024**3),
            max_age=timedelta(days=settings.cache_max_age_days),
        )
        self.runs = RunStore(self.workspace.sessions)
        self.trust = TrustStore(self.workspace.sessions)
        self.recent.touch(self.workspace.root)
        copied = seed_samples(self.workspace, self.registry.sample_dirs)
        if copied:
            log.info("sample data copied", files=len(copied), into=str(self.workspace.samples_dir))
        self.gc()

    def _trust_gate(self, doc: WorkflowDoc) -> Mapping[str, str]:
        """``{node: reason}`` for the code nodes of ``doc`` with no trust decision yet."""
        return self.trust.quarantined(doc)

    def _trust_save(self, doc: WorkflowDoc) -> None:
        return self.trust.on_workflow_saved(doc)

    async def switch_workspace(self, root: Path, *, create: bool = False) -> Path:
        """Close every open workflow and re-open the runtime on another folder."""
        target = Path(root).expanduser().resolve()
        if target.exists() and not target.is_dir():
            raise NotADirectoryError(str(target))
        if not target.exists():
            if not create:
                raise FileNotFoundError(str(target))
            target.mkdir(parents=True, exist_ok=True)
        watching = self.watcher is not None and self.watcher.running
        await self.stop_watcher()
        await self.batches.close()
        await asyncio.gather(*(s.close() for s in self.schedulers.values()), return_exceptions=True)
        self.schedulers.clear()
        self.workspace.close()
        self._open_workspace(target)
        self.recent.select(target)
        self.batches.cache = self.cache
        self.batches.workspace_root = self.workspace.root
        self.batches.scratch_root = self.workspace.scratch_dir
        self.batches.runs.clear()
        if watching:
            self.start_watcher()
        log.info("workspace switched", root=str(self.workspace.root))
        return self.workspace.root

    def start_watcher(self) -> None:
        """Start publishing ``workspace.changed`` events for the active workspace."""
        if not self.settings.watch_workspace:
            return
        if self.watcher is None or self.watcher.root != self.workspace.root:
            self.watcher = WorkspaceWatcher(self.bus, self.workspace.root)
        self.watcher.start()

    async def stop_watcher(self) -> None:
        if self.watcher is not None:
            await self.watcher.stop()
            self.watcher = None

    # --- schedulers --------------------------------------------------------------------------

    def scheduler_config(self) -> SchedulerConfig:
        return SchedulerConfig(
            debounce_s=self.settings.debounce_ms / 1000.0,
            auto_threshold_ms=float(self.settings.auto_threshold_ms),
            run_timeout_s=self.settings.run_timeout_s,
            use_processes=self.settings.process_pool,
        )

    def scheduler(self, workflow_id: str) -> Scheduler:
        """The scheduler for a stored workflow, created (and compiled) on first access."""
        existing = self.schedulers.get(workflow_id)
        if existing is not None:
            return existing
        doc = self.get(workflow_id)
        return self.load(doc)

    def load(self, doc: WorkflowDoc) -> Scheduler:
        """Attach ``doc`` to its scheduler (creating one) and recompile."""
        scheduler = self.schedulers.get(doc.id)
        if scheduler is None:
            scheduler = Scheduler(
                registry=self.registry,
                cache=self.cache,
                bus=self.bus,
                workspace_root=self.workspace.root,
                scratch_root=self.workspace.scratch_dir,
                threads=self.threads,
                processes=self.processes,
                stats=NodeStatStore(self.workspace.sessions, doc.id),
                runs=self.runs,
                config=self.scheduler_config(),
                workflow_id=doc.id,
                after_run=self._after_run,
                gate=lambda document: self.gate(document) if self.gate else {},
            )
            self.schedulers[doc.id] = scheduler
        scheduler.update(doc)
        return scheduler

    def recompile_all(self) -> None:
        """Recompile every open workflow (a trust decision or a pack change moved the goalposts)."""
        for scheduler in list(self.schedulers.values()):
            if scheduler.doc is not None:
                scheduler.update(scheduler.doc)

    def _after_run(self, _info: RunInfo) -> None:
        if self.index.total_bytes() > (self.cache.max_disk_bytes or 0):
            self.gc()

    def gc(self) -> list[str]:
        try:
            removed = self.cache.gc()
        except Exception as exc:  # noqa: BLE001 - GC must never take the server down
            log.warning("blob gc failed", error=str(exc))
            return []
        if removed:
            log.info("blob gc", removed=len(removed))
        return removed

    def output(self, workflow_id: str, node_id: str, port: str) -> PortType | None:
        scheduler = self.schedulers.get(workflow_id)
        return None if scheduler is None else scheduler.output(node_id, port)

    # --- workflow CRUD -----------------------------------------------------------------------

    def list_workflows(self) -> list[WorkflowSummary]:
        with self.workspace.session() as session:
            rows = session.scalars(select(Workflow).order_by(Workflow.modified.desc())).all()
            return [self._summary(row) for row in rows]

    @staticmethod
    def _summary(row: Workflow) -> WorkflowSummary:
        try:
            body: dict[str, Any] = json.loads(row.doc_json)
            node_count = len(body.get("nodes", {}))
            description = str(body.get("description", ""))
        except ValueError:
            node_count, description = 0, ""
        return WorkflowSummary(
            id=row.id,
            name=row.name,
            description=description,
            created=row.created.isoformat(),
            modified=row.modified.isoformat(),
            node_count=node_count,
            hash=row.hash,
        )

    def get(self, workflow_id: str) -> WorkflowDoc:
        with self.workspace.session() as session:
            row = session.get(Workflow, workflow_id)
            if row is None:
                raise UnknownWorkflowError(workflow_id)
            return WorkflowDoc.model_validate_json(row.doc_json)

    def exists(self, workflow_id: str) -> bool:
        with self.workspace.session() as session:
            return session.get(Workflow, workflow_id) is not None

    def save(self, doc: WorkflowDoc, *, label: str | None = None) -> WorkflowDoc:
        """Upsert ``doc`` (snapshotting a version when it changed) and recompile it."""
        if self.before_save is not None:
            self.before_save(doc)
        now = utcnow()
        doc.meta = {**doc.meta, "modified": now.isoformat()}
        doc.meta.setdefault("created", now.isoformat())
        payload = doc.model_dump_json(by_alias=True)
        new_hash = doc_hash(doc)
        with self.workspace.session() as session:
            row = session.get(Workflow, doc.id)
            if row is None:
                row = Workflow(id=doc.id, name=doc.name, doc_json=payload, hash="", created=now)
                session.add(row)
            changed = row.hash != new_hash
            row.name, row.doc_json, row.modified, row.hash = doc.name, payload, now, new_hash
            if changed or label is not None:
                session.add(WorkflowVersion(workflow_id=doc.id, doc_json=payload, label=label))
            session.commit()
        self.load(doc)
        return doc

    def versions(self, workflow_id: str) -> list[WorkflowVersionInfo]:
        with self.workspace.session() as session:
            if session.get(Workflow, workflow_id) is None:
                raise UnknownWorkflowError(workflow_id)
            rows = session.scalars(
                select(WorkflowVersion)
                .where(WorkflowVersion.workflow_id == workflow_id)
                .order_by(WorkflowVersion.id.desc())
            ).all()
            return [
                WorkflowVersionInfo(id=r.id, created=r.created.isoformat(), label=r.label)
                for r in rows
            ]

    def version_doc(self, workflow_id: str, version_id: int) -> WorkflowDoc:
        with self.workspace.session() as session:
            row = session.get(WorkflowVersion, version_id)
            if row is None or row.workflow_id != workflow_id:
                raise UnknownWorkflowError(workflow_id)
            return WorkflowDoc.model_validate_json(row.doc_json)

    async def delete(self, workflow_id: str) -> None:
        scheduler = self.schedulers.pop(workflow_id, None)
        if scheduler is not None:
            await scheduler.close()
        with self.workspace.session() as session:
            row = session.get(Workflow, workflow_id)
            if row is None:
                raise UnknownWorkflowError(workflow_id)
            session.delete(row)
            session.commit()

    # --- lifecycle ---------------------------------------------------------------------------

    async def shutdown(self) -> None:
        await self.stop_watcher()
        await self.batches.close()
        await asyncio.gather(*(s.close() for s in self.schedulers.values()), return_exceptions=True)
        self.threads.shutdown()
        if self.processes is not None:
            self.processes.shutdown()
        self.workspace.close()
