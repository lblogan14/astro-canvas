"""Reactive scheduler with cost gating (design 6.3).

Per node: ``idle -> dirty -> queued -> running -> done | error | cancelled`` plus a ``stale``
flag for dirty nodes gated by cost. Dirtiness is derived from cache keys: ``update(doc)``
recompiles, recomputes every key and marks nodes whose key changed (or that never ran). A
250 ms debounce then auto-runs cheap nodes; expensive ones wait for an explicit ``run``.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import shutil
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import structlog
from pydantic import ValidationError

from astro_canvas.engine.cache import OutputCache, OutputRef, cache_key, sub_key
from astro_canvas.engine.context import EngineContext
from astro_canvas.engine.events import (
    EventBus,
    GraphValidation,
    NodeErrorEvent,
    NodeIssue,
    NodeOutputSummary,
    NodeState,
    NodeStatus,
    RunFinished,
    RunStarted,
    RunStatus,
)
from astro_canvas.engine.executors import ProcessExecutor, ThreadExecutor, ThreadJob
from astro_canvas.engine.graph import ExecGraph, ExecNode, ValidationErrors, WorkflowDoc, compile
from astro_canvas.engine.outputs import OutputError, coerce, unwrap_linked, wrap_outputs
from astro_canvas.engine.worker import WorkerJob
from astro_canvas.sdk import BlobError, Expansion, NodeDef, NodeRegistry, PortType

log = structlog.get_logger("astro_canvas.engine")

CostClass = Literal["cheap", "expensive"]


class StatsStore(Protocol):
    """Per node instance runtime statistics (``store.runs.NodeStatStore`` or in-memory)."""

    def average_ms(self, node_id: str) -> float | None: ...

    def record(self, node_id: str, elapsed_ms: float, cost_class: str) -> float: ...


class RunRecorder(Protocol):
    """Optional persistence of runs (``store.runs.RunStore``)."""

    def begin(self, run_id: str, workflow_id: str, targets: Sequence[str] | None) -> None: ...

    def record(self, run_id: str, record: Any) -> None: ...

    def finish(self, run_id: str, status: str) -> None: ...


@dataclass
class SchedulerConfig:
    debounce_s: float = 0.25
    auto_threshold_ms: float = 2000.0
    run_timeout_s: float | None = None
    use_processes: bool = True
    auto_run: bool = True
    registry_factory: str = "astro_canvas.engine.worker:default_registry"


@dataclass
class NodeRecord:
    """Runtime bookkeeping for one node."""

    key: str = ""
    state: NodeState = "idle"
    stale: bool = False
    cache_hit: bool = False
    elapsed_ms: float | None = None
    error: str | None = None
    cost_class: CostClass = "cheap"
    run_id: str | None = None


@dataclass
class RunInfo:
    run_id: str
    targets: list[str] | None
    auto: bool
    started: float = field(default_factory=time.perf_counter)
    n_nodes: int = 0
    cached: int = 0
    status: RunStatus = "running"
    abort: bool = False
    message: str | None = None


class UpstreamMissingError(RuntimeError):
    """A required upstream output is not available (failed, cancelled or evicted)."""


class Scheduler:
    """Owns one workflow's execution state."""

    def __init__(
        self,
        *,
        registry: NodeRegistry,
        cache: OutputCache,
        bus: EventBus,
        workspace_root: Path,
        scratch_root: Path,
        threads: ThreadExecutor,
        processes: ProcessExecutor | None,
        stats: StatsStore,
        runs: RunRecorder | None = None,
        config: SchedulerConfig | None = None,
        workflow_id: str = "",
        after_run: Callable[[RunInfo], None] | None = None,
    ) -> None:
        self.after_run = after_run
        self.registry = registry
        self.cache = cache
        self.bus = bus
        self.workspace_root = workspace_root
        self.scratch_root = scratch_root
        self.threads = threads
        self.processes = processes
        self.stats = stats
        self.runs = runs
        self.config = config or SchedulerConfig()
        self.workflow_id = workflow_id
        self.doc: WorkflowDoc | None = None
        self.graph = ExecGraph(workflow_id=workflow_id)
        self.issues: dict[str, list[NodeIssue]] = {}
        self.records: dict[str, NodeRecord] = {}
        self.auto_run = self.config.auto_run
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._debounce: asyncio.Task[None] | None = None
        self._run_lock = asyncio.Lock()
        self._current: RunInfo | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._background: set[asyncio.Task[str]] = set()
        self.run_history: list[RunInfo] = []

    # --- document updates --------------------------------------------------------------------

    def update(self, doc: WorkflowDoc) -> GraphValidation:
        """Recompile ``doc``; mark changed nodes dirty; arm the debounce for auto-run."""
        self.doc = doc
        self.workflow_id = doc.id
        result = compile(doc, self.registry)
        if isinstance(result, ValidationErrors):
            self.graph, self.issues = result.graph, dict(result.node_errors)
        else:
            self.graph, self.issues = result, {}
        keys = self._compute_keys()
        changed: list[str] = []
        for nid in self.graph.order:
            rec = self.records.setdefault(nid, NodeRecord())
            rec.cost_class = self._effective_cost(self.graph.nodes[nid])
            if rec.key != keys[nid] or rec.state == "idle":
                if rec.state == "running":
                    self._cancel_node(nid)
                rec.key = keys[nid]
                rec.state = "dirty"
                rec.stale = rec.cache_hit = False
                rec.error = None
                rec.elapsed_ms = None
                changed.append(nid)
        for nid in list(self.records):
            if nid not in self.graph.nodes:
                if nid in self.doc.nodes or nid in self.graph.blocked or nid in self.issues:
                    rec = self.records[nid]
                    if rec.state == "running":
                        self._cancel_node(nid)
                    if rec.state != "idle":
                        rec.state, rec.stale, rec.key = "idle", False, ""
                        changed.append(nid)
                else:
                    del self.records[nid]
        for nid in [*self.graph.blocked, *self.issues]:
            if nid not in self.records and (nid in self.doc.nodes or "/" in nid):
                self.records[nid] = NodeRecord()
                changed.append(nid)
        validation = GraphValidation(workflow_id=self.workflow_id, node_errors=self.issues)
        self.bus.publish(validation)
        for nid in changed:
            self._emit_status(nid)
        if self.auto_run and any(r.state == "dirty" for r in self.records.values()):
            self._arm_debounce()
        return validation

    def _compute_keys(self) -> dict[str, str]:
        keys: dict[str, str] = {}
        for nid in self.graph.order:
            node = self.graph.nodes[nid]
            node_def = self.registry.get(node.type)
            upstream = {
                port: f"{keys[src]}:{sport}"
                for port, (src, sport) in node.inputs.items()
                if src in keys
            }
            fingerprint: Any = None
            if node_def.fingerprint is not None:
                try:
                    fingerprint = node_def.fingerprint(**node.params)
                except Exception as exc:  # noqa: BLE001 - a failing fingerprint just busts the cache
                    fingerprint = f"error:{exc!r}:{time.time_ns()}"
            keys[nid] = cache_key(node.type, node.version, node.params, upstream, fingerprint)
        return keys

    def _effective_cost(self, node: ExecNode) -> CostClass:
        if node.cost == "cheap":
            return "cheap"
        if node.cost == "expensive":
            return "expensive"
        average = self.stats.average_ms(node.id)
        return (
            "expensive"
            if average is not None and average > self.config.auto_threshold_ms
            else "cheap"
        )

    def _arm_debounce(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no event loop (synchronous callers): nothing to debounce
            return
        self._loop = loop
        if self._debounce is not None and not self._debounce.done():
            self._debounce.cancel()
        self._debounce = loop.create_task(self._debounced())

    async def _debounced(self) -> None:
        await asyncio.sleep(self.config.debounce_s)
        await self.run(None, auto=True)

    def set_auto_run(self, enabled: bool) -> None:
        self.auto_run = enabled
        if enabled and any(r.state == "dirty" for r in self.records.values()):
            self._arm_debounce()

    # --- queries -----------------------------------------------------------------------------

    def state_of(self, node_id: str) -> NodeRecord | None:
        return self.records.get(node_id)

    def output(self, node_id: str, port: str) -> PortType | None:
        """A finished node's output value from the cache, or ``None``."""
        rec = self.records.get(node_id)
        if rec is None or rec.state != "done":
            return None
        outputs = self.cache.lookup(rec.key)
        return None if outputs is None else outputs.get(port)

    def snapshot(self) -> dict[str, NodeStatus]:
        return {nid: self._status_event(nid) for nid in self.records}

    @property
    def current_run(self) -> RunInfo | None:
        return self._current

    # --- runs --------------------------------------------------------------------------------

    def _plan(self, targets: Sequence[str] | None) -> list[str]:
        graph = self.graph
        if targets:
            roots = {t for t in targets if t in graph.nodes}
        else:
            roots = {nid for nid in graph.nodes if not graph.consumers(nid)}
        wanted = roots | graph.ancestors(roots, include_lazy=False)
        plan: list[str] = []
        for nid in graph.order:
            if nid not in wanted:
                continue
            rec = self.records[nid]
            if rec.state == "done" and rec.key in self.cache.memory:
                continue
            plan.append(nid)
        return plan

    def start_run(self, targets: Sequence[str] | None = None) -> str:
        """Schedule ``run`` as a background task and return its id immediately."""
        run_id = uuid.uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        self._loop = loop
        if self.runs is not None:  # visible to GET /api/runs/{id} before the task starts
            self.runs.begin(run_id, self.workflow_id, list(targets) if targets else None)
        self._background.add(loop.create_task(self.run(targets, run_id=run_id, begun=True)))
        self._background = {t for t in self._background if not t.done()}
        return run_id

    async def run(
        self,
        targets: Sequence[str] | None = None,
        *,
        auto: bool = False,
        run_id: str | None = None,
        begun: bool = False,
    ) -> str:
        """Execute ``targets`` (default: every leaf) plus dirty ancestors; returns the run id."""
        self._loop = asyncio.get_running_loop()
        self.bus.bind(self._loop)
        run_id = run_id or uuid.uuid4().hex[:12]
        async with self._run_lock:
            info = RunInfo(run_id=run_id, targets=list(targets) if targets else None, auto=auto)
            self._current = info
            plan = self._plan(targets)
            info.n_nodes = len(plan)
            if self.runs is not None and not begun:
                self.runs.begin(run_id, self.workflow_id, info.targets)
            self.bus.publish(
                RunStarted(
                    workflow_id=self.workflow_id,
                    run_id=run_id,
                    targets=info.targets,
                    n_nodes=len(plan),
                )
            )
            try:
                await asyncio.wait_for(self._execute_plan(info, plan), self.config.run_timeout_s)
            except TimeoutError:
                info.abort = True
                info.status = "cancelled"
                info.message = f"run exceeded {self.config.run_timeout_s} s"
                for nid in list(self._tasks):
                    self._cancel_node(nid)
                await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            finally:
                shutil.rmtree(self.scratch_root / run_id, ignore_errors=True)
                if info.status == "running":
                    info.status = self._final_status(info, plan)
                if self.runs is not None:
                    self.runs.finish(run_id, info.status)
                self.bus.publish(
                    RunFinished(
                        workflow_id=self.workflow_id,
                        run_id=run_id,
                        targets=info.targets,
                        n_nodes=info.n_nodes,
                        cached=info.cached,
                        status=info.status,
                        elapsed_ms=(time.perf_counter() - info.started) * 1000.0,
                    )
                )
                self.run_history.append(info)
                del self.run_history[:-50]
                self._current = None
                if self.after_run is not None:
                    with contextlib.suppress(Exception):
                        self.after_run(info)
        return run_id

    def _final_status(self, info: RunInfo, plan: Iterable[str]) -> RunStatus:
        states = {self.records[n].state for n in plan if n in self.records}
        if info.abort or "cancelled" in states:
            return "cancelled"
        if "error" in states:
            return "error"
        return "done"

    async def _execute_plan(self, info: RunInfo, plan: list[str]) -> None:
        pending = list(plan)
        plan_set = set(plan)
        active: dict[asyncio.Task[None], str] = {}
        skipped: set[str] = set()
        gated: set[str] = set()
        while pending or active:
            if info.abort:
                for nid in pending:
                    self.records[nid].state = "dirty"
                pending.clear()
            for nid in list(pending):
                node = self.graph.nodes.get(nid)
                if node is None:
                    pending.remove(nid)
                    continue
                rec = self.records[nid]
                deps = [s for s in node.sources(include_lazy=False) if s in plan_set]
                if any(
                    self.records[d].state in ("error", "cancelled") or d in skipped or d in gated
                    for d in deps
                ):
                    pending.remove(nid)
                    skipped.add(nid)
                    if any(d in gated or self.records[d].stale for d in deps):
                        rec.stale = True
                        self._emit_status(nid)
                    continue
                if any(self.records[d].state != "done" for d in deps):
                    continue
                pending.remove(nid)
                cached = self.cache.lookup(rec.key)
                if cached is not None:
                    self._finish_cached(info, nid, cached)
                    continue
                if info.auto and self._effective_cost(node) == "expensive":
                    gated.add(nid)
                    rec.stale = True
                    rec.cost_class = "expensive"
                    self._emit_status(nid)
                    continue
                task = self._launch(info.run_id, node)
                active[task] = nid
            if not active:
                break
            done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                active.pop(task)

    def _launch(self, run_id: str, node: ExecNode) -> asyncio.Task[None]:
        existing = self._tasks.get(node.id)
        if existing is not None and not existing.done():
            return existing
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._execute_node(run_id, node))
        self._tasks[node.id] = task
        return task

    def _finish_cached(self, info: RunInfo, nid: str, outputs: dict[str, PortType]) -> None:
        rec = self.records[nid]
        rec.state, rec.cache_hit, rec.elapsed_ms, rec.run_id = "done", True, 0.0, info.run_id
        rec.stale = False
        info.cached += 1
        self._emit_status(nid)
        self._emit_summaries(nid, outputs)
        self._record(info.run_id, nid, rec)

    async def _execute_node(self, run_id: str, node: ExecNode) -> None:
        nid = node.id
        rec = self.records[nid]
        rec.state, rec.run_id, rec.cache_hit, rec.stale = "queued", run_id, False, False
        self._emit_status(nid)
        cancel_event = threading.Event()
        self._cancel_events[nid] = cancel_event
        started = time.perf_counter()
        key_at_start = rec.key
        try:
            node_def = self.registry.get(node.type)
            rec.state = "running"
            self._emit_status(nid)
            inputs = self._resolve_inputs(node)
            outputs = await self._invoke(run_id, node, node_def, inputs, cancel_event)
            rec.elapsed_ms = (time.perf_counter() - started) * 1000.0
            if not outputs or all(self._blobbable(v) for v in outputs.values()):
                self.cache.store(rec.key, node.type, outputs)
            else:
                self.cache.store(rec.key, node.type, outputs)
            rec.state = "done"
            self._emit_status(nid)
            self._emit_summaries(nid, outputs)
            self._update_stats(node, rec)
        except asyncio.CancelledError:
            # Superseded by an edit (key changed): stay dirty for the next run.
            rec.state = "dirty" if rec.key != key_at_start else "cancelled"
            rec.elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._emit_status(nid)
        except Exception as exc:  # noqa: BLE001 - every node failure becomes an event
            rec.state = "error"
            rec.error = f"{type(exc).__name__}: {exc}"
            rec.elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.bus.publish(
                NodeErrorEvent(
                    workflow_id=self.workflow_id,
                    node_id=nid,
                    message=rec.error,
                    traceback=traceback.format_exc(),
                    hint=_hint(exc),
                )
            )
            self._emit_status(nid)
        finally:
            self._tasks.pop(nid, None)
            self._cancel_events.pop(nid, None)
            self._record(run_id, nid, rec)

    @staticmethod
    def _blobbable(value: PortType) -> bool:
        return value.type_id() != "astro.Any"

    def _resolve_inputs(self, node: ExecNode) -> dict[str, PortType]:
        values: dict[str, PortType] = {}
        for port, (src, sport) in node.inputs.items():
            if port in node.lazy:
                continue
            values[port] = self._upstream_value(src, sport)
        return values

    def _upstream_value(self, src: str, sport: str) -> PortType:
        rec = self.records.get(src)
        outputs = self.cache.lookup(rec.key) if rec is not None and rec.key else None
        if outputs is None or sport not in outputs:
            raise UpstreamMissingError(f"output {src}.{sport} is not available")
        return outputs[sport]

    async def _invoke(
        self,
        run_id: str,
        node: ExecNode,
        node_def: NodeDef,
        inputs: dict[str, PortType],
        cancel_event: threading.Event,
    ) -> dict[str, PortType]:
        rec = self.records[node.id]
        cost = self._effective_cost(node)
        rec.cost_class = cost
        scratch = self.scratch_root / run_id / node.id.replace("/", "_")
        if (
            cost == "expensive"
            and self.processes is not None
            and self.config.use_processes
            and not node_def.spec.is_async
            and not node_def.spec.expand
            and self._process_refs(node) is not None
        ):
            return await self._invoke_process(run_id, node, node_def, scratch)
        params = dict(node.params)
        # Lazy ports are handed ``None``; the node fetches them through ``ctx.needs(port)``.
        call_inputs: dict[str, Any] = {port: None for port in node.lazy if port in node.inputs}
        for port, value in inputs.items():
            if port in node.linked:
                params[port] = unwrap_linked(value)
            else:
                call_inputs[port] = value
        ctx = EngineContext(
            bus=self.bus,
            workflow_id=self.workflow_id,
            node_id=node.id,
            workspace=self.workspace_root,
            scratch_dir=scratch,
            resolver=lambda port: self._resolve_lazy_sync(run_id, node, port),
            cancel_event=cancel_event,
        )
        result = await self.threads.run(ThreadJob(node_def, call_inputs, params, ctx))
        if node_def.spec.expand:
            expansion = (
                result if isinstance(result, Expansion) else Expansion.model_validate(result)
            )
            return await self._run_expansion(run_id, node, node_def, expansion, inputs)
        return wrap_outputs(node_def, result, self.registry.types)

    def _process_refs(self, node: ExecNode) -> dict[str, OutputRef] | None:
        """Blob refs for every connected input, or ``None`` if one is memory-only."""
        refs: dict[str, OutputRef] = {}
        for port, (src, sport) in node.inputs.items():
            rec = self.records.get(src)
            if rec is None or rec.state != "done":
                if port in node.lazy:
                    continue
                return None
            upstream = self.cache.refs(rec.key)
            if upstream is None or sport not in upstream:
                return None
            refs[port] = upstream[sport]
        return refs

    async def _invoke_process(
        self, run_id: str, node: ExecNode, node_def: NodeDef, scratch: Path
    ) -> dict[str, PortType]:
        assert self.processes is not None
        for port in node.lazy:
            if port in node.inputs:
                await self._ensure(run_id, node.inputs[port][0])
        refs = self._process_refs(node) or {}
        job = WorkerJob(
            node_id=node.id,
            node_type=node.type,
            params=dict(node.params),
            token=f"{run_id}:{node.id}",
            input_refs={p: r for p, r in refs.items() if p not in node.lazy},
            linked=node.linked,
            lazy_refs={p: r for p, r in refs.items() if p in node.lazy},
            blob_root=self.cache.blobs.root,
            workspace=self.workspace_root,
            scratch_dir=scratch,
            registry_factory=self.config.registry_factory,
        )
        ctx = EngineContext(
            bus=self.bus,
            workflow_id=self.workflow_id,
            node_id=node.id,
            workspace=self.workspace_root,
            scratch_dir=scratch,
        )

        def on_event(kind: str, payload: dict[str, Any]) -> None:
            if kind == "progress":
                ctx.progress(float(payload.get("frac", 0.0)), payload.get("message"))
            elif kind == "log":
                ctx.log(
                    str(payload.get("level", "info")),
                    str(payload.get("message", "")),
                    **dict(payload.get("fields") or {}),
                )
            elif kind == "preview":
                ctx.preview(dict(payload.get("summary") or {}))

        result = await self.processes.run(job, on_event=on_event)
        rec = self.records[node.id]
        adopted = {port: dataclasses.replace(ref, key=rec.key) for port, ref in result.refs.items()}
        return self.cache.adopt(rec.key, adopted)

    async def _run_expansion(
        self,
        run_id: str,
        parent: ExecNode,
        parent_def: NodeDef,
        expansion: Expansion,
        parent_inputs: dict[str, PortType],
    ) -> dict[str, PortType]:
        parent_key = self.records[parent.id].key
        results: dict[str, dict[str, PortType]] = {}
        for sub_id in _expansion_order(expansion):
            sub = expansion.nodes[sub_id]
            full_id = f"{parent.id}/{sub_id}"
            key = sub_key(parent_key, sub_id)
            sub_def = self.registry.get(sub.type)
            rec = self.records.setdefault(full_id, NodeRecord(key=key))
            rec.key, rec.run_id = key, run_id
            cached = self.cache.lookup(key)
            if cached is not None:
                results[sub_id] = cached
                rec.state, rec.cache_hit = "done", True
                self._emit_status(full_id)
                continue
            rec.state, rec.cache_hit = "running", False
            self._emit_status(full_id)
            params = dict(sub.params)
            inputs: dict[str, Any] = {}
            port_names = set(sub_def.input_names)
            for port, (src, sport) in sub.inputs.items():
                value = parent_inputs[sport] if src == Expansion.PARENT else results[src][sport]
                if port in port_names:
                    inputs[port] = value
                else:
                    params[port] = unwrap_linked(value)
            ctx = EngineContext(
                bus=self.bus,
                workflow_id=self.workflow_id,
                node_id=full_id,
                workspace=self.workspace_root,
                scratch_dir=self.scratch_root / run_id / full_id.replace("/", "_"),
                cancel_event=self._cancel_events.get(parent.id),
            )
            started = time.perf_counter()
            raw = await self.threads.run(ThreadJob(sub_def, inputs, params, ctx))
            outputs = wrap_outputs(sub_def, raw, self.registry.types)
            self.cache.store(key, sub.type, outputs)
            results[sub_id] = outputs
            rec.state, rec.elapsed_ms = "done", (time.perf_counter() - started) * 1000.0
            self._emit_status(full_id)
        declared = {o.name: o.type for o in parent_def.spec.outputs}
        final: dict[str, PortType] = {}
        for port, (src, sport) in expansion.outputs.items():
            if port not in declared:
                raise OutputError(f"{parent.type}: expansion maps unknown output {port!r}")
            final[port] = coerce(results[src][sport], declared[port], self.registry.types)
        return final

    # --- lazy inputs -------------------------------------------------------------------------

    def _resolve_lazy_sync(self, run_id: str, node: ExecNode, port: str) -> Any:
        """Called from a node thread: compute the lazy upstream on the loop and return it."""
        if port not in node.inputs:
            raise KeyError(f"lazy input {port!r} is not connected")
        src, sport = node.inputs[port]
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(self._ensure(run_id, src), self._loop)
        outputs = future.result()
        value = outputs[sport]
        return unwrap_linked(value) if port in node.linked else value

    async def _ensure(self, run_id: str, nid: str) -> dict[str, PortType]:
        """Make sure ``nid`` (and its ancestors) have outputs; returns them."""
        needed = [n for n in self.graph.order if n == nid or n in self.graph.ancestors([nid])]
        for anc in needed:
            rec = self.records[anc]
            if rec.state == "done" and self.cache.lookup(rec.key) is not None:
                continue
            task = self._tasks.get(anc)
            if task is None or task.done():
                cached = self.cache.lookup(rec.key)
                if cached is not None:
                    rec.state = "done"
                    rec.cache_hit = True
                    self._emit_status(anc)
                    self._emit_summaries(anc, cached)
                    continue
                task = self._launch(run_id, self.graph.nodes[anc])
            await task
            if self.records[anc].state != "done":
                raise UpstreamMissingError(f"upstream node {anc} did not finish: {rec.error}")
        outputs = self.cache.lookup(self.records[nid].key)
        if outputs is None:
            raise UpstreamMissingError(f"outputs of {nid} are not available")
        return outputs

    # --- cancellation ------------------------------------------------------------------------

    def cancel(self, *, run_id: str | None = None, node_id: str | None = None) -> bool:
        """Cancel one node or the whole current run. Returns whether anything was cancelled."""
        if node_id is not None:
            return self._cancel_node(node_id)
        info = self._current
        if info is None or (run_id is not None and info.run_id != run_id):
            return False
        info.abort = True
        cancelled = False
        for nid in list(self._tasks):
            cancelled |= self._cancel_node(nid)
        return True if not self._tasks else cancelled

    def _cancel_node(self, node_id: str) -> bool:
        event = self._cancel_events.get(node_id)
        if event is not None:
            event.set()
        task = self._tasks.get(node_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def close(self) -> None:
        if self._debounce is not None:
            self._debounce.cancel()
        if self._current is not None:
            self._current.abort = True
        for nid in list(self._tasks):
            self._cancel_node(nid)
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        if self._background:
            await asyncio.gather(*self._background, return_exceptions=True)

    # --- events / persistence ----------------------------------------------------------------

    def _status_event(self, nid: str) -> NodeStatus:
        rec = self.records[nid]
        return NodeStatus(
            workflow_id=self.workflow_id,
            node_id=nid,
            state=rec.state,
            run_id=rec.run_id,
            cache_hit=rec.cache_hit,
            elapsed_ms=rec.elapsed_ms,
            cost_class=rec.cost_class,
            stale=rec.stale,
        )

    def _emit_status(self, nid: str) -> None:
        self.bus.publish(self._status_event(nid))

    def _emit_summaries(self, nid: str, outputs: dict[str, PortType]) -> None:
        for port, value in outputs.items():
            try:
                summary = value.summary()
            except Exception as exc:  # noqa: BLE001 - previews must never break a run
                summary = {"type": value.type_id(), "error": str(exc)}
            self.bus.publish(
                NodeOutputSummary(
                    workflow_id=self.workflow_id,
                    node_id=nid,
                    port=port,
                    type_id=value.type_id(),
                    summary=summary,
                )
            )

    def _update_stats(self, node: ExecNode, rec: NodeRecord) -> None:
        if rec.elapsed_ms is None:
            return
        average = self.stats.record(node.id, rec.elapsed_ms, rec.cost_class)
        if node.cost == "auto":
            rec.cost_class = "expensive" if average > self.config.auto_threshold_ms else "cheap"

    def _record(self, run_id: str, nid: str, rec: NodeRecord) -> None:
        if self.runs is None:
            return
        from astro_canvas.store.runs import NodeRunRecord  # noqa: PLC0415 - avoid import cycle

        with contextlib.suppress(Exception):
            self.runs.record(
                run_id,
                NodeRunRecord(
                    node_id=nid,
                    key=rec.key,
                    status=rec.state,
                    elapsed_ms=rec.elapsed_ms,
                    cache_hit=rec.cache_hit,
                    error=rec.error,
                ),
            )


def _expansion_order(expansion: Expansion) -> list[str]:
    remaining = dict(expansion.nodes)
    order: list[str] = []
    while remaining:
        ready = sorted(
            sid
            for sid, sub in remaining.items()
            if all(src == Expansion.PARENT or src in order for src, _ in sub.inputs.values())
        )
        if not ready:
            raise OutputError("expansion contains a cycle")
        order.extend(ready)
        for sid in ready:
            del remaining[sid]
    return order


def _hint(exc: BaseException) -> str | None:
    if isinstance(exc, ValidationError):
        return "Check the node's parameters against its schema."
    if isinstance(exc, BlobError):
        return "This value cannot be serialized; astro.Any outputs need cheap (in-process) nodes."
    if isinstance(exc, UpstreamMissingError):
        return "Run the upstream node first or reconnect the input."
    if isinstance(exc, TimeoutError):
        return "The node exceeded the configured time limit."
    if isinstance(exc, OutputError):
        return "The node returned a value that does not match its declared outputs."
    return None


Runner = Callable[[Sequence[str] | None], Any]
