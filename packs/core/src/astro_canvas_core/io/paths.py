"""Workspace-relative path resolution for nodes (same rules as the server's ``safe_path``)."""

from __future__ import annotations

import mimetypes
from pathlib import Path, PurePath

from blake3 import blake3

from astro_canvas_core.types import File


class WorkspacePathError(ValueError):
    """A node was given a path that leaves the workspace (absolute, ``..`` or symlink)."""


def resolve_in_workspace(root: Path, relative: str | PurePath) -> Path:
    """Resolve ``relative`` under ``root``; reject absolute paths, ``..`` and symlinks."""
    root = Path(root).resolve()
    text = str(relative).strip().replace("\\", "/")
    rel = PurePath(text)
    if rel.is_absolute() or (rel.parts and rel.parts[0].endswith(":")) or text.startswith("//"):
        raise WorkspacePathError(f"absolute paths are not allowed: {relative!s}")
    if any(part in ("..", "") for part in rel.parts):
        raise WorkspacePathError(f"path traversal is not allowed: {relative!s}")
    probe = root
    for part in rel.parts:
        probe = probe / part
        if probe.is_symlink():
            raise WorkspacePathError(f"symlinks are not allowed: {relative!s}")
    resolved = root.joinpath(*rel.parts).resolve()
    if not resolved.is_relative_to(root):
        raise WorkspacePathError(f"path escapes the workspace: {relative!s}")
    return resolved


def file_fingerprint(path: str = "", *, workspace: Path | None = None, **_: object) -> str:
    """Cache-key fingerprint of a workspace file: ``mtime_ns:size`` (or ``missing``).

    Used as ``fingerprint=`` on the loader nodes so editing or replacing a file re-runs them.
    """
    if not path or workspace is None:
        return "no-path"
    try:
        target = resolve_in_workspace(Path(workspace), path)
        stat = target.stat()
    except (WorkspacePathError, OSError):
        return "missing"
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def describe_file(root: Path, target: Path, *, hash_content: bool = True) -> File:
    """Build an ``astro.File`` value for ``target`` (blake3 streamed in 4 MiB chunks)."""
    digest: str | None = None
    if hash_content:
        hasher = blake3()
        with target.open("rb") as handle:
            while chunk := handle.read(4 * 1024 * 1024):
                hasher.update(chunk)
        digest = str(hasher.hexdigest())
    mime, _ = mimetypes.guess_type(target.name)
    return File(
        path=target.resolve().relative_to(Path(root).resolve()).as_posix(),
        blake3=digest,
        size=target.stat().st_size,
        mime=mime,
    )


__all__ = ["WorkspacePathError", "describe_file", "file_fingerprint", "resolve_in_workspace"]
