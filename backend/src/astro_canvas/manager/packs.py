"""``PackManager``: install, enable, update, roll back and hot-register node packs (design 9).

Everything here follows the same shape: *plan, snapshot, act, verify*.

1. ``resolve`` runs ``uv pip install --dry-run`` with the app's own distributions pinned, so a
   pack whose pins would break the app comes back as a conflict rather than as a broken install.
2. ``install`` snapshots ``uv pip freeze`` **before** touching anything, so ``rollback`` can put
   the environment back exactly as it was.
3. After the install an import test runs in a **subprocess** -- a pack that segfaults or hangs on
   import must not take the server with it.
4. If the pack is new, it is registered into the live registry (its nodes appear without a
   restart); if it replaces already-imported code, ``restart_required`` is raised instead, because
   Python will not re-import a module that is already in ``sys.modules``.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable
from datetime import datetime
from importlib.metadata import EntryPoint

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astro_canvas.engine.events import EventBus, PacksChanged
from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.manager.plan import (
    InstallPlan,
    PackSource,
    PlanAction,
    SourceError,
    classify_source,
    parse_dry_run,
)
from astro_canvas.manager.registry import RegistryClient
from astro_canvas.manager.settings import SecurityLevel, SettingsStore
from astro_canvas.manager.trust import TrustStore
from astro_canvas.manager.uv import UvError, UvNotFoundError, UvRunner
from astro_canvas.sdk import NodeRegistry, PackRecord, load_pack, pack_entry_points
from astro_canvas.store.models import Pack, Snapshot, utcnow

log = structlog.get_logger("astro_canvas.manager")

APP_DISTRIBUTIONS: tuple[str, ...] = ("astro-canvas", "astro-canvas-sdk")
"""Pinned during every resolution so a pack cannot silently downgrade the app out from under us."""

IMPORT_TEST_TIMEOUT_S = 120.0


class ManagerError(RuntimeError):
    """The manager refused an operation (bad source, blocked plan, missing snapshot)."""


class PackDetail(BaseModel):
    """One pack as the Manager's *Installed* tab shows it (``/api/health`` has a summary)."""

    name: str
    version: str = "unknown"
    distribution: str | None = None
    entry_point: str = ""
    enabled: bool = True
    loaded: bool = Field(default=False, description="Registered in the running server right now.")
    node_count: int = 0
    type_count: int = 0
    template_count: int = 0
    security: str = "standard"
    source: str | None = None
    installed: str | None = None
    error: str | None = None
    traceback: str | None = None


class ImportTest(BaseModel):
    """Result of importing a freshly installed pack in a throw-away subprocess."""

    module: str
    ok: bool
    error: str = ""


class SnapshotInfo(BaseModel):
    """A recorded ``uv pip freeze`` the environment can be rolled back to."""

    id: int
    created: str
    label: str = ""
    packages: int = 0


class InstallResult(BaseModel):
    """Outcome of an environment mutation."""

    ok: bool
    action: PlanAction
    source: str = ""
    plan: InstallPlan | None = None
    snapshot_id: int | None = None
    packs: list[str] = Field(default_factory=list)
    restart_required: bool = False
    import_test: ImportTest | None = None
    message: str = ""
    output: str = ""


def _snapshot_payload(freeze: Iterable[str], label: str) -> str:
    return json.dumps({"label": label, "packages": sorted(freeze)}, indent=2)


def freeze_index(lines: Iterable[str]) -> dict[str, str]:
    """``{distribution name: requirement line}`` for a ``uv pip freeze``.

    Freeze lines come in three shapes: ``name==version``, ``name @ file:///â€¦`` (a direct URL or
    a workspace member) and ``-e file:///â€¦`` (editable). Editable lines carry no name, so they
    are skipped: a rollback leaves them alone rather than guessing what they were.
    """
    index: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", "-e ", "--")):
            continue
        name = line.split(" @ ", 1)[0].split("==", 1)[0].split("[", 1)[0].strip()
        if name:
            index[name.replace("_", "-").lower()] = line
    return index


