"""Run one node body with candidate parameters outside the scheduler (editor live previews).

Nothing here touches the cache, the run history or the event bus: the caller receives the wrapped
outputs and decides what to do with them (the WebSocket session summarises them with a ``tag``).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from astro_canvas.engine.outputs import unwrap_linked, wrap_outputs
from astro_canvas.engine.scheduler import Scheduler
from astro_canvas.sdk import NodeRegistry, NullContext, PortType


class PreviewError(ValueError):
    """The preview request cannot be served (unknown node, expanding node, ...)."""


def compute_preview(
    scheduler: Scheduler,
    registry: NodeRegistry,
    *,
    node_id: str | None = None,
    node_type: str | None = None,
    params: Mapping[str, Any] | None = None,
    workspace: Path | None = None,
) -> tuple[str, dict[str, PortType]]:
    """Call a node with ``params`` layered over the document's values; returns ``(type, outputs)``.

    With ``node_id`` the inputs are the cached outputs of the node's upstream neighbours in
    ``scheduler`` (``UpstreamMissingError`` when one is not computed yet). With ``node_type`` the
    node runs on params alone (for nodes without inputs, e.g. a line-list lookup).
    """
    root = workspace if workspace is not None else scheduler.workspace_root
    overrides = dict(params or {})
    if node_id is not None:
        node = scheduler.graph.nodes.get(node_id)
        if node is None:
            raise PreviewError(f"node {node_id!r} is not part of the executable graph")
        node_def = registry.get(node.type)
        if node_def.spec.expand:
            raise PreviewError(f"{node.type} expands into a sub-graph and cannot be previewed")
        merged = {**node.params, **overrides}
        call_inputs: dict[str, Any] = {}
        lazy: dict[str, Any] = {}
        for port, value in scheduler.resolve_inputs(node_id).items():
            if port in node.linked:
                if port not in overrides:
                    merged[port] = unwrap_linked(value)
            elif port in node.lazy:
                lazy[port] = value
                call_inputs[port] = None
            else:
                call_inputs[port] = value
        ctx = NullContext(workspace=Path(root), inputs=lazy)
        result = node_def.call(call_inputs, merged, ctx)
    elif node_type is not None:
        node_def = registry.get(node_type)
        if node_def.spec.expand or node_def.input_names:
            raise PreviewError(f"{node_type} needs inputs; preview it through a node instance")
        result = node_def.call({}, overrides, NullContext(workspace=Path(root)))
    else:
        raise PreviewError("preview.compute needs node_id or node_type")
    if inspect.isawaitable(result):
        result = asyncio.run(_await(result))
    return node_def.spec.id, wrap_outputs(node_def, result, registry.types)


async def _await(value: Any) -> Any:
    return await value


__all__ = ["PreviewError", "compute_preview"]
