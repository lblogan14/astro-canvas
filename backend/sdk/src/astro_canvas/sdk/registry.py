"""Node registry and entry-point discovery."""

from __future__ import annotations

import builtins
import importlib.metadata
import logging
import traceback
from collections.abc import Container, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from astro_canvas.sdk.errors import DuplicateNodeError, UnknownNodeError
from astro_canvas.sdk.node import NodeDef
from astro_canvas.sdk.porttype import PortType, TypeRegistry, is_port_type
from astro_canvas.sdk.spec import NodeSpec, PackLoadError, PackRecord

ENTRY_POINT_GROUP = "astro_canvas.nodes"
log = logging.getLogger("astro_canvas.sdk")


class NodeRegistry:
    """Nodes by id plus the port ``types`` they use."""

    def __init__(self, types: TypeRegistry | None = None) -> None:
        self._nodes: dict[str, NodeDef] = {}
        self._specs: dict[str, NodeSpec] = {}
        self.types = types if types is not None else TypeRegistry()
        self.sample_dirs: dict[str, Path] = {}
        """Per pack, a folder of bundled sample data copied to ``<workspace>/samples/<pack>``."""
        self.security: dict[str, str] = {}
        """Per pack security class declared at registration (``standard`` when absent)."""
        self.template_dirs: dict[str, Path] = {}
        """Per pack, a folder of workflow templates (``*.acw`` documents plus optional ``*.md``)."""

    def add_sample_data(self, path: Path, *, pack: str) -> None:
        """Declare a directory of sample files shipped with ``pack``."""
        self.sample_dirs[pack] = Path(path)

    def declare_security(self, level: str, *, pack: str) -> None:
        """Record the pack's manifest ``security`` class (``standard``, ``needs-network``, ...)."""
        self.security[pack] = level

    def add_templates(self, path: Path, *, pack: str) -> None:
        """Declare a directory of workflow templates shipped with ``pack``."""
        self.template_dirs[pack] = Path(path)

    def add(self, node: NodeDef, *, pack: str | None = None) -> NodeDef:
        """Register ``node``; raises ``DuplicateNodeError`` if the id is taken."""
        if not isinstance(node, NodeDef):
            raise TypeError(f"expected a @node-decorated function, got {node!r}")
        if node.id in self._nodes:
            raise DuplicateNodeError(f"node {node.id!r} is already registered")
        self._nodes[node.id] = node
        self._specs[node.id] = node.spec.model_copy(update={"pack": pack})
        return node

    def add_type(self, cls: type[PortType], *, pack: str | None = None) -> type[PortType]:
        return self.types.add(cls, pack=pack)

    def add_module(self, module: ModuleType, *, pack: str | None = None) -> int:
        """Register every ``NodeDef`` and ``@port_type`` class defined in ``module``.

        Returns the number of nodes added. Port types are registered idempotently, so modules
        that merely import types from elsewhere do not conflict.
        """
        added = 0
        for value in list(vars(module).values()):
            if is_port_type(value):
                self.types.add(value, pack=pack)
            elif isinstance(value, NodeDef) and value.id not in self._nodes:
                self.add(value, pack=pack)
                added += 1
        return added

    def remove_pack(self, pack: str) -> int:
        """Forget everything registered under ``pack`` (used when a pack fails mid-way)."""
        doomed = [nid for nid, spec in self._specs.items() if spec.pack == pack]
        for nid in doomed:
            del self._nodes[nid]
            del self._specs[nid]
        self.sample_dirs.pop(pack, None)
        self.security.pop(pack, None)
        self.template_dirs.pop(pack, None)
        return len(doomed) + self.types.remove_pack(pack)

    def get(self, node_id: str) -> NodeDef:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise UnknownNodeError(f"unknown node {node_id!r}") from None

    def spec(self, node_id: str) -> NodeSpec:
        """The node's ``NodeSpec`` with ``pack`` filled in."""
        self.get(node_id)
        return self._specs[node_id]

    def ids(self) -> builtins.list[str]:
        return sorted(self._nodes)

    def list(self) -> builtins.list[NodeSpec]:
        return [self._specs[nid] for nid in sorted(self._specs)]

    def by_category(self) -> dict[str, builtins.list[NodeSpec]]:
        grouped: dict[str, builtins.list[NodeSpec]] = {}
        for spec in self.list():
            grouped.setdefault(spec.category, []).append(spec)
        return dict(sorted(grouped.items()))

    def validate_unique(self) -> builtins.list[str]:
        """Return human-readable problems: ports referencing unregistered types."""
        problems: builtins.list[str] = []
        for spec in self.list():
            for port in [*spec.inputs, *spec.outputs]:
                if port.type not in self.types:
                    problems.append(
                        f"{spec.id}: port {port.name!r} uses unknown type {port.type!r}"
                    )
        return problems

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._nodes

    def __len__(self) -> int:
        return len(self._nodes)

    def for_pack(self, pack: str) -> PackRegistry:
        return PackRegistry(self, pack)