class PackManager:
    """The service behind ``/api/manager/*``.

    Args:
        registry: The live node registry (mutated on hot-registration).
        sessions: Workspace database sessions (``packs``, ``snapshots``, ``settings`` tables).
        settings: Manager preferences (security level, uv path, registry URL).
        bus: Event bus, used to publish ``packs.changed``.
        uv: Explicit ``UvRunner``; built lazily from the settings when omitted.
        records: The ``PackRecord`` list ``discover()`` produced at start-up.
        on_change: Called after the registry changed so the server can refresh derived state.
        on_recompile: Called when a trust decision changed, so open workflows re-evaluate the gate.
    """

    def __init__(
        self,
        registry: NodeRegistry,
        sessions: sessionmaker[Session],
        settings: SettingsStore,
        *,
        bus: EventBus | None = None,
        uv: UvRunner | None = None,
        records: list[PackRecord] | None = None,
        on_change: Callable[[list[str]], None] | None = None,
        on_recompile: Callable[[], None] | None = None,
        registry_client: RegistryClient | None = None,
    ) -> None:
        self.registry = registry
        self.sessions = sessions
        self.settings = settings
        self.bus = bus
        self.records: list[PackRecord] = list(records or [])
        self.on_change = on_change
        self.on_recompile = on_recompile
        self.trust = TrustStore(sessions)
        self.restart_required = False
        self._uv = uv
        self._registry_client = registry_client
        self.sync_records()

    def on_workflow_saved(self, doc: WorkflowDoc) -> None:
        """Trust hook for every save (``EngineRuntime.before_save``).

        Code the user wrote here is trusted on the spot; an imported document stays quarantined
        until every one of its snippets has a decision, and then loses the flag for good.
        """
        if doc.meta.get("quarantine"):
            if not self.trust.quarantined(doc):
                doc.meta = {k: v for k, v in doc.meta.items() if k != "quarantine"}
            return
        self.trust.trust_local(doc)

    def recompile(self) -> None:
        """Re-evaluate the trust gate on every open workflow (after a decision changed)."""
        if self.on_recompile is not None:
            self.on_recompile()

    # --- environment -------------------------------------------------------------------------

    @property
    def uv(self) -> UvRunner:
        """The ``uv`` runner, built from the current settings on first use.

        Raises:
            UvNotFoundError: when no ``uv`` binary can be located.
        """
        if self._uv is None:
            self._uv = UvRunner(self.settings.get().uv_path, sys.executable)
        return self._uv

    @property
    def index(self) -> RegistryClient:
        """The registry client, rebuilt when the configured URL changes."""
        url = self.settings.get().registry_url
        if self._registry_client is None:
            self._registry_client = RegistryClient(url)
        elif url and self._registry_client.url != url:
            self._registry_client = RegistryClient(url, self._registry_client.cache_dir)
        return self._registry_client

    def uv_status(self) -> tuple[str | None, str]:
        """``(path, version)`` of the located uv, or ``(None, <why not>)``.

        Running it is part of the check: a configured path that no longer exists is exactly the
        case ``doctor`` and Manager > Settings have to report, not raise on.
        """
        try:
            runner = self.uv
            return str(runner.uv_path), runner.version()
        except UvNotFoundError as exc:
            return None, str(exc)

    # --- installed packs ---------------------------------------------------------------------

    def sync_records(self) -> None:
        """Upsert a ``packs`` row per discovered pack and unregister the disabled ones."""
        with self.sessions() as session:
            rows = {row.name: row for row in session.scalars(select(Pack)).all()}
            for record in self.records:
                row = rows.get(record.name)
                if row is None:
                    session.add(Pack(name=record.name, version=record.version, enabled=True))
                else:
                    row.version = record.version
            session.commit()
        for name in self.disabled():
            self.registry.remove_pack(name)

    def disabled(self) -> set[str]:
        with self.sessions() as session:
            rows = session.scalars(select(Pack).where(Pack.enabled.is_(False))).all()
            return {row.name for row in rows}

    def installed(self) -> list[PackDetail]:
        """Every discovered pack, merged with what the database remembers about it."""
        with self.sessions() as session:
            rows = {row.name: row for row in session.scalars(select(Pack)).all()}
        out: list[PackDetail] = []
        for record in self.records:
            row = rows.get(record.name)
            enabled = row.enabled if row is not None else True
            out.append(
                PackDetail(
                    name=record.name,
                    version=record.version,
                    distribution=record.distribution,
                    entry_point=record.entry_point,
                    enabled=enabled,
                    loaded=enabled and record.error is None,
                    node_count=record.node_count,
                    type_count=record.type_count,
                    template_count=1 if record.name in self.registry.template_dirs else 0,
                    security=record.security,
                    source=row.source if row is not None else None,
                    installed=row.installed.isoformat() if row is not None else None,
                    error=record.error.error if record.error else None,
                    traceback=record.error.traceback if record.error else None,
                )
            )
        return sorted(out, key=lambda p: p.name)

    def set_enabled(self, name: str, enabled: bool) -> PackDetail:
        """Enable or disable a pack. Disabled packs stay installed but are not registered.

        Both directions take effect immediately: disabling drops the pack's nodes out of the
        registry, and enabling calls its ``register(registry)`` again. No new code is involved
        either way, so neither needs a restart.
        """
        with self.sessions() as session:
            row = session.get(Pack, name)
            if row is None:
                raise ManagerError(f"unknown pack {name!r}")
            row.enabled = enabled
            session.commit()
        if enabled:
            self._register([name], new_code=False)
        else:
            self.registry.remove_pack(name)
            self._changed("disabled", [name])
        info = next((p for p in self.installed() if p.name == name), None)
        if info is None:  # pragma: no cover - the row exists, so the record does too
            raise ManagerError(f"unknown pack {name!r}")
        return info

    # --- plans -------------------------------------------------------------------------------

    def guard_requirements(self) -> list[str]:
        """Exact pins for the app's own distributions, added to every resolution.

        Without them ``uv pip install`` happily plans a resolution that satisfies the new pack
        alone -- downgrading numpy under astropy, say. Pinning what is installed turns that into
        an honest "no solution" the user can act on.
        """
        pins: list[str] = []
        for name in APP_DISTRIBUTIONS:
            try:
                pins.append(f"{name}=={importlib.metadata.version(name)}")
            except importlib.metadata.PackageNotFoundError:  # pragma: no cover - dev checkouts
                continue
        return pins

    def check_source(self, raw: str) -> PackSource:
        """Classify ``raw`` and refuse it when the security level does not allow that shape."""
        source = classify_source(raw)
        level: SecurityLevel = self.settings.get().security
        if level == "permissive":
            return source
        if source.kind in ("git", "url", "path"):
            if level == "standard" and self._in_registry(source.raw):
                return source
            raise SourceError(
                f"the {level!r} security level does not allow installing from a {source.kind}; "
                "switch to 'permissive' in Manager > Settings to allow it"
            )
        if level == "strict" and not self._in_registry(source.name):
            raise SourceError(
                f"{source.name!r} is not in the registry and the security level is 'strict'"
            )
        return source

    def _in_registry(self, needle: str) -> bool:
        name = needle.split("[", 1)[0].strip()
        if self.index.entry(name) is not None:
            return True
        return any(entry.source == needle for entry in self.index.fetch().entries)

    def resolve(self, raw: str, *, action: PlanAction = "install") -> InstallPlan:
        """Dry-run ``raw`` and return the diff (or the conflict that blocks it)."""
        source = self.check_source(raw)
        args = ["install", "--dry-run", source.requirement, *self.guard_requirements()]
        result = self.uv.pip(args, check=False)
        return parse_dry_run(
            result.stdout, result.stderr, result.returncode, source=raw, action=action
        )

    def resolve_uninstall(self, name: str) -> InstallPlan:
        """The diff of removing ``name`` (uv reports uninstalls the same way)."""
        result = self.uv.pip(["uninstall", "--dry-run", name], check=False)
        return parse_dry_run(
            result.stdout, result.stderr, result.returncode, source=name, action="uninstall"
        )

    # --- mutations ---------------------------------------------------------------------------

    def install(self, raw: str, *, plan: InstallPlan | None = None) -> InstallResult:
        """Snapshot, install ``raw``, import-test it and hot-register what it added."""
        plan = plan or self.resolve(raw)
        if not plan.ok:
            raise ManagerError(plan.message or "the resolution has conflicts; install is blocked")
        source = self.check_source(raw)
        snapshot = self.snapshot(f"before install {raw}")
        before = set(self._entry_point_names())
        try:
            result = self.uv.pip(["install", source.requirement, *self.guard_requirements()])
        except UvError as exc:
            return InstallResult(
                ok=False,
                action="install",
                source=raw,
                plan=plan,
                snapshot_id=snapshot.id,
                message=exc.result.output.splitlines()[-1] if exc.result.output else str(exc),
                output=exc.result.output,
            )
        added = [name for name in self._entry_point_names() if name not in before]
        test = self.import_test(added[0]) if added else None
        if test is not None and not test.ok:
            log.warning("import test failed", pack=added[0], error=test.error)
            self.rollback(snapshot.id)
            return InstallResult(
                ok=False,
                action="install",
                source=raw,
                plan=plan,
                snapshot_id=snapshot.id,
                import_test=test,
                message=f"{added[0]} could not be imported; the environment was rolled back",
                output=result.output,
            )
        restart = self._register(added)
        self._record_source(added, raw)
        return InstallResult(
            ok=True,
            action="install",
            source=raw,
            plan=plan,
            snapshot_id=snapshot.id,
            packs=added,
            restart_required=restart,
            import_test=test,
            message=(
                "restart the server to finish loading the new code"
                if restart
                else f"installed {', '.join(added) or raw}"
            ),
            output=result.output,
        )

    def update(self, name: str) -> InstallResult:
        """Re-resolve a pack with ``--upgrade``; new code always needs a restart to take effect."""
        distribution = self._distribution_for(name)
        plan_result = self.uv.pip(
            ["install", "--dry-run", "--upgrade", distribution, *self.guard_requirements()],
            check=False,
        )
        plan = parse_dry_run(
            plan_result.stdout,
            plan_result.stderr,
            plan_result.returncode,
            source=distribution,
            action="update",
        )
        if not plan.ok:
            raise ManagerError(plan.message or "the update has conflicts")
        snapshot = self.snapshot(f"before update {distribution}")
        if plan.is_empty:
            return InstallResult(
                ok=True,
                action="update",
                source=distribution,
                plan=plan,
                snapshot_id=snapshot.id,
                message=f"{distribution} is already up to date",
            )
        try:
            result = self.uv.pip(["install", "--upgrade", distribution, *self.guard_requirements()])
        except UvError as exc:
            return InstallResult(
                ok=False,
                action="update",
                source=distribution,
                plan=plan,
                snapshot_id=snapshot.id,
                message=str(exc),
                output=exc.result.output,
            )
        self.restart_required = True
        self._changed("updated", [name])
        return InstallResult(
            ok=True,
            action="update",
            source=distribution,
            plan=plan,
            snapshot_id=snapshot.id,
            packs=[name],
            restart_required=True,
            message="restart the server to load the updated pack",
            output=result.output,
        )

    def uninstall(self, name: str) -> InstallResult:
        """Remove a pack's distribution and unregister its nodes."""
        distribution = self._distribution_for(name)
        snapshot = self.snapshot(f"before uninstall {distribution}")
        try:
            result = self.uv.pip(["uninstall", distribution])
        except UvError as exc:
            return InstallResult(
                ok=False,
                action="uninstall",
                source=distribution,
                snapshot_id=snapshot.id,
                message=str(exc),
                output=exc.result.output,
            )
        self.registry.remove_pack(name)
        self.records = [r for r in self.records if r.name != name]
        with self.sessions() as session:
            row = session.get(Pack, name)
            if row is not None:
                session.delete(row)
                session.commit()
        self._changed("uninstalled", [name])
        return InstallResult(
            ok=True,
            action="uninstall",
            source=distribution,
            snapshot_id=snapshot.id,
            packs=[name],
            message=f"uninstalled {distribution}",
            output=result.output,
        )

    # --- snapshots ---------------------------------------------------------------------------

    def snapshot(self, label: str = "") -> SnapshotInfo:
        """Record ``uv pip freeze`` so this exact environment can be restored."""
        freeze = self.uv.freeze()
        with self.sessions() as session:
            row = Snapshot(lock_json=_snapshot_payload(freeze, label))
            session.add(row)
            session.commit()
            return SnapshotInfo(
                id=row.id, created=row.created.isoformat(), label=label, packages=len(freeze)
            )

    def snapshots(self) -> list[SnapshotInfo]:
        with self.sessions() as session:
            rows = session.scalars(select(Snapshot).order_by(Snapshot.id.desc())).all()
            return [self._snapshot_info(row) for row in rows]

    @staticmethod
    def _snapshot_info(row: Snapshot) -> SnapshotInfo:
        try:
            body = json.loads(row.lock_json)
        except ValueError:  # pragma: no cover - the column is written by us
            body = {}
        return SnapshotInfo(
            id=row.id,
            created=(row.created or datetime.min).isoformat(),
            label=str(body.get("label", "")),
            packages=len(body.get("packages", [])),
        )

    def snapshot_packages(self, snapshot_id: int) -> list[str]:
        with self.sessions() as session:
            row = session.get(Snapshot, snapshot_id)
            if row is None:
                raise ManagerError(f"unknown snapshot {snapshot_id}")
            return list(json.loads(row.lock_json).get("packages", []))

    def rollback(self, snapshot_id: int) -> InstallResult:
        """Restore a snapshot: reinstall what changed, remove what was added since.

        Deliberately a *diff* rather than ``uv pip sync``. A sync rebuilds every entry, which in a
        development checkout means rebuilding the editable workspace members from an unrelated
        working directory -- and failing. Touching only what actually differs restores the freeze
        just as exactly, and leaves editable installs (identical in both freezes) alone.
        """
        wanted = freeze_index(self.snapshot_packages(snapshot_id))
        current = freeze_index(self.uv.freeze())
        install = [req for name, req in sorted(wanted.items()) if current.get(name) != req]
        remove = sorted(name for name in current if name not in wanted)
        pinned = [req for req in install if "==" in req]
        unpinned = [req for req in install if "==" not in req]

        outputs: list[str] = []
        ok = True
        if remove:
            result = self.uv.pip(["uninstall", *remove], check=False)
            outputs.append(result.output)
            ok = ok and result.ok
        if pinned:
            result = self.uv.pip(["install", *pinned], check=False)
            outputs.append(result.output)
            ok = ok and result.ok
        self.restart_required = True
        self._changed("rolled-back", [])
        changed = len(remove) + len(pinned)
        message = (
            f"restored {changed} packages from snapshot {snapshot_id}" if ok else "rollback failed"
        )
        if ok and unpinned:
            # A direct-URL or editable entry cannot be reinstalled from a freeze line alone.
            message += f"; {len(unpinned)} entries could not be restored automatically"
        return InstallResult(
            ok=ok,
            action="rollback",
            source=f"snapshot {snapshot_id}",
            snapshot_id=snapshot_id,
            restart_required=True,
            message=message,
            output="\n".join(part for part in outputs if part),
        )

    # --- registration ------------------------------------------------------------------------

    def import_test(self, pack: str) -> ImportTest:
        """``python -c "import <module>"`` in a subprocess so a bad pack cannot crash the server."""
        module = self._module_for(pack)
        try:
            completed = subprocess.run(  # noqa: S603 - argv built from our own values
                [str(self.uv.python), "-c", f"import {module}"],
                capture_output=True,
                text=True,
                timeout=IMPORT_TEST_TIMEOUT_S,
                env={**os.environ, **(self.uv.env or {})},
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ImportTest(module=module, ok=False, error=str(exc))
        error = "" if completed.returncode == 0 else (completed.stderr or "").strip()
        return ImportTest(module=module, ok=completed.returncode == 0, error=error[-4000:])

    def _entry_points(self) -> dict[str, EntryPoint]:
        importlib.invalidate_caches()
        return {ep.name: ep for ep in pack_entry_points()}

    def _entry_point_names(self) -> list[str]:
        return sorted(self._entry_points())

    def _module_for(self, pack: str) -> str:
        for ep in pack_entry_points():
            if ep.name == pack:
                return ep.value.split(":", 1)[0]
        return pack.replace("-", "_")

    def _distribution_for(self, name: str) -> str:
        for record in self.records:
            if record.name == name:
                return record.distribution or name
        return name

    def _register(self, names: list[str], *, new_code: bool = True) -> bool:
        """Register packs into the live registry; returns ``True`` when a restart is needed.

        ``new_code`` is the whole distinction. Installing or updating brings *new code*, and
        Python will not re-import a module that is already in ``sys.modules``, so a pack whose
        module is loaded can only change on restart. Re-enabling a pack brings no new code at
        all: its ``register(registry)`` is simply called again on the module already in memory,
        which is safe, cheap, and takes effect immediately.
        """
        if not names:
            return self.restart_required
        entry_points = self._entry_points()
        restart = False
        registered: list[str] = []
        for name in names:
            ep = entry_points.get(name)
            if ep is None:
                continue
            module = ep.value.split(":", 1)[0].split(".", 1)[0]
            if new_code and module in sys.modules:
                restart = True
                continue
            self.registry.remove_pack(name)
            record = load_pack(self.registry, ep)
            self.records = [r for r in self.records if r.name != name] + [record]
            registered.append(name)
        self.records.sort(key=lambda r: r.name)
        if restart:
            self.restart_required = True
        if registered or restart:
            self._changed("installed", registered)
        return restart

    def _record_source(self, names: list[str], source: str) -> None:
        with self.sessions() as session:
            for name in names:
                row = session.get(Pack, name)
                if row is None:
                    session.add(Pack(name=name, source=source, installed=utcnow()))
                else:
                    row.source, row.installed = source, utcnow()
            session.commit()

    def _changed(self, change: str, packs: list[str]) -> None:
        if self.on_change is not None:
            self.on_change(packs)
        if self.bus is not None:
            self.bus.publish(PacksChanged(workflow_id="*", event=change))
        log.info("packs changed", change=change, packs=packs)


__all__ = [
    "APP_DISTRIBUTIONS",
    "ImportTest",
    "InstallResult",
    "ManagerError",
    "PackDetail",
    "PackManager",
    "SnapshotInfo",
    "freeze_index",
]
