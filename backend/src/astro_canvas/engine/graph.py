"""``workflow.json`` (format v1, design 7.1) and its compilation into an ``ExecGraph`` (6.1).

``compile`` inlines subgraphs, rewires around disabled nodes, validates node types, edges,
required inputs and params, detects cycles and returns either an ``ExecGraph`` or
``ValidationErrors`` (per-node issues plus the still-executable sub-graph).
"""

from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from astro_canvas.engine.events import NodeIssue
from astro_canvas.sdk import Cost, NodeDef, NodeRegistry, UnknownNodeError

FORMAT = "astro-canvas/workflow"
SUBGRAPH_PREFIX = "subgraph:"
MAX_SUBGRAPH_DEPTH = 8


def new_id() -> str:
    return uuid.uuid4().hex


# --- document ----------------------------------------------------------------------------------


class NodeDoc(BaseModel):
    """One node instance on the canvas."""

    model_config = ConfigDict(extra="allow")

    type: str
    version: str | None = None
    title: str | None = None
    pos: tuple[float, float] | None = None
    size: tuple[float, float] | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    linked: list[str] = Field(default_factory=list)
    ui: dict[str, Any] = Field(default_factory=dict)
    cost: Cost | None = None
    disabled: bool = False
    notes: str = ""


class EdgeDoc(BaseModel):
    """``{"from": [node, port], "to": [node, port]}``."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    source: tuple[str, str] = Field(alias="from")
    target: tuple[str, str] = Field(alias="to")


class GroupDoc(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = ""
    nodes: list[str] = Field(default_factory=list)
    color: str | None = None


class SubgraphPort(BaseModel):
    """An exposed port of a subgraph: ``name`` outside maps to ``node.port`` inside."""

    name: str
    node: str
    port: str


class SubgraphDoc(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""
    nodes: dict[str, NodeDoc] = Field(default_factory=dict)
    edges: dict[str, EdgeDoc] = Field(default_factory=dict)
    inputs: list[SubgraphPort] = Field(default_factory=list)
    outputs: list[SubgraphPort] = Field(default_factory=list)


class PromotedDoc(BaseModel):
    model_config = ConfigDict(extra="allow")

    node: str
    param: str
    label: str | None = None
    group: str | None = None
    order: int = 0


class ViewDoc(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    node: str
    port: str
    kind: str | None = None


class WorkflowDoc(BaseModel):
    """The canvas document. Unknown top-level fields are preserved."""

    model_config = ConfigDict(extra="allow")

    format: Literal["astro-canvas/workflow"] = "astro-canvas/workflow"
    version: Literal[1] = 1
    id: str = Field(default_factory=new_id)
    name: str = "Untitled"
    description: str = ""
    nodes: dict[str, NodeDoc] = Field(default_factory=dict)
    edges: dict[str, EdgeDoc] = Field(default_factory=dict)
    groups: dict[str, GroupDoc] = Field(default_factory=dict)
    subgraphs: dict[str, SubgraphDoc] = Field(default_factory=dict)
    promoted: list[PromotedDoc] = Field(default_factory=list)
    views: list[ViewDoc] = Field(default_factory=list)
    layouts: dict[str, Any] = Field(default_factory=dict)
    requires: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


# --- executable graph --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecNode:
    """A node call with resolved params and wired inputs."""

    id: str
    type: str
    version: str
    params: dict[str, Any]
    inputs: dict[str, tuple[str, str]]
    linked: frozenset[str] = frozenset()
    lazy: frozenset[str] = frozenset()
    cost: Cost = "cheap"
    doc_id: str = ""

    def sources(self, *, include_lazy: bool = True) -> set[str]:
        return {
            src for port, (src, _) in self.inputs.items() if include_lazy or port not in self.lazy
        }


@dataclass
class ExecGraph:
    """Pure DAG of node calls in topological ``order``."""

    workflow_id: str
    nodes: dict[str, ExecNode] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    blocked: set[str] = field(default_factory=set)
    """Nodes excluded because an upstream node has validation errors."""

    def consumers(self, node_id: str) -> set[str]:
        return {n.id for n in self.nodes.values() if node_id in n.sources()}

    def ancestors(self, ids: Iterable[str], *, include_lazy: bool = False) -> set[str]:
        seen: set[str] = set()
        stack = [i for i in ids if i in self.nodes]
        while stack:
            current = stack.pop()
            for src in self.nodes[current].sources(include_lazy=include_lazy):
                if src not in seen and src in self.nodes:
                    seen.add(src)
                    stack.append(src)
        return seen

    def descendants(self, ids: Iterable[str]) -> set[str]:
        seen: set[str] = set()
        stack = list(ids)
        while stack:
            current = stack.pop()
            for consumer in self.consumers(current):
                if consumer not in seen:
                    seen.add(consumer)
                    stack.append(consumer)
        return seen


class ValidationErrors(BaseModel):
    """Compile failed for at least one node. ``graph`` holds the still-runnable subset."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    node_errors: dict[str, list[NodeIssue]]
    graph: ExecGraph = Field(exclude=True)