class PackRegistry:
    """What a pack's ``register(registry)`` entry point receives: adds tagged with the pack."""

    def __init__(self, registry: NodeRegistry, pack: str) -> None:
        self.registry = registry
        self.pack = pack

    def add(self, node: NodeDef) -> NodeDef:
        return self.registry.add(node, pack=self.pack)

    def add_type(self, cls: type[PortType]) -> type[PortType]:
        return self.registry.add_type(cls, pack=self.pack)

    def add_module(self, module: ModuleType) -> int:
        return self.registry.add_module(module, pack=self.pack)

    def add_sample_data(self, path: Path) -> None:
        self.registry.add_sample_data(path, pack=self.pack)

    def declare_security(self, level: str) -> None:
        self.registry.declare_security(level, pack=self.pack)

    def add_templates(self, path: Path) -> None:
        self.registry.add_templates(path, pack=self.pack)

    @property
    def types(self) -> TypeRegistry:
        return self.registry.types


@dataclass
class DiscoveryResult:
    """Outcome of ``discover()``: the populated registry and one record per pack."""

    registry: NodeRegistry
    packs: list[PackRecord] = field(default_factory=list)

    @property
    def errors(self) -> list[PackLoadError]:
        return [p.error for p in self.packs if p.error is not None]


def pack_entry_points(
    group: str = ENTRY_POINT_GROUP,
) -> list[importlib.metadata.EntryPoint]:
    """Every installed ``astro_canvas.nodes`` entry point, sorted by pack name.

    ``importlib.metadata`` caches its view of ``sys.path``; call
    ``importlib.invalidate_caches()`` first when a pack was installed after start-up.
    """
    return sorted(importlib.metadata.entry_points(group=group), key=lambda e: e.name)


def load_pack(registry: NodeRegistry, ep: importlib.metadata.EntryPoint) -> PackRecord:
    """Import one pack and call its ``register(registry)``; never raises.

    A pack that fails leaves no partial registration behind (they are rolled back) and comes back
    as a ``PackRecord`` carrying a ``PackLoadError`` with the traceback the Manager shows.
    """
    dist = getattr(ep, "dist", None)
    version = getattr(dist, "version", None) or "unknown"
    distribution: str | None = getattr(dist, "name", None) if dist is not None else None
    nodes_before, types_before = len(registry), len(registry.types)
    error: PackLoadError | None = None
    try:
        target: Any = ep.load()
        if not callable(target):
            raise TypeError(f"entry point {ep.value!r} is not callable")
        target(registry.for_pack(ep.name))
    except Exception as exc:  # noqa: BLE001 - per-pack isolation is the point
        registry.remove_pack(ep.name)
        error = PackLoadError(
            pack=ep.name,
            entry_point=ep.value,
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
        )
        log.warning("pack %s failed to load: %s", ep.name, error.error)
    return PackRecord(
        name=ep.name,
        version=version,
        distribution=distribution,
        entry_point=ep.value,
        node_count=len(registry) - nodes_before if error is None else 0,
        type_count=len(registry.types) - types_before if error is None else 0,
        security=registry.security.get(ep.name, "standard"),
        error=error,
    )


def discover(
    entry_points: Iterable[importlib.metadata.EntryPoint] | None = None,
    *,
    registry: NodeRegistry | None = None,
    skip: Container[str] = (),
) -> DiscoveryResult:
    """Load every ``astro_canvas.nodes`` entry point into a registry.

    A pack that raises during import or registration is recorded as a ``PackLoadError`` (its
    partial registrations are rolled back) and does not prevent other packs from loading. Packs
    named in ``skip`` are not imported at all (the Manager's disabled list).
    """
    registry = registry if registry is not None else NodeRegistry()
    eps = (
        pack_entry_points() if entry_points is None else sorted(entry_points, key=lambda e: e.name)
    )
    records = [load_pack(registry, ep) for ep in eps if ep.name not in skip]
    return DiscoveryResult(registry=registry, packs=records)
