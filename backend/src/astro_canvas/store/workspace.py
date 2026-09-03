"""``Workspace``: a user folder plus its ``.astro-canvas/{app.db, blobs, scratch}`` state."""

from __future__ import annotations

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


class PathOutsideWorkspaceError(ValueError):
    """A user-supplied path escapes the workspace root (traversal or symlink)."""


def safe_path(root: Path, relative: str | PurePath) -> Path:
    """Resolve ``relative`` under ``root``; reject absolute paths, ``..`` and symlinks.

    Raises:
        PathOutsideWorkspaceError: when the path would escape ``root``.
    """
    root = root.resolve()
    rel = PurePath(str(relative).replace("\\", "/"))
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

    def __init__(self, root: Path, *, engine: Engine | None = None) -> None:
        self.root = Path(root).resolve()
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
    def open(cls, root: Path) -> Workspace:
        return cls(root)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.sessions() as session:
            yield session

    def safe_path(self, relative: str | PurePath) -> Path:
        return safe_path(self.root, relative)

    def relative(self, path: Path) -> str:
        """Workspace-relative POSIX form of an absolute path inside the root."""
        return Path(path).resolve().relative_to(self.root).as_posix()

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
