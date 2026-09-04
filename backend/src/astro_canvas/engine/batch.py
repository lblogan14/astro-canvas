"""Batch runner (design 8.4): run one workflow over a table of inputs.

Each row binds columns to node params (usually *promoted* ones), the body runs with those
params, and chosen node outputs are flattened into a results row. Rows execute through ordinary
``Scheduler`` instances that share the process-wide ``OutputCache`` and executors, so:

* row cache keys fall out of the params that differ — two rows that agree on a prefix of the
  graph share those cached outputs, and re-running an unchanged row is free;
* expensive nodes still run in the process pool and cancel by killing their worker;
* per-row events are published as ``batch.row`` while node-level chatter stays on a private bus
  so a 200-row batch does not repaint the canvas.
"""

from __future__ import annotations

import asyncio
import math
import os
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import structlog
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from astro_canvas.engine.cache import OutputCache
from astro_canvas.engine.events import (
    BatchFinished,
    BatchRowEvent,
    BatchStarted,
    EventBus,
    RunStatus,
)
from astro_canvas.engine.executors import ProcessExecutor, ThreadExecutor
from astro_canvas.engine.graph import WorkflowDoc, as_graph, compile
from astro_canvas.engine.scheduler import Scheduler, SchedulerConfig
from astro_canvas.sdk import NodeRegistry, PortType, UnknownNodeError
from astro_canvas.store.runs import MemoryStats

log = structlog.get_logger("astro_canvas.batch")

RowState = Literal["pending", "queued", "running", "done", "error", "cancelled"]

STATUS_COLUMN = "status"
ERROR_COLUMN = "error_message"
TIMESTAMP_COLUMN = "calculation_timestamp"
"""Result bookkeeping columns, named after rbcodes' ``master_batch_table``."""

DEFAULT_CHEAP_WORKERS = 8
MAX_ROWS = 5000
KEEP_BATCHES = 20
"""Finished batches kept for polling; older ones are forgotten so the server does not grow."""


# --- specification -----------------------------------------------------------------------------


class BatchBinding(BaseModel):
    """One table column feeding one node param (``layouts.batch.columns`` entry)."""

    model_config = ConfigDict(frozen=True)

    node: str
    param: str
    column: str

    @property
    def ref(self) -> str:
        return f"{self.node}.{self.param}"


class BatchCollect(BaseModel):
    """One node output gathered into the results table."""

    model_config = ConfigDict(frozen=True)

    node: str
    port: str
    prefix: str | None = Field(
        default=None,
        description="Column prefix; defaults to none for a single collect and '<node>.' "
        "when several outputs are gathered.",
    )

    @property
    def ref(self) -> str:
        return f"{self.node}.{self.port}"


class BatchSpec(BaseModel):
    """What to vary and what to keep from a batch run."""

    bindings: list[BatchBinding] = Field(default_factory=list)
    collect: list[BatchCollect] = Field(default_factory=list)
    max_workers: int | None = Field(
        default=None, description="Rows in flight; default cpu-1 with expensive nodes, else 8."
    )
    continue_on_error: bool = True


def spec_from_layout(layout: Mapping[str, Any]) -> BatchSpec:
    """Build a ``BatchSpec`` from a document's ``layouts.batch`` section (design 7.1).

    ``columns`` entries are ``{"promoted": "<node>.<param>", "column": "<name>"}`` (the column
    defaults to the promoted ref) and ``collect`` entries are ``"<node>.<port>"`` strings or
    ``{"node", "port", "prefix"}`` objects.
    """
    bindings: list[BatchBinding] = []
    for entry in layout.get("columns") or []:
        if isinstance(entry, str):
            ref, column = entry, entry
        else:
            ref = str(entry.get("promoted") or f"{entry.get('node')}.{entry.get('param')}")
            column = str(entry.get("column") or ref)
        node, _, param = ref.partition(".")
        if node and param:
            bindings.append(BatchBinding(node=node, param=param, column=column))
    collect: list[BatchCollect] = []
    for entry in layout.get("collect") or []:
        if isinstance(entry, str):
            node, _, port = entry.partition(".")
            prefix = None
        else:
            node, port = str(entry.get("node", "")), str(entry.get("port", ""))
            prefix = entry.get("prefix")
        if node and port:
            collect.append(BatchCollect(node=node, port=port, prefix=prefix))
    return BatchSpec(
        bindings=bindings,
        collect=collect,
        max_workers=layout.get("max_workers"),
        continue_on_error=bool(layout.get("continue_on_error", True)),
    )


