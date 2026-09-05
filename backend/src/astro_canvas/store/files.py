"""Workspace file metadata: directory listings, MIME/kind sniffing helpers and cached blake3.

Hashes live in the ``files`` table keyed by workspace-relative path; a row is reused while the
file's ``(mtime_ns, size)`` pair is unchanged, so repeated ``info`` calls on large FITS files do
not re-read them.
"""

from __future__ import annotations

import mimetypes
import threading
from dataclasses import dataclass
from pathlib import Path

from blake3 import blake3
from sqlalchemy.orm import Session, sessionmaker

from astro_canvas.store.models import FileRecord, utcnow

CHUNK = 4 * 1024 * 1024

mimetypes.add_type("application/fits", ".fits")
mimetypes.add_type("application/fits", ".fit")
mimetypes.add_type("application/fits", ".fts")
mimetypes.add_type("text/x-ecsv", ".ecsv")
mimetypes.add_type("application/x-hdf5", ".hdf5")
mimetypes.add_type("application/x-hdf5", ".h5")


@dataclass(frozen=True)
class FileInfo:
    """What the workspace API reports for one file."""

    path: str
    name: str
    size: int
    mtime: float
    blake3: str | None
    mime: str | None


@dataclass(frozen=True)
class Entry:
    """One row of a directory listing (``children`` is ``None`` for lazily listed folders)."""

    path: str
    name: str
    is_dir: bool
    size: int
    mtime: float
    mime: str | None
    children: tuple[Entry, ...] | None = None


def guess_mime(name: str) -> str | None:
    mime, _ = mimetypes.guess_type(name)
    return mime


def hash_path(path: Path) -> str:
    """blake3 hex digest of a file's content, streamed in 4 MiB chunks."""
    hasher = blake3()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            hasher.update(chunk)
    return str(hasher.hexdigest())


def relative_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def list_dir(
    root: Path, directory: Path, *, depth: int = 1, hidden: bool = False, prefix: str = ""
) -> list[Entry]:
    """Sorted entries of ``directory`` (folders first); folders deeper than ``depth`` are lazy.

    Hidden entries (dot-prefixed, including ``.astro-canvas``) are skipped unless ``hidden``.
    ``prefix`` names the mount the listing came from (``shared`` on a lab server), so the reported
    paths are what the API will accept back.
    """
    entries: list[Entry] = []
    try:
        children = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return entries
    for child in children:
        if not hidden and child.name.startswith("."):
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        is_dir = child.is_dir()
        nested: tuple[Entry, ...] | None = None
        if is_dir and depth > 1:
            nested = tuple(list_dir(root, child, depth=depth - 1, hidden=hidden, prefix=prefix))
        rel = relative_posix(root, child)
        entries.append(
            Entry(
                path=f"{prefix}/{rel}" if prefix else rel,
                name=child.name,
                is_dir=is_dir,
                size=0 if is_dir else stat.st_size,
                mtime=stat.st_mtime,
                mime=None if is_dir else guess_mime(child.name),
                children=nested,
            )
        )
    return entries


class FileIndex:
    """``files`` table: blake3 per relative path, invalidated by ``(mtime_ns, size)``."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._lock = threading.Lock()

    def info(  # noqa: A002
        self, root: Path, path: Path, *, hash: bool = True, rel: str | None = None
    ) -> FileInfo:
        """Size, mtime, MIME and (optionally cached) blake3 of ``path`` under ``root``.

        ``rel`` overrides the cache key and the reported path, which is how a file inside the
        read-only ``shared/`` mount keeps its prefix instead of colliding with the user's own.
        """
        stat = path.stat()
        rel = relative_posix(root, path) if rel is None else rel
        digest: str | None = None
        if hash:
            digest = self.cached_hash(rel, stat.st_mtime_ns, stat.st_size)
            if digest is None:
                digest = hash_path(path)
                self.remember(rel, stat.st_mtime_ns, stat.st_size, digest)
        return FileInfo(
            path=rel,
            name=path.name,
            size=stat.st_size,
            mtime=stat.st_mtime,
            blake3=digest,
            mime=guess_mime(path.name),
        )

    def cached_hash(self, rel: str, mtime_ns: int, size: int) -> str | None:
        with self._lock, self._sessions() as session:
            row = session.get(FileRecord, rel)
            if row is None or row.mtime_ns != mtime_ns or row.size != size:
                return None
            return row.blake3

    def remember(self, rel: str, mtime_ns: int, size: int, digest: str) -> None:
        with self._lock, self._sessions() as session:
            row = session.get(FileRecord, rel)
            if row is None:
                session.add(FileRecord(path=rel, mtime_ns=mtime_ns, size=size, blake3=digest))
            else:
                row.mtime_ns, row.size, row.blake3, row.hashed = mtime_ns, size, digest, utcnow()
            session.commit()

    def forget(self, rel: str) -> None:
        with self._lock, self._sessions() as session:
            row = session.get(FileRecord, rel)
            if row is not None:
                session.delete(row)
                session.commit()