# --- flattening --------------------------------------------------------------------------------


@dataclass
class _Edge:
    src: str
    src_port: str
    dst: str
    dst_port: str


@dataclass
class _Flat:
    nodes: dict[str, NodeDoc] = field(default_factory=dict)
    edges: list[_Edge] = field(default_factory=list)
    errors: dict[str, list[NodeIssue]] = field(default_factory=dict)

    def error(self, node: str, code: str, message: str, **where: str | None) -> None:
        self.errors.setdefault(node, []).append(NodeIssue(code=code, message=message, **where))


def _flatten(
    nodes: Mapping[str, NodeDoc],
    edges: Mapping[str, EdgeDoc],
    subgraphs: Mapping[str, SubgraphDoc],
    flat: _Flat,
    *,
    prefix: str = "",
    depth: int = 0,
) -> None:
    """Inline ``subgraph:<id>`` instances as ``<instance>/<inner>`` nodes."""
    port_in: dict[tuple[str, str], tuple[str, str]] = {}
    port_out: dict[tuple[str, str], tuple[str, str]] = {}
    instances: set[str] = set()
    for nid, node in nodes.items():
        full = f"{prefix}{nid}"
        if not node.type.startswith(SUBGRAPH_PREFIX):
            flat.nodes[full] = node
            continue
        sg_id = node.type[len(SUBGRAPH_PREFIX) :]
        sg = subgraphs.get(sg_id)
        if sg is None:
            flat.error(full, "unknown_subgraph", f"unknown subgraph {sg_id!r}")
            continue
        if depth >= MAX_SUBGRAPH_DEPTH:
            flat.error(full, "subgraph_depth", "subgraphs nested too deeply")
            continue
        instances.add(full)
        inner_prefix = f"{full}/"
        _flatten(sg.nodes, sg.edges, subgraphs, flat, prefix=inner_prefix, depth=depth + 1)
        for p in sg.inputs:
            port_in[(full, p.name)] = (f"{inner_prefix}{p.node}", p.port)
        for p in sg.outputs:
            port_out[(full, p.name)] = (f"{inner_prefix}{p.node}", p.port)
    for edge in edges.values():
        src, src_port = f"{prefix}{edge.source[0]}", edge.source[1]
        dst, dst_port = f"{prefix}{edge.target[0]}", edge.target[1]
        if src in instances:
            mapped = port_out.get((src, src_port))
            if mapped is None:
                flat.error(
                    dst, "unknown_port", f"subgraph has no output {src_port!r}", port=dst_port
                )
                continue
            src, src_port = mapped
        if dst in instances:
            mapped = port_in.get((dst, dst_port))
            if mapped is None:
                flat.error(
                    dst, "unknown_port", f"subgraph has no input {dst_port!r}", port=dst_port
                )
                continue
            dst, dst_port = mapped
        flat.edges.append(_Edge(src, src_port, dst, dst_port))


