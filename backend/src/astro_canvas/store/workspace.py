"""``Workspace``: a user folder plus its ``.astro-canvas/{app.db, blobs, scratch}`` state."""

from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePath

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from astro_canvas.engine.cache import BlobStore
from astro_canvas.store.db import make_engine, migrate
from astro_canvas.store.files import FileIndex

STATE_DIR = ".astro-canvas"
SAMPLES_DIR = "samples"
DOWNLOADS_DIR = "downloads"
UPLOADS_DIR = "uploads"
SHARED_DIR = "shared"
"""Prefix under which a lab server's read-only shared folder appears in every workspace."""

DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
"""A Windows drive letter, recognised on every platform (see ``safe_path``)."""


class PathOutsideWorkspaceError(ValueError):
    """A user-supplied path escapes the workspace root (traversal or symlink)."""


class ReadOnlyPathError(PathOutsideWorkspaceError):
    """A write was attempted inside the read-only shared mount."""


def safe_path(root: Path, relative: str | PurePath) -> Path:
    """Resolve ``relative`` under ``root``; reject absolute paths, ``..`` and symlinks.

    Raises:
        PathOutsideWorkspaceError: when the path would escape ``root``.
    """
    root = root.resolve()
    text = str(relative).replace("\\", "/")
    rel = PurePath(text)
    # A Windows drive prefix has to be refused on every platform, not just on Windows. `PurePath`
    # only recognises one where it is running, so on a Linux server `c:relative` would otherwise
    # become a file *named* `c:relative` inside the workspace -- the same request meaning two
    # different things on two servers is worse than either meaning.
    if DRIVE_PREFIX.match(text):
        raise PathOutsideWorkspaceError(f"absolute paths are not allowed: {relative!s}")
    if rel.is_absolute() or (rel.parts and rel.parts[0].endswith(":")):
        raise PathOutsideWorkspaceError(f"absolute paths are not allowed: {relative!s}")
    if any(part in ("..", "") for part in rel.parts):
        raise PathOutsideWorkspaceError(f"path traversal is not allowed: {relative!s}")
    candidate = root.joinpath(*rel.parts)
    probe = root
    for part in rel.parts:
        probe = probe / part
        if probe.is_symlink():
            raise PathOutsideWorkspaceError(f"symlinks are not allowed: {relative!s}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise PathOutsideWorkspaceError(f"path escapes the workspace: {relative!s}")
    return resolved


class Workspace:
    """Filesystem + database handle for one workspace root."""

    def __init__(
        self, root: Path, *, engine: Engine | None = None, shared: Path | None = None
    ) -> None:
        self.root = Path(root).resolve()
        self.shared = Path(shared).resolve() if shared else None
        """Read-only folder mounted as ``shared/`` (design 12); ``None`` on a desktop install."""
        self.state_dir = self.root / STATE_DIR
        self.db_path = self.state_dir / "app.db"
        self.blobs_dir = self.state_dir / "blobs"
        self.scratch_dir = self.state_dir / "scratch"
        for directory in (self.root, self.state_dir, self.blobs_dir, self.scratch_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.engine = engine if engine is not None else make_engine(self.db_path)
        migrate(self.engine)
        self.sessions: sessionmaker[Session] = sessionmaker(self.engine, expire_on_commit=False)
        self.blobs = BlobStore(self.blobs_dir)
        self.files = FileIndex(self.sessions)

    @classmethod
    def open(cls, root: Path, *, shared: Path | None = None) -> Workspace:
        return cls(root, shared=shared)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.sessions() as session:
            yield session

    def safe_path(self, relative: str | PurePath, *, write: bool = False) -> Path:
        """Resolve a workspace-relative path, honouring the ``shared/`` mount.

        Args:
            relative: A path as the REST API received it.
            write: Set for anything that creates, replaces or deletes; the shared mount refuses.

        Raises:
            ReadOnlyPathError: when ``write`` and the path is inside the shared mount.
            PathOutsideWorkspaceError: when the path escapes both roots.
        """
        rel = PurePath(str(relative).replace("\\", "/"))
        if self.shared is not None and rel.parts[:1] == (SHARED_DIR,):
            if write:
                raise ReadOnlyPathError(f"{SHARED_DIR}/ is read-only on this server")
            return safe_path(self.shared, PurePath(*rel.parts[1:]))
        return safe_path(self.root, relative)

    def mount_for(self, path: Path) -> tuple[Path, str]:
        """``(root, prefix)`` of the mount ``path`` belongs to; the prefix shapes API paths."""
        resolved = Path(path).resolve()
        if self.shared is not None and resolved.is_relative_to(self.shared):
            return self.shared, SHARED_DIR
        return self.root, ""

    def relative(self, path: Path) -> str:
        """Workspace-relative POSIX form of an absolute path inside the root or the mount."""
        root, prefix = self.mount_for(path)
        rel = Path(path).resolve().relative_to(root).as_posix()
        return f"{prefix}/{rel}" if prefix else rel

    @property
    def samples_dir(self) -> Path:
        """``<root>/samples`` (bundled pack sample data is copied here on first run)."""
        return self._sub(SAMPLES_DIR)

    @property
    def downloads_dir(self) -> Path:
        """``<root>/downloads`` (astroquery-style fetch nodes cache here by query hash)."""
        return self._sub(DOWNLOADS_DIR)

    @property
    def uploads_dir(self) -> Path:
        """``<root>/uploads`` (default target of the upload endpoint)."""
        return self._sub(UPLOADS_DIR)

    def _sub(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def new_scratch(self, prefix: str = "run-") -> Path:
        return Path(tempfile.mkdtemp(prefix=prefix, dir=self.scratch_dir))

    def clear_scratch(self) -> int:
        removed = 0
        for child in self.scratch_dir.iterdir():
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        return removed

    def close(self) -> None:
        self.engine.dispose()
