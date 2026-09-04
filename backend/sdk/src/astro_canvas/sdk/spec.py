"""Wire models describing nodes, ports, parameters, port types, and packs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Cost = Literal["cheap", "expensive", "auto"]


class PortSpec(BaseModel):
    """An input or output port."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str = Field(description="Port type id, e.g. ``astro.Spectrum1D``.")
    description: str = ""
    required: bool = True
    lazy: bool = False


class ParamSpec(BaseModel):
    """A widget-rendered parameter. Any param can be linked to become an input port."""

    model_config = ConfigDict(frozen=True)

    name: str
    label: str
    description: str = ""
    json_schema: dict[str, Any] = Field(
        description="Self-contained JSON Schema (draft 2020-12) including default/constraints."
    )
    required: bool = False
    default: Any = None
    widget: str | None = None
    unit: str | None = None
    step: float | None = None
    advanced: bool = False
    linkable: bool = True
    link_type: str = Field(
        description="Port type id the param becomes when linked (``astro.Float`` etc.)."
    )


class DynamicPorts(BaseModel):
    """Which parameters of a node declare its ports, and where the values arrive.

    Attributes:
        inputs: Param name holding the input declarations, or ``None`` for a fixed input set.
        outputs: Param name holding the output declarations, or ``None``.
        values: Function parameter that receives ``{port name: value}`` for the dynamic inputs.
    """

    model_config = ConfigDict(frozen=True)

    inputs: str | None = None
    outputs: str | None = None
    values: str = "values"


class NodeSpec(BaseModel):
    """Everything the frontend and engine need to know about a node type."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    category: str
    version: str = "1.0.0"
    cost: Cost = "cheap"
    inputs: list[PortSpec] = []
    params: list[ParamSpec] = []
    outputs: list[PortSpec] = []
    description: str = ""
    param_docs: dict[str, str] = {}
    icon: str | None = None
    preview: str | None = None
    editor: str | None = None
    pack: str | None = None
    module: str = ""
    deprecated: bool = False
    experimental: bool = False
    expand: bool = False
    fingerprint: bool = Field(
        default=False, description="True when the node declares a ``fingerprint`` callable."
    )
    is_async: bool = False
    dynamic_ports: DynamicPorts | None = Field(
        default=None,
        description="Set when the node's ports come from its own params (the code node).",
    )


class PortTypeSpec(BaseModel):
    """A registered port type."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    color: str = "#888888"
    summary_renderer: str | None = None
    compatible_with: list[str] = []
    description: str = ""
    json_schema: dict[str, Any] = {}
    module: str = ""
    pack: str | None = None


class PackLoadError(BaseModel):
    """Recorded (not raised) when a pack's entry point fails to import or register."""

    model_config = ConfigDict(frozen=True)

    pack: str
    entry_point: str
    error: str
    traceback: str = ""


class PackRecord(BaseModel):
    """A discovered pack (entry point in the ``astro_canvas.nodes`` group)."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str = "unknown"
    distribution: str | None = None
    entry_point: str
    enabled: bool = True
    node_count: int = 0
    type_count: int = 0
    security: str = Field(
        default="standard",
        description="Manifest security class: standard, needs-network or runs-subprocess.",
    )
    error: PackLoadError | None = None
