"""Blobs: the serialized form of a port value (JSON manifest + binary parts).

The default ``PortType.to_blob`` walks the model dump, moves every ``ndarray`` into one ``.npz``
part and every ``bytes`` value into its own part, and keeps the JSON-safe remainder in the
manifest. Phase 02 hashes ``Blob.pack()`` with blake3 for the content-addressed store.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Mapping
from typing import Any

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict
from pydantic_core import to_jsonable_python

from astro_canvas.sdk.errors import BlobError

ARRAYS_PART = "arrays.npz"
MANIFEST_NAME = "manifest.json"
ARRAY_KEY = "$ndarray"
BYTES_KEY = "$bytes"
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class Blob(BaseModel):
    """A serialized port value: JSON ``manifest`` plus named binary ``parts``."""

    model_config = ConfigDict(frozen=True)

    manifest: dict[str, Any]
    parts: dict[str, bytes] = {}

    @property
    def size(self) -> int:
        """Total size of the binary parts in bytes."""
        return sum(len(p) for p in self.parts.values())

    def pack(self) -> bytes:
        """Encode as a deterministic (stored, fixed-timestamp) zip; see ``unpack``."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as zf:
            manifest = json.dumps(self.manifest, sort_keys=True, separators=(",", ":"))
            zf.writestr(zipfile.ZipInfo(MANIFEST_NAME, _ZIP_TIME), manifest.encode())
            for name in sorted(self.parts):
                zf.writestr(zipfile.ZipInfo(f"parts/{name}", _ZIP_TIME), self.parts[name])
        return buffer.getvalue()

    @classmethod
    def unpack(cls, data: bytes) -> Blob:
        """Inverse of ``pack``."""
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                manifest = json.loads(zf.read(MANIFEST_NAME))
                parts = {
                    n.removeprefix("parts/"): zf.read(n)
                    for n in zf.namelist()
                    if n.startswith("parts/")
                }
        except (zipfile.BadZipFile, KeyError, ValueError) as exc:
            raise BlobError(f"not a packed blob: {exc}") from exc
        return cls(manifest=manifest, parts=parts)


def split_binary(
    data: Any, path: str = ""
) -> tuple[Any, dict[str, npt.NDArray[Any]], dict[str, bytes]]:
    """Replace ndarray/bytes leaves with placeholders; return ``(json_data, arrays, blobs)``."""
    arrays: dict[str, npt.NDArray[Any]] = {}
    binaries: dict[str, bytes] = {}

    def walk(value: Any, at: str) -> Any:
        if isinstance(value, np.ndarray):
            if value.dtype == object:
                raise BlobError(f"object array at {at!r} cannot be serialized")
            arrays[at] = value
            return {ARRAY_KEY: at}
        if isinstance(value, bytes | bytearray | memoryview):
            binaries[at] = bytes(value)
            return {BYTES_KEY: at}
        if isinstance(value, Mapping):
            return {str(k): walk(v, f"{at}.{k}" if at else str(k)) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [walk(v, f"{at}.{i}" if at else str(i)) for i, v in enumerate(value)]
        return value

    return walk(data, path), arrays, binaries


def join_binary(
    data: Any, arrays: Mapping[str, npt.NDArray[Any]], binaries: Mapping[str, bytes]
) -> Any:
    """Inverse of ``split_binary``: substitute placeholders back."""

    def walk(value: Any) -> Any:
        if isinstance(value, Mapping):
            if set(value) == {ARRAY_KEY}:
                key = str(value[ARRAY_KEY])
                if key not in arrays:
                    raise BlobError(f"missing array part {key!r}")
                return arrays[key]
            if set(value) == {BYTES_KEY}:
                key = str(value[BYTES_KEY])
                if key not in binaries:
                    raise BlobError(f"missing bytes part {key!r}")
                return binaries[key]
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(data)


def encode_npz(arrays: Mapping[str, npt.NDArray[Any]]) -> bytes:
    """Serialize arrays into an uncompressed ``.npz`` (pickle-free)."""
    buffer = io.BytesIO()
    kwargs: dict[str, Any] = dict(arrays)
    np.savez(buffer, **kwargs)
    return buffer.getvalue()


def decode_npz(data: bytes) -> dict[str, npt.NDArray[Any]]:
    """Load arrays from ``.npz`` bytes without allowing pickles."""
    try:
        with np.load(io.BytesIO(data), allow_pickle=False) as npz:
            return {name: npz[name] for name in npz.files}
    except (OSError, ValueError) as exc:
        raise BlobError(f"invalid npz part: {exc}") from exc


def to_manifest_data(data: Any) -> Any:
    """Make placeholder-substituted data JSON-safe (dates, enums, numpy scalars, ...)."""
    return to_jsonable_python(data, fallback=_numpy_fallback)


def _numpy_fallback(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    raise BlobError(f"value of type {type(value).__name__} is not JSON-serializable")
