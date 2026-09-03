"""Memory-mapping large arrays straight out of a packed blob file.

A packed blob is an uncompressed (``ZIP_STORED``) zip, so a part that holds a single array in
``.npy`` format sits in the file as a header followed by raw, contiguous bytes. ``memmap_part``
finds that byte range and hands back a read-only ``numpy.memmap`` view of it: an IFU cube is
therefore *referenced* from the content-addressed store rather than copied into the process.

Port types opt in by listing field names in ``PortType.__mmap_fields__``; arrays at or above
``mmap_min_bytes()`` (``ASTRO_CANVAS_MMAP_MIN_BYTES``, 8 MiB by default) get their own part.
"""

from __future__ import annotations

import os
import struct
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from astro_canvas.sdk.errors import BlobError

NPY_SUFFIX = ".npy"
PART_PREFIX = "parts/"
MMAP_MIN_BYTES_ENV = "ASTRO_CANVAS_MMAP_MIN_BYTES"
DEFAULT_MMAP_MIN_BYTES = 8 * 1024 * 1024
_LOCAL_HEADER = struct.Struct("<4s5H3I2H")
"""ZIP local file header: signature, version, flags, method, time, date, crc, sizes, name/extra."""


def mmap_min_bytes() -> int:
    """Smallest array that gets its own memory-mappable part (0 disables the split)."""
    raw = os.environ.get(MMAP_MIN_BYTES_ENV)
    if raw is None:
        return DEFAULT_MMAP_MIN_BYTES
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_MMAP_MIN_BYTES


def encode_npy(array: npt.NDArray[Any]) -> bytes:
    """Serialize one array in ``.npy`` format (pickle-free), C-contiguous."""
    import io  # noqa: PLC0415 - only needed when a blob is written

    if array.dtype == object:
        raise BlobError("object arrays cannot be serialized")
    buffer = io.BytesIO()
    np.lib.format.write_array(buffer, np.ascontiguousarray(array), allow_pickle=False)
    return buffer.getvalue()


def decode_npy(data: bytes) -> npt.NDArray[Any]:
    """Read an array back from ``.npy`` bytes."""
    import io  # noqa: PLC0415

    try:
        return np.lib.format.read_array(io.BytesIO(data), allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise BlobError(f"invalid npy part: {exc}") from exc


def stored_part_offset(path: Path, name: str) -> int | None:
    """Byte offset of an *uncompressed* part's data inside a packed blob, or ``None``.

    ``None`` means "read the part normally": the file is not a zip, the member is missing, or it
    was stored compressed (nothing this package writes is, but a hand-made blob might be).
    """
    try:
        with zipfile.ZipFile(path) as zf:
            info = zf.getinfo(f"{PART_PREFIX}{name}")
            if info.compress_type != zipfile.ZIP_STORED:
                return None
            header_offset = info.header_offset
        with path.open("rb") as handle:
            handle.seek(header_offset)
            header = handle.read(_LOCAL_HEADER.size)
            if len(header) != _LOCAL_HEADER.size:
                return None
            fields = _LOCAL_HEADER.unpack(header)
            if fields[0] != b"PK\x03\x04":
                return None
            name_len, extra_len = int(fields[-2]), int(fields[-1])
        return int(header_offset) + _LOCAL_HEADER.size + name_len + extra_len
    except (KeyError, OSError, zipfile.BadZipFile, struct.error):
        return None


def memmap_part(path: Path, name: str) -> npt.NDArray[Any] | None:
    """Read-only ``numpy.memmap`` of the ``.npy`` part ``name`` inside the blob at ``path``.

    Returns ``None`` when the part cannot be mapped (compressed member, unreadable header, or a
    Fortran-ordered array); callers then fall back to reading the bytes.
    """
    offset = stored_part_offset(path, name)
    if offset is None:
        return None
    readers = {
        (1, 0): np.lib.format.read_array_header_1_0,
        (2, 0): np.lib.format.read_array_header_2_0,
    }
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            reader = readers.get(np.lib.format.read_magic(handle))
            if reader is None:
                return None
            shape, fortran_order, dtype = reader(handle)
            data_offset = handle.tell()
        if fortran_order or dtype.hasobject:
            return None
        return np.memmap(path, dtype=dtype, mode="r", offset=data_offset, shape=tuple(shape))
    except (OSError, ValueError):
        return None


def is_memmapped(array: Any) -> bool:
    """True when ``array`` (or its base) is backed by a memory map rather than process memory."""
    if isinstance(array, np.memmap):
        return True
    base = getattr(array, "base", None)
    return isinstance(base, np.memmap)


__all__ = [
    "DEFAULT_MMAP_MIN_BYTES",
    "MMAP_MIN_BYTES_ENV",
    "NPY_SUFFIX",
    "PART_PREFIX",
    "decode_npy",
    "encode_npy",
    "is_memmapped",
    "memmap_part",
    "mmap_min_bytes",
    "stored_part_offset",
]
