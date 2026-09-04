"""Port types: pydantic models tagged with ``@port_type`` that know how to blob and summarize."""

from __future__ import annotations

import builtins
import json
import re
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, TypeGuard, TypeVar

import numpy as np
from pydantic import BaseModel, ConfigDict

from astro_canvas.sdk.blob import (
    ARRAYS_PART,
    MANIFEST_NAME,
    Blob,
    decode_npz,
    encode_npz,
    join_binary,
    split_binary,
    to_manifest_data,
)
from astro_canvas.sdk.errors import (
    BlobError,
    DuplicateNodeError,
    NodeDefinitionError,
    UnknownTypeError,
)
from astro_canvas.sdk.memmap import (
    NPY_SUFFIX,
    PART_PREFIX,
    decode_npy,
    encode_npy,
    memmap_part,
    mmap_min_bytes,
)
from astro_canvas.sdk.spec import PortTypeSpec

MMAP_KEY = "mmap"
"""Manifest key mapping a field name to the ``.npy`` part holding its (mappable) array."""


class _Unmappable(Exception):
    """Internal: this blob has no mappable parts, so read it the ordinary way."""


def mmap_manifest(manifest: Mapping[str, Any]) -> dict[str, str]:
    """``{field: part}`` written by ``to_blob`` for arrays stored as standalone ``.npy`` parts."""
    mapped = manifest.get(MMAP_KEY)
    if not isinstance(mapped, Mapping):
        return {}
    return {str(k): str(v) for k, v in mapped.items()}


ANY_TYPE = "astro.Any"
JSON_TYPE = "astro.Json"
SCALAR_TYPE_IDS: dict[type, str] = {
    float: "astro.Float",
    int: "astro.Int",
    str: "astro.Str",
    bool: "astro.Bool",
}
"""Port type ids that JSON-native params become when linked (implemented by the core pack)."""

WRAPPED_TYPE_IDS: frozenset[str] = frozenset([*SCALAR_TYPE_IDS.values(), JSON_TYPE, ANY_TYPE])
"""Types that merely box a plain Python value; consumers see the value, not the wrapper."""

_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")


@dataclass(frozen=True)
class PortTypeMeta:
    """Metadata captured by ``@port_type``."""

    id: str
    color: str
    summary_renderer: str | None
    compatible_with: tuple[str, ...]