# --- results -----------------------------------------------------------------------------------


def flatten_value(value: PortType, prefix: str = "", *, depth: int = 2) -> dict[str, Any]:
    """Scalar fields of a port value as flat columns (``EWMeasurement`` -> ``W``, ``W_e``, ...).

    Arrays and lists are skipped: a results table holds one cell per column. Nested models are
    walked ``depth`` levels deep with dotted names (``transition.wrest``).
    """
    out: dict[str, Any] = {}

    def walk(data: Mapping[str, Any], head: str, left: int) -> None:
        for name, item in data.items():
            key = f"{head}{name}"
            if isinstance(item, bool | str) or item is None:
                out[key] = item
            elif isinstance(item, int | float):
                out[key] = float(item) if isinstance(item, float) else item
            elif isinstance(item, np.generic):
                out[key] = item.item()
            elif isinstance(item, Mapping) and left > 0:
                walk(item, f"{key}.", left - 1)

    walk(value.model_dump(mode="python"), prefix, depth)
    return out


def _column_prefixes(collect: Sequence[BatchCollect]) -> list[str]:
    """Explicit prefixes win; otherwise prefix by node id only when several outputs collide."""
    return [
        c.prefix if c.prefix is not None else ("" if len(collect) == 1 else f"{c.node}.")
        for c in collect
    ]


def _as_column(values: Sequence[Any]) -> Any:
    """A numpy column for mixed Python values (numbers keep NaN for missing cells)."""
    present = [v for v in values if v is not None]
    if present and all(isinstance(v, bool) for v in present) and len(present) == len(values):
        return np.asarray(values, dtype=bool)
    if present and all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        if len(present) == len(values):
            return np.asarray(values, dtype=np.int64)
        return np.asarray([math.nan if v is None else float(v) for v in values], dtype=np.float64)
    if present and all(isinstance(v, int | float) and not isinstance(v, bool) for v in present):
        return np.asarray([math.nan if v is None else float(v) for v in values], dtype=np.float64)
    return np.asarray(["" if v is None else str(v) for v in values], dtype=np.str_)


class BatchResults(BaseModel):
    """The results grid: one row per input row, JSON-safe so it can travel over REST."""

    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)

    def to_table(self, registry: NodeRegistry) -> PortType:
        """The same grid as an ``astro.Table`` (for ``core.io.save_table`` and the CLI)."""
        table_cls = registry.types.get("astro.Table")
        columns = {name: _as_column([row.get(name) for row in self.rows]) for name in self.columns}
        return table_cls.model_validate({"columns": columns})


# --- run state ---------------------------------------------------------------------------------


