"""Engine test fixtures: a registry with test nodes and a scheduler factory."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

from astro_canvas.engine.cache import BlobStore, MemoryLRU, OutputCache, OutputIndex
from astro_canvas.engine.events import EventBus
from astro_canvas.engine.executors import ProcessExecutor, ThreadExecutor
from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.engine.scheduler import Scheduler, SchedulerConfig
from astro_canvas.sdk import NodeRegistry
from astro_canvas.store.runs import MemoryStats, RunStore
from astro_canvas.store.workspace import Workspace

WORKFLOWS = Path(__file__).resolve().parents[1] / "fixtures" / "workflows"
REGISTRY_FACTORY = "tests.engine.nodes:build_registry"


def load_doc(name: str) -> WorkflowDoc:
    """``tests/fixtures/workflows/<name>.json`` as a document."""
    return WorkflowDoc.model_validate_json((WORKFLOWS / f"{name}.json").read_text(encoding="utf-8"))


def load_expected(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (WORKFLOWS / "expected" / f"{name}.json").read_text(encoding="utf-8")
    )
    return data


def make_doc(
    nodes: dict[str, Any], edges: dict[str, Any] | None = None, **extra: Any
) -> WorkflowDoc:
    return WorkflowDoc.model_validate(
        {"id": extra.pop("id", "wf"), "nodes": nodes, "edges": edges or {}, **extra}
    )


class Harness:
    """A scheduler wired to a temp workspace with an event-recording bus."""

    def __init__(self, tmp_path: Path, registry: NodeRegistry, *, processes: bool) -> None:
        self.workspace = Workspace(tmp_path / "ws")
        self.registry = registry
        self.index = OutputIndex(self.workspace.sessions)
        self.cache = OutputCache(
            memory=MemoryLRU(256 * 1024 * 1024),
            blobs=BlobStore(self.workspace.blobs_dir),
            index=self.index,
            types=registry.types,
        )
        self.bus = EventBus()
        self.bus.keep_history = 10_000
        self.threads = ThreadExecutor(4)
        self.processes = ProcessExecutor(max_workers=1) if processes else None
        self.stats = MemoryStats()
        self.runs = RunStore(self.workspace.sessions)
        self.schedulers: list[Scheduler] = []

    def scheduler(self, doc: WorkflowDoc | None = None, **config: Any) -> Scheduler:
        cfg = SchedulerConfig(debounce_s=0.05, registry_factory=REGISTRY_FACTORY, **config)
        scheduler = Scheduler(
            registry=self.registry,
            cache=self.cache,
            bus=self.bus,
            workspace_root=self.workspace.root,
            scratch_root=self.workspace.scratch_dir,
            threads=self.threads,
            processes=self.processes,
            stats=self.stats,
            runs=self.runs,
            config=cfg,
            workflow_id=doc.id if doc else "wf",
        )
        self.schedulers.append(scheduler)
        if doc is not None:
            scheduler.update(doc)
        return scheduler

    def events(self, kind: str | None = None, node_id: str | None = None) -> list[Any]:
        out = []
        for event in self.bus.history:
            if kind is not None and event.type != kind:
                continue
            if node_id is not None and getattr(event, "node_id", None) != node_id:
                continue
            out.append(event)
        return out

    def states(self, node_id: str) -> list[str]:
        return [e.state for e in self.events("node.status", node_id)]

    async def close(self) -> None:
        for scheduler in self.schedulers:
            await scheduler.close()
        self.threads.shutdown()
        if self.processes is not None:
            self.processes.shutdown()
        self.workspace.close()


@pytest.fixture
async def harness(tmp_path: Path, registry: NodeRegistry) -> AsyncIterator[Harness]:
    h = Harness(tmp_path, registry, processes=False)
    h.bus.bind(asyncio.get_running_loop())
    yield h
    await h.close()


@pytest.fixture
async def process_harness(tmp_path: Path, registry: NodeRegistry) -> AsyncIterator[Harness]:
    h = Harness(tmp_path, registry, processes=True)
    h.bus.bind(asyncio.get_running_loop())
    yield h
    await h.close()


async def wait_for(predicate: Callable[[], bool], timeout: float = 5.0, step: float = 0.02) -> None:
    """Poll ``predicate`` until true or fail after ``timeout`` seconds."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(step)
