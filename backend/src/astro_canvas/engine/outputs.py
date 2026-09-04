"""Turn a node's raw return value into ``{port: PortType}`` and unwrap linked-param inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from astro_canvas.sdk import (
    WRAPPED_TYPE_IDS,
    NodeDef,
    PortType,
    TypeRegistry,
    effective_ports,
    is_compatible,
    unwrap_scalar,
)

WRAPPED_IDS = WRAPPED_TYPE_IDS


class OutputError(TypeError):
    """A node returned something that does not match its declared outputs."""


def coerce(value: Any, type_id: str, types: TypeRegistry) -> PortType:
    """Make ``value`` an instance of the registered port type ``type_id``."""
    if isinstance(value, PortType):
        actual = value.type_id()
        if actual == type_id or is_compatible(actual, type_id, types):
            return value
        raise OutputError(f"expected {type_id}, got {actual}")
    cls = types.get(type_id)
    if type_id in WRAPPED_IDS:
        return cls.model_validate({"value": value})
    if isinstance(value, Mapping):
        return cls.model_validate(dict(value))
    raise OutputError(f"expected {type_id}, got {type(value).__name__}")


def wrap_outputs(
    node: NodeDef,
    result: Any,
    types: TypeRegistry,
    params: Mapping[str, Any] | None = None,
) -> dict[str, PortType]:
    """Split ``result`` per ``NodeDef.output_kind`` and wrap scalars into port values.

    ``params`` is only needed for a node with dynamic output ports (the code node): its outputs
    are declared in a parameter, so the mapping it returns is checked against that declaration.
    """
    if node.output_kind == "dynamic":
        return _wrap_dynamic(node, result, types, params or {})
    specs = {o.name: o.type for o in node.spec.outputs}
    names = node.output_names
    if node.output_kind == "none" or not names:
        return {}
    if node.output_kind == "single":
        return {names[0]: coerce(result, specs[names[0]], types)}
    if node.output_kind == "tuple":
        if not isinstance(result, tuple | list) or len(result) != len(names):
            raise OutputError(f"{node.id}: expected a tuple of {len(names)} outputs")
        return {n: coerce(v, specs[n], types) for n, v in zip(names, result, strict=True)}
    return {n: coerce(getattr(result, n), specs[n], types) for n in names}


def _wrap_dynamic(
    node: NodeDef, result: Any, types: TypeRegistry, params: Mapping[str, Any]
) -> dict[str, PortType]:
    """A node with declared output ports must return ``{port name: value}`` covering all of them."""
    _, outputs = effective_ports(node.spec, params)
    if not isinstance(result, Mapping):
        raise OutputError(f"{node.id}: expected a dict of outputs, got {type(result).__name__}")
    missing = [o.name for o in outputs if o.name not in result]
    if missing:
        raise OutputError(f"{node.id}: no value for output {', '.join(sorted(missing))}")
    extra = sorted(set(result) - {o.name for o in outputs})
    if extra:
        raise OutputError(f"{node.id}: undeclared output {', '.join(extra)}")
    return {o.name: coerce(result[o.name], o.type, types) for o in outputs}


def unwrap_linked(value: PortType) -> Any:
    """A linked param receives the plain value carried by scalar/JSON port types."""
    return unwrap_scalar(value)
