"""Safe zip handling shared by bundle import and the ``uv`` download fallback (design 11).

A zip that arrives from outside the machine is hostile until proven otherwise: entries may try to
escape the destination (``../../.ssh/authorized_keys``), to fill the disk (a "zip bomb" of a few
kilobytes expanding to gigabytes), or to smuggle a pickle that some later reader would load.
``inspect_zip`` rejects all three before a single byte is written.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_ENTRIES = 4096
"""Refuse archives with more members than this (a bundle has tens, not thousands)."""

MAX_TOTAL_BYTES = 4 * 1024**3
"""Refuse archives whose members add up to more than 4 GiB uncompressed."""

MAX_RATIO = 200.0
"""Refuse archives that expand more than 200x (the classic zip bomb signature)."""

FORBIDDEN_SUFFIXES: tuple[str, ...] = (".pkl", ".pickle", ".pt", ".joblib", ".dill", ".marshal")
"""Pickle-shaped members are rejected outright: a bundle is never unpickled (design 7.2)."""


class ArchiveError(ValueError):
    """An archive is malformed, unsafe, or larger than the caps allow."""


@dataclass(frozen=True)
class ArchiveInfo:
    """What ``inspect_zip`` learned about an archive it accepted."""

    names: tuple[str, ...]
    total_bytes: int
    compressed_bytes: int

    @property
    def ratio(self) -> float:
        return self.total_bytes / self.compressed_bytes if self.compressed_bytes else 0.0


def _reject_name(name: str) -> str | None:
    """Why ``name`` may not be extracted, or ``None`` when it is safe."""
    if not name or name in (".", ".."):
        return "empty entry name"
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return "absolute path"
    if len(normalized) > 1 and normalized[1] == ":":
        return "drive-qualified path"
    parts = PurePosixPath(normalized).parts
    if any(part == ".." for part in parts):
        return "path traversal"
    return None


def inspect_zip(
    zf: zipfile.ZipFile,
    *,
    forbidden_suffixes: Sequence[str] = FORBIDDEN_SUFFIXES,
    max_entries: int = MAX_ENTRIES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_ratio: float = MAX_RATIO,
) -> ArchiveInfo:
    """Validate every member of ``zf`` against the traversal, bomb and pickle rules.

    Raises:
        ArchiveError: on the first member that breaks a rule.
    """
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise ArchiveError(f"archive has {len(infos)} entries (limit {max_entries})")
    total = compressed = 0
    names: list[str] = []
    for info in infos:
        reason = _reject_name(info.filename)
        if reason is not None:
            raise ArchiveError(f"unsafe entry {info.filename!r}: {reason}")
        # High bits of external_attr carry the Unix mode; 0o120000 is a symlink.
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ArchiveError(f"unsafe entry {info.filename!r}: symlink")
        suffix = PurePosixPath(info.filename).suffix.lower()
        if suffix in forbidden_suffixes:
            raise ArchiveError(
                f"unsafe entry {info.filename!r}: {suffix} is never read from a bundle"
            )
        total += info.file_size
        compressed += info.compress_size
        if total > max_total_bytes:
            raise ArchiveError(f"archive expands to more than {max_total_bytes} bytes")
        names.append(info.filename)
    if compressed > 0 and total / compressed > max_ratio:
        raise ArchiveError(
            f"archive expands {total / compressed:.0f}x "
            f"(limit {max_ratio:.0f}x); refusing to extract"
        )
    return ArchiveInfo(names=tuple(names), total_bytes=total, compressed_bytes=compressed)


def safe_extract(
    zf: zipfile.ZipFile,
    dest: Path,
    *,
    members: Iterable[str] | None = None,
    forbidden_suffixes: Sequence[str] = FORBIDDEN_SUFFIXES,
) -> list[Path]:
    """Validate ``zf`` and extract it (or ``members``) under ``dest``; returns the written files."""
    inspect_zip(zf, forbidden_suffixes=forbidden_suffixes)
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    wanted = list(members) if members is not None else [i.filename for i in zf.infolist()]
    written: list[Path] = []
    for name in wanted:
        if name.endswith("/"):
            continue
        target = dest.joinpath(*PurePosixPath(name.replace("\\", "/")).parts)
        if not target.resolve().is_relative_to(dest):
            raise ArchiveError(f"unsafe entry {name!r}: path traversal")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(name) as source, target.open("wb") as out:
            while chunk := source.read(1 << 20):
                out.write(chunk)
        written.append(target)
    return written


__all__ = [
    "FORBIDDEN_SUFFIXES",
    "MAX_ENTRIES",
    "MAX_RATIO",
    "MAX_TOTAL_BYTES",
    "ArchiveError",
    "ArchiveInfo",
    "inspect_zip",
    "safe_extract",
]