class PortType(BaseModel):
    """Base class for every port type.

    Subclasses declare fields (arrays via ``astro_canvas.sdk.arrays``), apply ``@port_type`` and
    optionally override ``to_blob``/``from_blob`` (e.g. Arrow IPC for tables) or ``summary``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    __astro_port_type__: ClassVar[PortTypeMeta | None] = None

    __mmap_fields__: ClassVar[tuple[str, ...]] = ()
    """Fields whose big arrays get their own ``.npy`` part so ``from_blob_file`` can map them."""

    @classmethod
    def type_id(cls) -> str:
        """The registered id (``astro.Spectrum1D``)."""
        if cls.__astro_port_type__ is None:
            raise NodeDefinitionError(f"{cls.__name__} is not decorated with @port_type")
        return cls.__astro_port_type__.id

    def to_blob(self) -> Blob:
        """Default: arrays into one npz part, bytes into parts, the rest into the manifest.

        Arrays named in ``__mmap_fields__`` that are at least ``mmap_min_bytes()`` large are
        written as their own uncompressed ``.npy`` part instead, so a reader can memory-map them.
        """
        data, arrays, binaries = split_binary(self.model_dump(mode="python"))
        parts: dict[str, bytes] = dict(binaries)
        mapped: dict[str, str] = {}
        threshold = mmap_min_bytes()
        for name in self.__mmap_fields__:
            array = arrays.get(name)
            if array is None or threshold <= 0 or array.nbytes < threshold:
                continue
            part = f"{name}{NPY_SUFFIX}"
            parts[part] = encode_npy(array)
            mapped[name] = part
            del arrays[name]
        if arrays:
            parts[ARRAYS_PART] = encode_npz(arrays)
        manifest: dict[str, Any] = {"type": self.type_id(), "data": to_manifest_data(data)}
        if mapped:
            manifest[MMAP_KEY] = mapped
        return Blob(manifest=manifest, parts=parts)

    @classmethod
    def from_blob(cls: type[P], blob: Blob) -> P:
        """Inverse of the default ``to_blob``."""
        if blob.manifest.get("type") != cls.type_id():
            raise BlobError(f"blob holds {blob.manifest.get('type')!r}, expected {cls.type_id()!r}")
        mapped = mmap_manifest(blob.manifest)
        arrays = decode_npz(blob.parts[ARRAYS_PART]) if ARRAYS_PART in blob.parts else {}
        for name, part in mapped.items():
            if part not in blob.parts:
                raise BlobError(f"missing array part {part!r}")
            arrays[name] = decode_npy(blob.parts[part])
        skip = {ARRAYS_PART, *mapped.values()}
        binaries = {k: v for k, v in blob.parts.items() if k not in skip}
        return cls.model_validate(join_binary(blob.manifest.get("data"), arrays, binaries))

    @classmethod
    def from_blob_file(cls: type[P], path: Path) -> P:
        """Like ``from_blob``, but big arrays are mapped from ``path`` instead of copied.

        The value holds read-only ``numpy.memmap`` views into the blob file, so an IFU cube costs
        page cache rather than resident memory. Types without ``__mmap_fields__`` -- and any part
        that cannot be mapped -- go through ``from_blob`` unchanged.
        """
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
                manifest: dict[str, Any] = json.loads(zf.read(MANIFEST_NAME))
                mapped = mmap_manifest(manifest)
                if not mapped:
                    raise _Unmappable
                npz = f"{PART_PREFIX}{ARRAYS_PART}"
                arrays = decode_npz(zf.read(npz)) if npz in names else {}
                skip = {npz, *(f"{PART_PREFIX}{p}" for p in mapped.values())}
                binaries = {
                    n.removeprefix(PART_PREFIX): zf.read(n)
                    for n in names
                    if n.startswith(PART_PREFIX) and n not in skip
                }
            for name, part in mapped.items():
                view = memmap_part(path, part)
                if view is None:
                    raise _Unmappable
                arrays[name] = view
        except (_Unmappable, KeyError, OSError, ValueError, zipfile.BadZipFile):
            return cls.from_blob(Blob.unpack(path.read_bytes()))
        return cls.model_validate(join_binary(manifest.get("data"), arrays, binaries))

    def summary(self, viewport: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Small JSON payload for the node's inline preview; arrays become shape/range stats."""
        return {"type": self.type_id(), "data": summarize_arrays(self.model_dump(mode="python"))}


P = TypeVar("P", bound=PortType)


