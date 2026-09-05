"""Astro Canvas node SDK.

Turn a Python function into a node with ``@node``; describe parameters with ``Param``; define
port types with ``@port_type`` on ``PortType`` models; discover packs with ``discover()``.

Parameter rules (see the design document, section 5):

* an annotation that is a ``@port_type`` class is an **input port**;
* JSON-native annotations (``float``, ``int``, ``str``, ``bool``, ``Literal``, ``list[...]``,
  ``Optional``, pydantic models, ``Quantity[unit]``) are **params** rendered as widgets and
  linkable into ports;
* ``ctx: NodeContext | None = None`` receives the runtime context;
* the return annotation is one port type, ``tuple[...]`` of them (``outputs=`` names them), a
  ``NamedTuple``/dataclass whose fields become named outputs, or ``None``.
"""

from __future__ import annotations

from astro_canvas.sdk import errors
from astro_canvas.sdk.arrays import (
    Float1D,
    Float2D,
    Float3D,
    Float32_2D,
    Float32_3D,
    FloatArray,
    NDArray,
    NDArrayAnnotation,
    StrArray,
    arrays_equal,
    decimate,
    decimate_indices,
)
from astro_canvas.sdk.blob import Blob
from astro_canvas.sdk.context import NodeContext, NullContext
from astro_canvas.sdk.docstrings import DocInfo, parse_docstring
from astro_canvas.sdk.errors import (
    BlobError,
    DuplicateNodeError,
    NodeDefinitionError,
    SdkError,
    UnknownNodeError,
    UnknownTypeError,
)
from astro_canvas.sdk.expand import ExpandNode, Expansion
from astro_canvas.sdk.memmap import is_memmapped, memmap_part, mmap_min_bytes
from astro_canvas.sdk.node import NodeDef, node, validate_call
from astro_canvas.sdk.params import Param, Widget
from astro_canvas.sdk.ports import (
    DynamicPorts,
    PortDecl,
    declared_ports,
    effective_ports,
    parse_declarations,
)
from astro_canvas.sdk.porttype import (
    ANY_TYPE,
    JSON_TYPE,
    SCALAR_TYPE_IDS,
    WRAPPED_TYPE_IDS,
    PortType,
    TypeRegistry,
    is_compatible,
    is_port_type,
    port_type,
    unwrap_scalar,
)
from astro_canvas.sdk.registry import (
    ENTRY_POINT_GROUP,
    DiscoveryResult,
    NodeRegistry,
    PackRegistry,
    discover,
    load_pack,
    pack_entry_points,
)
from astro_canvas.sdk.spec import (
    Cost,
    NodeSpec,
    PackLoadError,
    PackRecord,
    ParamSpec,
    PortSpec,
    PortTypeSpec,
)

__version__ = "0.1.0"

__all__ = [
    "ANY_TYPE",
    "ENTRY_POINT_GROUP",
    "JSON_TYPE",
    "SCALAR_TYPE_IDS",
    "WRAPPED_TYPE_IDS",
    "Blob",
    "BlobError",
    "Cost",
    "DiscoveryResult",
    "DynamicPorts",
    "DocInfo",
    "DuplicateNodeError",
    "ExpandNode",
    "Expansion",
    "Float1D",
    "Float2D",
    "Float3D",
    "Float32_2D",
    "Float32_3D",
    "FloatArray",
    "NDArray",
    "NDArrayAnnotation",
    "NodeContext",
    "NodeDef",
    "NodeDefinitionError",
    "NodeRegistry",
    "NodeSpec",
    "NullContext",
    "PackLoadError",
    "PackRecord",
    "PackRegistry",
    "Param",
    "ParamSpec",
    "PortDecl",
    "PortSpec",
    "PortType",
    "PortTypeSpec",
    "SdkError",
    "StrArray",
    "TypeRegistry",
    "UnknownNodeError",
    "UnknownTypeError",
    "Widget",
    "__version__",
    "arrays_equal",
    "decimate",
    "decimate_indices",
    "declared_ports",
    "discover",
    "effective_ports",
    "load_pack",
    "parse_declarations",
    "unwrap_scalar",
    "pack_entry_points",
    "errors",
    "is_compatible",
    "is_memmapped",
    "is_port_type",
    "memmap_part",
    "mmap_min_bytes",
    "node",
    "parse_docstring",
    "port_type",
    "validate_call",
]
