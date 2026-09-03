"""``/api/nodes``, ``/api/types`` and ``/api/packs``: the schema catalogue for the frontend."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from astro_canvas.sdk import NodeRegistry, NodeSpec, PackRecord, PortTypeSpec, UnknownNodeError

router = APIRouter(tags=["nodes"])


def get_registry(request: Request) -> NodeRegistry:
    """The registry built at startup (``create_app``)."""
    registry: NodeRegistry = request.app.state.registry
    return registry


@router.get("/nodes", response_model=list[NodeSpec])
def list_nodes(request: Request, category: str | None = None) -> list[NodeSpec]:
    """Every registered node schema, sorted by id; optionally filtered by exact category."""
    specs = get_registry(request).list()
    if category is not None:
        specs = [s for s in specs if s.category == category]
    return specs


@router.get("/nodes/{node_id}", response_model=NodeSpec)
def get_node(request: Request, node_id: str) -> NodeSpec:
    """One node schema by id."""
    try:
        return get_registry(request).spec(node_id)
    except UnknownNodeError:
        raise HTTPException(status_code=404, detail=f"unknown node {node_id!r}") from None


@router.get("/types", response_model=list[PortTypeSpec])
def list_types(request: Request) -> list[PortTypeSpec]:
    """Every registered port type, sorted by id."""
    return get_registry(request).types.list()


@router.get("/packs", response_model=list[PackRecord])
def list_packs(request: Request) -> list[PackRecord]:
    """Discovered packs, including the ones that failed to load (with their error)."""
    packs: list[PackRecord] = request.app.state.packs
    return packs