@dataclass
class BatchRowRecord:
    index: int
    state: RowState = "pending"
    error: str | None = None
    elapsed_ms: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchRun:
    """One batch execution: its rows, their states and the assembled results."""

    batch_id: str
    workflow_id: str
    spec: BatchSpec
    records: list[BatchRowRecord]
    status: RunStatus = "running"
    started: float = field(default_factory=time.time)
    finished: float | None = None
    message: str | None = None
    abort: bool = False
    _schedulers: dict[int, Scheduler] = field(default_factory=dict, repr=False)

    @property
    def n_rows(self) -> int:
        return len(self.records)

    def counts(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for record in self.records:
            totals[record.state] = totals.get(record.state, 0) + 1
        return totals

    def results(self) -> BatchResults:
        """Input columns, collected columns, then ``status``/``error_message``/timestamp."""
        columns: list[str] = []
        for record in self.records:
            for name in [*record.inputs, *record.outputs]:
                if name not in columns and name != TIMESTAMP_COLUMN:
                    columns.append(name)
        columns += [STATUS_COLUMN, ERROR_COLUMN, TIMESTAMP_COLUMN]
        rows = [
            {
                **record.inputs,
                **record.outputs,
                STATUS_COLUMN: record.state,
                ERROR_COLUMN: record.error or "",
                TIMESTAMP_COLUMN: record.outputs.get(TIMESTAMP_COLUMN, ""),
            }
            for record in self.records
        ]
        return BatchResults(columns=columns, rows=rows)


class BatchCancelled(RuntimeError):
    """The batch was cancelled before or while this row ran."""


# --- runner ------------------------------------------------------------------------------------


def coerce_cell(registry: NodeRegistry, node_type: str, param: str, value: Any) -> Any:
    """Widen a table cell to the param's declared type.

    Cells arriving from a CSV or a pasted table are strings; a param annotated ``float`` must
    receive ``1.3855``, not ``"1.3855"``. A value the param model rejects is passed through
    untouched so the compiler reports it as ``bad_param`` on that node.
    """
    if not isinstance(value, str):
        return value
    try:
        field = registry.get(node_type).params_model.model_fields[param]
        return TypeAdapter(field.annotation).validate_python(value)
    except (LookupError, UnknownNodeError, ValidationError, TypeError):
        return value


def bind_row(
    doc: WorkflowDoc, spec: BatchSpec, row: Mapping[str, Any], registry: NodeRegistry | None = None
) -> WorkflowDoc:
    """A copy of ``doc`` with this row's columns written into the bound node params."""
    variant = doc.model_copy(deep=True)
    for binding in spec.bindings:
        if binding.column not in row:
            continue
        node = variant.nodes.get(binding.node)
        if node is None:
            continue
        value = row[binding.column]
        node.params[binding.param] = (
            value if registry is None else coerce_cell(registry, node.type, binding.param, value)
        )
        if binding.param in node.linked:
            node.linked = [name for name in node.linked if name != binding.param]
    return variant


class BatchRunner:
    """Runs workflows over row tables; one instance per ``EngineRuntime``."""

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
        config: Callable[[], SchedulerConfig] | None = None,
    ) -> None:
        self.registry = registry
        self.cache = cache
        self.bus = bus
        self.workspace_root = workspace_root
        self.scratch_root = scratch_root
        self.threads = threads
        self.processes = processes
        self._config = config or SchedulerConfig
        self.runs: dict[str, BatchRun] = {}
        self._tasks: dict[str, asyncio.Task[BatchRun]] = {}

    # --- lifecycle ---------------------------------------------------------------------------

    def start(
        self,
        doc: WorkflowDoc,
        rows: Sequence[Mapping[str, Any]],
        spec: BatchSpec,
        *,
        batch_id: str | None = None,
    ) -> BatchRun:
        """Schedule a batch in the background and return its record immediately."""
        run = self._prepare(doc, rows, spec, batch_id)
        loop = asyncio.get_running_loop()
        self.bus.bind(loop)
        self._tasks[run.batch_id] = loop.create_task(self._run(doc, rows, run))
        return run

    async def execute(
        self,
        doc: WorkflowDoc,
        rows: Sequence[Mapping[str, Any]],
        spec: BatchSpec,
        *,
        batch_id: str | None = None,
    ) -> BatchRun:
        """Run a batch to completion (CLI and tests)."""
        run = self._prepare(doc, rows, spec, batch_id)
        self.bus.bind(asyncio.get_running_loop())
        return await self._run(doc, rows, run)

    def _prepare(
        self,
        doc: WorkflowDoc,
        rows: Sequence[Mapping[str, Any]],
        spec: BatchSpec,
        batch_id: str | None,
    ) -> BatchRun:
        if len(rows) > MAX_ROWS:
            raise ValueError(f"a batch is limited to {MAX_ROWS} rows, got {len(rows)}")
        run = BatchRun(
            batch_id=batch_id or uuid.uuid4().hex[:12],
            workflow_id=doc.id,
            spec=spec,
            records=[
                BatchRowRecord(index=i, inputs={k: v for k, v in row.items()})
                for i, row in enumerate(rows)
            ],
        )
        self.runs[run.batch_id] = run
        self._forget_old()
        return run

    def _forget_old(self) -> None:
        """Drop the oldest finished batches once more than ``KEEP_BATCHES`` are remembered."""
        finished = [bid for bid, r in self.runs.items() if r.status != "running"]
        for batch_id in finished[: max(0, len(self.runs) - KEEP_BATCHES)]:
            del self.runs[batch_id]
            self._tasks.pop(batch_id, None)

    def get(self, batch_id: str) -> BatchRun | None:
        return self.runs.get(batch_id)

    def cancel(self, batch_id: str) -> bool:
        """Stop queued rows and cancel every row currently running."""
        run = self.runs.get(batch_id)
        if run is None or run.status != "running":
            return False
        run.abort = True
        for scheduler in list(run._schedulers.values()):
            scheduler.cancel()
        return True

    async def close(self) -> None:
        for batch_id in list(self._tasks):
            self.cancel(batch_id)
        tasks = [t for t in self._tasks.values() if not t.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    # --- execution ---------------------------------------------------------------------------

    def _workers(self, doc: WorkflowDoc, spec: BatchSpec) -> int:
        if spec.max_workers:
            return max(1, spec.max_workers)
        graph = as_graph(compile(doc, self.registry))
        expensive = any(node.cost == "expensive" for node in graph.nodes.values())
        if not expensive:
            return DEFAULT_CHEAP_WORKERS
        return max(1, (os.cpu_count() or 2) - 1)

    async def _run(
        self, doc: WorkflowDoc, rows: Sequence[Mapping[str, Any]], run: BatchRun
    ) -> BatchRun:
        started = time.perf_counter()
        workers = self._workers(doc, run.spec)
        stats = MemoryStats()
        self.bus.publish(
            BatchStarted(
                workflow_id=run.workflow_id,
                batch_id=run.batch_id,
                n_rows=run.n_rows,
                max_workers=workers,
                columns=[b.column for b in run.spec.bindings],
            )
        )
        semaphore = asyncio.Semaphore(workers)

        async def one(index: int) -> None:
            async with semaphore:
                await self._run_row(doc, rows[index], run, run.records[index], stats)

        try:
            await asyncio.gather(*(one(i) for i in range(run.n_rows)))
        finally:
            states = {record.state for record in run.records}
            if run.abort or "cancelled" in states:
                run.status = "cancelled"
            elif "error" in states:
                run.status = "error"
            else:
                run.status = "done"
            run.finished = time.time()
            counts = run.counts()
            self.bus.publish(
                BatchFinished(
                    workflow_id=run.workflow_id,
                    batch_id=run.batch_id,
                    n_rows=run.n_rows,
                    done=counts.get("done", 0),
                    failed=counts.get("error", 0),
                    cancelled=counts.get("cancelled", 0),
                    status=run.status,
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                )
            )
            log.info(
                "batch finished",
                batch_id=run.batch_id,
                rows=run.n_rows,
                status=run.status,
                **counts,
            )
        return run

    def _emit_row(self, run: BatchRun, record: BatchRowRecord) -> None:
        self.bus.publish(
            BatchRowEvent(
                workflow_id=run.workflow_id,
                batch_id=run.batch_id,
                row=record.index,
                state=record.state,
                error=record.error,
                elapsed_ms=record.elapsed_ms,
                outputs=record.outputs,
            )
        )

    async def _run_row(
        self,
        doc: WorkflowDoc,
        row: Mapping[str, Any],
        run: BatchRun,
        record: BatchRowRecord,
        stats: MemoryStats,
    ) -> None:
        if run.abort:
            record.state = "cancelled"
            self._emit_row(run, record)
            return
        record.state = "running"
        self._emit_row(run, record)
        started = time.perf_counter()
        scheduler = self._scheduler(bind_row(doc, run.spec, row, self.registry), stats)
        run._schedulers[record.index] = scheduler
        try:
            targets = [c.node for c in run.spec.collect if c.node in scheduler.graph.nodes]
            await scheduler.run(targets or None)
            record.error = self._row_error(scheduler, run.spec, targets)
            if run.abort:
                record.state = "cancelled"
            elif record.error is not None:
                record.state = "error"
            else:
                record.outputs = self._collect(scheduler, run.spec, set(record.inputs))
                record.outputs[TIMESTAMP_COLUMN] = _now()
                record.state = "done"
        except Exception as exc:  # noqa: BLE001 - one row's failure never stops the batch
            record.state = "error"
            record.error = f"{type(exc).__name__}: {exc}"
        finally:
            record.elapsed_ms = (time.perf_counter() - started) * 1000.0
            run._schedulers.pop(record.index, None)
            await scheduler.close()
            self._emit_row(run, record)
        if record.state == "error" and not run.spec.continue_on_error:
            run.abort = True

    def _scheduler(self, doc: WorkflowDoc, stats: MemoryStats) -> Scheduler:
        """A scheduler on a private bus: node chatter stays out of the canvas subscription."""
        config = self._config()
        scheduler = Scheduler(
            registry=self.registry,
            cache=self.cache,
            bus=EventBus(),
            workspace_root=self.workspace_root,
            scratch_root=self.scratch_root,
            threads=self.threads,
            processes=self.processes,
            stats=stats,
            config=SchedulerConfig(
                debounce_s=config.debounce_s,
                auto_threshold_ms=config.auto_threshold_ms,
                run_timeout_s=config.run_timeout_s,
                use_processes=config.use_processes,
                auto_run=False,
                registry_factory=config.registry_factory,
            ),
            workflow_id=doc.id,
        )
        scheduler.set_auto_run(False)
        scheduler.update(doc)
        return scheduler

    @staticmethod
    def _row_error(scheduler: Scheduler, spec: BatchSpec, targets: Sequence[str]) -> str | None:
        """The first problem that stops this row from producing its collected outputs."""
        for node_id, issues in scheduler.issues.items():
            if issues:
                return f"{node_id}: {issues[0].message}"
        for node_id, record in scheduler.records.items():
            if record.state == "error":
                return f"{node_id}: {record.error}"
        for collect in spec.collect:
            if collect.node not in scheduler.graph.nodes:
                return f"{collect.node}: node is not in the runnable graph"
            if scheduler.output(collect.node, collect.port) is None:
                return f"{collect.ref}: no output was produced"
        if not targets and spec.collect:
            return "no collected node is runnable"
        return None

    @staticmethod
    def _collect(scheduler: Scheduler, spec: BatchSpec, taken: set[str]) -> dict[str, Any]:
        """Collected outputs as columns, qualified when a name clashes with an input column."""
        out: dict[str, Any] = {}
        for collect, prefix in zip(spec.collect, _column_prefixes(spec.collect), strict=True):
            value = scheduler.output(collect.node, collect.port)
            if value is None:
                continue
            for name, item in flatten_value(value, prefix).items():
                column = name
                for candidate in (f"{collect.node}.{name}", f"{collect.ref}.{name}"):
                    if column not in taken and column not in out:
                        break
                    column = candidate
                out[column] = item
        return out


def _now() -> str:
    from datetime import UTC, datetime  # noqa: PLC0415 - only needed per finished row

    return datetime.now(UTC).isoformat(timespec="seconds")