def _bypass_disabled(flat: _Flat, registry: NodeRegistry) -> None:
    """Remove disabled nodes; pass their first type-matching input through to consumers."""
    disabled = {nid for nid, n in flat.nodes.items() if n.disabled}
    if not disabled:
        return
    incoming: dict[tuple[str, str], _Edge] = {}
    for e in flat.edges:
        if e.dst in disabled:
            incoming[(e.dst, e.dst_port)] = e
    passthrough: dict[tuple[str, str], tuple[str, str] | None] = {}
    for nid in disabled:
        node = flat.nodes[nid]
        try:
            spec = registry.get(node.type).spec
        except UnknownNodeError:
            continue
        for out in spec.outputs:
            source: tuple[str, str] | None = None
            for inp in spec.inputs:
                feed = incoming.get((nid, inp.name))
                if feed is not None and registry.types.is_compatible(inp.type, out.type):
                    source = (feed.src, feed.src_port)
                    break
            passthrough[(nid, out.name)] = source
    kept: list[_Edge] = []
    for edge in flat.edges:
        if edge.dst in disabled:
            continue
        if edge.src in disabled:
            source = passthrough.get((edge.src, edge.src_port))
            if source is None:
                flat.error(
                    edge.dst,
                    "upstream_disabled",
                    f"input {edge.dst_port!r} is fed by disabled node {edge.src!r}",
                    port=edge.dst_port,
                )
                continue
            kept.append(_Edge(source[0], source[1], edge.dst, edge.dst_port))
            continue
        kept.append(edge)
    flat.edges = kept
    for nid in disabled:
        del flat.nodes[nid]


# --- validation --------------------------------------------------------------------------------


def _resolve_params(
    node_def: NodeDef, given: Mapping[str, Any], linked: set[str], flat: _Flat, nid: str
) -> dict[str, Any]:
    """Fill defaults, validate with the node's pydantic model, report per-param issues."""
    spec = node_def.spec
    known = {p.name: p for p in spec.params}
    for name in given:
        if name not in known:
            flat.error(nid, "unknown_param", f"unknown param {name!r}", param=name)
    for name in linked:
        if name not in known:
            flat.error(nid, "unknown_param", f"linked param {name!r} does not exist", param=name)
    resolved: dict[str, Any] = {}
    for name, p in known.items():
        if name in linked:
            continue
        if name in given:
            resolved[name] = given[name]
        elif p.required:
            flat.error(nid, "missing_param", f"param {name!r} is required", param=name)
        else:
            resolved[name] = p.default
    try:
        node_def.params_model.model_validate(resolved)
    except ValidationError as exc:
        for err in exc.errors():
            loc = err.get("loc") or ()
            param = str(loc[0]) if loc else None
            if err.get("type") == "missing" and param in linked:
                continue
            if err.get("type") == "missing" and param is not None and param not in resolved:
                continue  # already reported as missing_param
            flat.error(nid, "bad_param", f"{param}: {err.get('msg', 'invalid')}", param=param)
    return resolved


def _topological(nodes: Mapping[str, ExecNode]) -> tuple[list[str], set[str]]:
    """Kahn's algorithm; returns ``(order, nodes stuck in cycles)``."""
    indegree = {nid: 0 for nid in nodes}
    consumers: dict[str, list[str]] = {nid: [] for nid in nodes}
    for nid, node in nodes.items():
        for src in node.sources():
            if src in nodes:
                indegree[nid] += 1
                consumers[src].append(nid)
    queue = deque(sorted(nid for nid, deg in indegree.items() if deg == 0))
    order: list[str] = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for consumer in sorted(consumers[current]):
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                queue.append(consumer)
    return order, {nid for nid in nodes if nid not in set(order)}


