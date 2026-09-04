"""Code that runs inside pebble worker processes.

Inputs arrive as blob references (``OutputRef``), are rehydrated from the shared ``BlobStore``,
the node runs with a ``WorkerContext``, and its outputs are written back to the store so only
references travel through the pipe.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from astro_canvas.engine.cache import BlobStore, OutputRef
from astro_canvas.engine.context import WorkerContext
from astro_canvas.engine.outputs import unwrap_linked, wrap_outputs
from astro_canvas.sdk import NodeRegistry, PortType, discover


@dataclass
class WorkerJob:
    """Everything a worker needs to run one node (must pickle)."""

    node_id: str
    node_type: str
    params: dict[str, Any]
    token: str
    input_refs: dict[str, OutputRef]
    linked: frozenset[str]
    lazy_refs: dict[str, OutputRef]
    blob_root: Path
    workspace: Path
    scratch_dir: Path
    registry_factory: str = "astro_canvas.engine.worker:default_registry"
    inline_inputs: dict[str, Any] = field(default_factory=dict)
    """Small JSON-safe inputs (linked scalar params) that need no blob round trip."""


@dataclass
class WorkerResult:
    refs: dict[str, OutputRef]
    elapsed_ms: float


_registry_cache: dict[str, NodeRegistry] = {}


def default_registry() -> NodeRegistry:
    return discover().registry


def load_registry(factory: str) -> NodeRegistry:
    """Import ``module:callable`` once per process and cache the registry it builds."""
    registry = _registry_cache.get(factory)
    if registry is None:
        module_name, _, attr = factory.partition(":")
        target: Callable[[], NodeRegistry] = getattr(importlib.import_module(module_name), attr)
        registry = target()
        _registry_cache[factory] = registry
    return registry


def rehydrate(
    refs: Mapping[str, OutputRef], blobs: BlobStore, registry: NodeRegistry
) -> dict[str, PortType]:
    """Load inputs from the shared blob store, memory-mapping whatever the type marks mappable."""
    return {
        port: registry.types.get(ref.type_id).from_blob_file(blobs.path(ref.blob_hash))
        for port, ref in refs.items()
    }


def run_job(job: WorkerJob, events: Any = None) -> WorkerResult:
    """Entry point scheduled on the pebble pool."""
    registry = load_registry(job.registry_factory)
    node_def = registry.get(job.node_type)
    blobs = BlobStore(job.blob_root)
    values = rehydrate(job.input_refs, blobs, registry)
    lazy = rehydrate(job.lazy_refs, blobs, registry)
    inputs: dict[str, Any] = dict.fromkeys(lazy)  # lazy ports arrive as None, see ctx.needs
    params = dict(job.params)
    for port, value in values.items():
        if port in job.linked:
            params[port] = unwrap_linked(value)
        else:
            inputs[port] = value
    for port, value in job.inline_inputs.items():
        if port in job.linked:
            params[port] = value
        else:
            inputs[port] = value
    ctx = WorkerContext(
        node_id=job.token,
        workspace=job.workspace,
        scratch_dir=job.scratch_dir,
        events=events,
        lazy_inputs=lazy,
    )
    started = time.perf_counter()
    result = node_def.call(inputs, params, ctx)
    if inspect.isawaitable(result):
        result = asyncio.run(_await(result))
    outputs = wrap_outputs(node_def, result, registry.types, params)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    refs: dict[str, OutputRef] = {}
    for port, value in outputs.items():
        data = value.to_blob().pack()  # BlobError for astro.Any propagates as a node error
        blob_hash = blobs.put(data)
        refs[port] = OutputRef("", port, value.type_id(), blob_hash, len(data), job.node_type)
    return WorkerResult(refs=refs, elapsed_ms=elapsed_ms)


async def _await(value: Any) -> Any:
    return await value


__all__ = ["WorkerJob", "WorkerResult", "default_registry", "load_registry", "run_job"]
