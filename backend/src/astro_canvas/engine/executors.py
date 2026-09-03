"""Executors: a thread pool for cheap nodes and a pebble process pool for expensive ones.

Threads cooperate through ``ctx.is_cancelled()``; cancelling a process job kills the worker
(``pebble.ProcessFuture.cancel``). Progress/log/preview events from workers travel through a
``multiprocessing.Manager`` queue pumped by a background thread into ``on_event`` callbacks.
"""

from __future__ import annotations

import asyncio
import inspect
import multiprocessing
import os
import queue
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from pebble import ProcessPool

from astro_canvas.engine.context import EngineContext
from astro_canvas.engine.worker import WorkerJob, WorkerResult, run_job
from astro_canvas.sdk import NodeDef

WorkerEventHandler = Callable[[str, dict[str, Any]], None]
"""``(kind, payload)`` for ``progress`` / ``log`` / ``preview`` events of one job."""


@dataclass
class ThreadJob:
    """One in-process node call."""

    node_def: NodeDef
    inputs: dict[str, Any]
    params: dict[str, Any]
    ctx: EngineContext


class ThreadExecutor:
    """Runs ``NodeDef.call`` on a thread pool; async nodes are awaited on the event loop."""

    def __init__(self, max_workers: int | None = None) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers or min(32, (os.cpu_count() or 1) + 4),
            thread_name_prefix="astro-node",
        )

    async def run(self, job: ThreadJob) -> Any:
        """Return the node's raw result; a cancelled await sets the context's cancel flag."""
        if job.node_def.spec.is_async:
            result = job.node_def.call(job.inputs, job.params, job.ctx)
            return await result if inspect.isawaitable(result) else result
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._pool, self._call, job)
        try:
            return await future
        except asyncio.CancelledError:
            job.ctx.cancel_event.set()
            raise

    @staticmethod
    def _call(job: ThreadJob) -> Any:
        result = job.node_def.call(job.inputs, job.params, job.ctx)
        if inspect.isawaitable(result):
            result = asyncio.run(_await(result))
        return result

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


async def _await(value: Any) -> Any:
    return await value


@dataclass
class ProcessExecutor:
    """pebble ``ProcessPool`` started lazily on first use."""

    max_workers: int = field(default_factory=lambda: max(1, (os.cpu_count() or 2) - 1))
    _pool: ProcessPool | None = field(default=None, init=False, repr=False)
    _manager: Any = field(default=None, init=False, repr=False)
    _queue: Any = field(default=None, init=False, repr=False)
    _handlers: dict[str, WorkerEventHandler] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _pump: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    @property
    def started(self) -> bool:
        return self._pool is not None

    def start(self) -> None:
        with self._lock:
            if self._pool is not None:
                return
            self._manager = multiprocessing.Manager()
            self._queue = self._manager.Queue()
            self._pool = ProcessPool(max_workers=self.max_workers)
            self._stop.clear()
            self._pump = threading.Thread(
                target=self._pump_events, name="astro-worker-events", daemon=True
            )
            self._pump.start()

    def _pump_events(self) -> None:
        while not self._stop.is_set():
            try:
                kind, token, payload = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            except (EOFError, OSError, ConnectionError):  # manager gone
                return
            handler = self._handlers.get(str(token))
            if handler is not None:
                handler(str(kind), dict(payload))

    async def run(
        self,
        job: WorkerJob,
        *,
        on_event: WorkerEventHandler | None = None,
        timeout: float | None = None,
    ) -> WorkerResult:
        """Run ``job`` in a worker; cancelling the awaiting task kills the worker."""
        self.start()
        assert self._pool is not None
        if on_event is not None:
            self._handlers[job.token] = on_event
        future = self._pool.schedule(run_job, args=(job, self._queue), timeout=timeout)
        try:
            result: WorkerResult = await asyncio.wrap_future(future)
            return result
        except asyncio.CancelledError:
            future.cancel()
            raise
        finally:
            self._handlers.pop(job.token, None)

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
            manager, self._manager = self._manager, None
        self._stop.set()
        if pool is not None:
            pool.stop()
            pool.join(timeout=timeout)
        if manager is not None:
            manager.shutdown()


def process_pool_default_workers(env: Mapping[str, str] | None = None) -> int:
    """``ASTRO_CANVAS_MAX_WORKERS`` or ``cpu_count - 1`` (at least 1)."""
    raw = (env if env is not None else os.environ).get("ASTRO_CANVAS_MAX_WORKERS")
    if raw and raw.isdigit() and int(raw) > 0:
        return int(raw)
    return max(1, (os.cpu_count() or 2) - 1)