def compile(doc: WorkflowDoc, registry: NodeRegistry) -> ExecGraph | ValidationErrors:  # noqa: A001
    """Turn a document into an executable graph, or report per-node validation errors."""
    flat = _Flat()
    _flatten(doc.nodes, doc.edges, doc.subgraphs, flat)
    _bypass_disabled(flat, registry)

    defs: dict[str, NodeDef] = {}
    for nid, node in flat.nodes.items():
        try:
            defs[nid] = registry.get(node.type)
        except UnknownNodeError:
            flat.error(nid, "unknown_node", f"unknown node type {node.type!r}")

    # Inputs per node: ports plus linked params, with the type each accepts.
    accepts: dict[str, dict[str, tuple[str, bool, bool]]] = {}  # port -> (type, required, lazy)
    for nid, node_def in defs.items():
        table: dict[str, tuple[str, bool, bool]] = {
            p.name: (p.type, p.required, p.lazy) for p in node_def.spec.inputs
        }
        for name in flat.nodes[nid].linked:
            param = next((p for p in node_def.spec.params if p.name == name), None)
            if param is not None:
                table[name] = (param.link_type, param.required, False)
        accepts[nid] = table

    wired: dict[str, dict[str, tuple[str, str]]] = {nid: {} for nid in flat.nodes}
    upstream_failed: dict[str, set[str]] = {}  # consumer -> sources whose edge could not be wired
    bad_ports: set[tuple[str, str]] = set()
    for e in flat.edges:
        if e.dst not in flat.nodes:
            if e.src in flat.nodes:
                flat.error(e.src, "dangling_edge", f"edge to unknown node {e.dst!r}")
            continue
        if e.src not in flat.nodes:
            flat.error(e.dst, "dangling_edge", f"edge from unknown node {e.src!r}", port=e.dst_port)
            continue
        upstream_failed.setdefault(e.dst, set()).add(e.src)
        if e.dst not in defs or e.src not in defs:
            continue
        out_spec = next((o for o in defs[e.src].spec.outputs if o.name == e.src_port), None)
        if out_spec is None:
            flat.error(
                e.dst, "unknown_port", f"{e.src!r} has no output {e.src_port!r}", port=e.dst_port
            )
            continue
        target = accepts[e.dst].get(e.dst_port)
        if target is None:
            flat.error(e.dst, "unknown_port", f"no input {e.dst_port!r}", port=e.dst_port)
            continue
        if e.dst_port in wired[e.dst]:
            flat.error(
                e.dst, "multiple_inputs", f"input {e.dst_port!r} has several edges", port=e.dst_port
            )
            continue
        if not registry.types.is_compatible(out_spec.type, target[0]):
            bad_ports.add((e.dst, e.dst_port))
            flat.error(
                e.dst,
                "type_mismatch",
                f"{out_spec.type} from {e.src}.{e.src_port} cannot feed {e.dst_port} ({target[0]})",
                port=e.dst_port,
            )
            continue
        wired[e.dst][e.dst_port] = (e.src, e.src_port)

    exec_nodes: dict[str, ExecNode] = {}
    for nid, node_def in defs.items():
        node = flat.nodes[nid]
        linked = set(node.linked)
        for port, (_type, required, _lazy) in accepts[nid].items():
            if required and port not in wired[nid] and (nid, port) not in bad_ports:
                flat.error(nid, "missing_input", f"input {port!r} is required", port=port)
        params = _resolve_params(node_def, node.params, linked, flat, nid)
        exec_nodes[nid] = ExecNode(
            id=nid,
            type=node_def.id,
            version=node_def.spec.version,
            params=params,
            inputs=dict(wired[nid]),
            linked=frozenset(linked & set(wired[nid])),
            lazy=frozenset(p.name for p in node_def.spec.inputs if p.lazy),
            cost=node.cost or node_def.spec.cost,
            doc_id=nid.split("/", 1)[0],
        )

    order, cyclic = _topological(exec_nodes)
    for nid in sorted(cyclic):
        flat.error(nid, "cycle", "node is part of a cycle")

    graph = ExecGraph(workflow_id=doc.id)
    failed = set(flat.errors)
    blocked: set[str] = set()
    for nid in order:
        enode = exec_nodes[nid]
        sources = enode.sources() | upstream_failed.get(nid, set())
        if nid in failed or any(s in failed or s in blocked for s in sources):
            if nid not in failed:
                blocked.add(nid)
            continue
        graph.nodes[nid] = enode
        graph.order.append(nid)
    graph.blocked = blocked
    if flat.errors:
        return ValidationErrors(
            node_errors={k: flat.errors[k] for k in sorted(flat.errors)}, graph=graph
        )
    return graph


def as_graph(result: ExecGraph | ValidationErrors) -> ExecGraph:
    """The executable graph from either ``compile`` outcome."""
    return result if isinstance(result, ExecGraph) else result.graph
