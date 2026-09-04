"""Dynamic ports: nodes whose ports are declared by their own parameters.

Almost every node has a fixed shape -- its ports come from the function signature and never
change. The code node is the exception the design calls for (§5, phase 11): the user types the
snippet *and* says what goes in and what comes out, so the ports live in two parameters
(``inputs`` and ``outputs``, each a list of ``{name, type}``).

``@node(dynamic_ports=DynamicPorts(...))`` names those parameters. The declaration travels on the
``NodeSpec``, so the compiler, the executor and the frontend all derive the same ports from the
same document values -- there is no hidden per-instance schema to keep in sync.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from astro_canvas.sdk.porttype import ANY_TYPE
from astro_canvas.sdk.spec import DynamicPorts, NodeSpec, PortSpec

PORT_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


class PortDecl(BaseModel):
    """One user-declared port (the element type of a ``dynamic_ports`` parameter)."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Port name; must be a Python identifier.")
    type: str = Field(default=ANY_TYPE, description="Port type id, e.g. ``astro.Spectrum1D``.")
    description: str = ""
    required: bool = True


def valid_port_name(name: str) -> bool:
    """A dynamic port name must be a plain identifier so it can address an edge unambiguously."""
    return bool(name) and not name[0].isdigit() and set(name) <= PORT_NAME_CHARS


def parse_declarations(value: Any) -> list[PortDecl]:
    """Coerce a param value into port declarations, dropping anything malformed.

    A half-typed declaration is normal while the user is editing the node, so this never raises;
    the compiler reports the resulting missing ports instead.
    """
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    out: list[PortDecl] = []
    seen: set[str] = set()
    for item in value:
        decl: PortDecl | None = None
        if isinstance(item, PortDecl):
            decl = item
        elif isinstance(item, Mapping):
            name = str(item.get("name", "")).strip()
            if valid_port_name(name):
                decl = PortDecl(
                    name=name,
                    type=str(item.get("type") or ANY_TYPE),
                    description=str(item.get("description") or ""),
                    required=bool(item.get("required", True)),
                )
        elif isinstance(item, str) and valid_port_name(item.strip()):
            decl = PortDecl(name=item.strip())
        if decl is None or decl.name in seen or not valid_port_name(decl.name):
            continue
        seen.add(decl.name)
        out.append(decl)
    return out


def declared_ports(value: Any) -> list[PortSpec]:
    """Port specs for one ``dynamic_ports`` parameter value."""
    return [
        PortSpec(name=d.name, type=d.type, description=d.description, required=d.required)
        for d in parse_declarations(value)
    ]


def effective_ports(
    spec: NodeSpec, params: Mapping[str, Any] | None = None
) -> tuple[list[PortSpec], list[PortSpec]]:
    """``(inputs, outputs)`` of one node instance: the static ports plus the declared ones.

    For a node without ``dynamic_ports`` this is exactly ``spec.inputs, spec.outputs``.
    """
    dynamic = spec.dynamic_ports
    if dynamic is None:
        return list(spec.inputs), list(spec.outputs)
    values = params or {}
    inputs = list(spec.inputs)
    outputs = list(spec.outputs)
    if dynamic.inputs:
        inputs = inputs + declared_ports(values.get(dynamic.inputs))
    if dynamic.outputs:
        outputs = outputs + declared_ports(values.get(dynamic.outputs))
    return inputs, outputs


__all__ = [
    "DynamicPorts",
    "PortDecl",
    "declared_ports",
    "effective_ports",
    "parse_declarations",
    "valid_port_name",
]