def summarize_arrays(value: Any) -> Any:
    """Replace ndarray leaves with ``{shape, dtype, min, max}`` and drop raw bytes."""
    if isinstance(value, np.ndarray):
        stats: dict[str, Any] = {"shape": list(value.shape), "dtype": value.dtype.name}
        if value.size and value.dtype.kind in "fiu":
            finite = value[np.isfinite(value)] if value.dtype.kind == "f" else value
            if finite.size:
                stats["min"], stats["max"] = float(finite.min()), float(finite.max())
        return {"$ndarray": stats}
    if isinstance(value, bytes | bytearray | memoryview):
        return {"$bytes": len(value)}
    if isinstance(value, Mapping):
        return {str(k): summarize_arrays(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [summarize_arrays(v) for v in value]
    return to_manifest_data(value)


def port_type(
    *,
    id: str,
    color: str = "#888888",
    summary_renderer: str | None = None,
    compatible_with: Sequence[str] = (),
) -> Callable[[type[P]], type[P]]:
    """Register ``cls`` (a ``PortType`` subclass) as the port type ``id``."""
    if not _ID_PATTERN.match(id):
        raise NodeDefinitionError(f"invalid port type id {id!r} (expected e.g. astro.Spectrum1D)")

    def decorate(cls: type[P]) -> type[P]:
        if not (isinstance(cls, type) and issubclass(cls, PortType)):
            raise NodeDefinitionError(f"@port_type requires a PortType subclass, got {cls!r}")
        cls.__astro_port_type__ = PortTypeMeta(
            id=id,
            color=color,
            summary_renderer=summary_renderer,
            compatible_with=tuple(compatible_with),
        )
        return cls

    return decorate


def is_port_type(obj: Any) -> TypeGuard[type[PortType]]:
    """True for classes decorated with ``@port_type`` (not for undecorated subclasses)."""
    return (
        isinstance(obj, type)
        and issubclass(obj, PortType)
        and "__astro_port_type__" in obj.__dict__
        and obj.__astro_port_type__ is not None
    )


def port_type_spec(cls: type[PortType], pack: str | None = None) -> PortTypeSpec:
    """Build the wire description of a port type class."""
    meta = cls.__astro_port_type__
    if meta is None:
        raise NodeDefinitionError(f"{cls.__name__} is not decorated with @port_type")
    doc = (cls.__doc__ or "").strip().splitlines()
    return PortTypeSpec(
        id=meta.id,
        name=cls.__name__,
        color=meta.color,
        summary_renderer=meta.summary_renderer,
        compatible_with=list(meta.compatible_with),
        description=doc[0] if doc else "",
        json_schema=cls.model_json_schema(),
        module=cls.__module__,
        pack=pack,
    )


class TypeRegistry:
    """Registered port types by id."""

    def __init__(self) -> None:
        self._types: dict[str, type[PortType]] = {}
        self._specs: dict[str, PortTypeSpec] = {}

    def add(self, cls: type[PortType], *, pack: str | None = None) -> type[PortType]:
        """Register ``cls``; re-adding the same class is a no-op, a different class is an error."""
        if not is_port_type(cls):
            raise NodeDefinitionError(f"{cls!r} is not decorated with @port_type")
        type_id = cls.type_id()
        existing = self._types.get(type_id)
        if existing is not None and existing is not cls:
            raise DuplicateNodeError(f"port type {type_id!r} is already registered by {existing!r}")
        if existing is None:
            self._types[type_id] = cls
            self._specs[type_id] = port_type_spec(cls, pack)
        return cls

    def remove_pack(self, pack: str) -> int:
        """Drop every type registered under ``pack``; returns how many were removed."""
        doomed = [tid for tid, spec in self._specs.items() if spec.pack == pack]
        for tid in doomed:
            del self._types[tid]
            del self._specs[tid]
        return len(doomed)

    def get(self, type_id: str) -> type[PortType]:
        try:
            return self._types[type_id]
        except KeyError:
            raise UnknownTypeError(f"unknown port type {type_id!r}") from None

    def spec(self, type_id: str) -> PortTypeSpec:
        self.get(type_id)
        return self._specs[type_id]

    def list(self) -> builtins.list[PortTypeSpec]:
        return [self._specs[tid] for tid in sorted(self._specs)]

    def ids(self) -> builtins.list[str]:
        return sorted(self._types)

    def __contains__(self, type_id: object) -> bool:
        return type_id in self._types

    def __len__(self) -> int:
        return len(self._types)

    def is_compatible(self, source: str, target: str) -> bool:
        """See ``is_compatible``."""
        return is_compatible(source, target, self)


def is_compatible(source: str, target: str, registry: TypeRegistry | None = None) -> bool:
    """Can an output of type ``source`` feed an input of type ``target``?

    Exact match; ``astro.Any`` accepts everything; ``astro.Json`` accepts scalars; a registered
    source may list explicit coercion targets in ``compatible_with``.
    """
    if target in (source, ANY_TYPE):
        return True
    if target == JSON_TYPE and source in SCALAR_TYPE_IDS.values():
        return True
    if registry is not None and source in registry:
        return target in registry.spec(source).compatible_with
    return False


def unwrap_scalar(value: PortType) -> Any:
    """The plain Python value inside a boxing port type (``astro.Float``, ``astro.Any``, ...).

    Anything else is returned unchanged: a ``Spectrum1D`` *is* the value a node wants.
    """
    if value.type_id() in WRAPPED_TYPE_IDS:
        return getattr(value, "value")  # noqa: B009 - dynamic attribute of a wrapped scalar
    return value
