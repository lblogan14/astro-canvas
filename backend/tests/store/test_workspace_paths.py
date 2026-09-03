"""Path safety of the workspace API (design 11): traversal, absolute paths, symlinks, odd input."""

from __future__ import annotations

import os
from pathlib import Path, PurePath

import pytest

from astro_canvas.store.workspace import PathOutsideWorkspaceError, safe_path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "data" / "sub").mkdir(parents=True)
    (root / "data" / "spec.fits").write_bytes(b"SIMPLE")
    return root


@pytest.mark.parametrize(
    "relative",
    [
        "data/spec.fits",
        "data\\spec.fits",
        "./data/spec.fits",
        "data/./sub",
        "data/sub/new file with spaces.fits",
        "data/ünïcødé.dat",
        "",
        ".",
    ],
)
def test_accepts_paths_inside_the_root(root: Path, relative: str) -> None:
    resolved = safe_path(root, relative)
    assert resolved.is_relative_to(root.resolve())


def test_resolves_to_the_expected_file(root: Path) -> None:
    assert safe_path(root, "data/spec.fits") == (root / "data" / "spec.fits").resolve()
    assert safe_path(root, PurePath("data") / "sub") == (root / "data" / "sub").resolve()
    assert safe_path(root, "") == root.resolve()


@pytest.mark.parametrize(
    "relative",
    [
        "../x",
        "..",
        "data/../../x",
        "data/sub/../../../etc/passwd",
        "..\\x",
        "data\\..\\..\\x",
        "/etc/passwd",
        "\\\\server\\share\\x",
        "C:/Windows/system32",
        "C:\\Windows",
        "c:relative",
        "/",
        "//x",
    ],
)
def test_rejects_traversal_and_absolute_paths(root: Path, relative: str) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        safe_path(root, relative)


def test_rejects_encoded_and_embedded_null(root: Path) -> None:
    for bad in ("data/%2e%2e/x", "data/x\x00y"):
        try:
            resolved = safe_path(root, bad)
        except (PathOutsideWorkspaceError, ValueError):
            continue
        # `%2e%2e` is a literal folder name, not traversal: it must stay inside the root.
        assert resolved.is_relative_to(root.resolve())


def test_rejects_symlinks_when_the_platform_can_create_them(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted here")
    with pytest.raises(PathOutsideWorkspaceError):
        safe_path(root, "link")
    with pytest.raises(PathOutsideWorkspaceError):
        safe_path(root, "link/secret.txt")
    # A symlink pointing *inside* the root is still refused: the rule is "no symlinks".
    inner = root / "data" / "alias"
    inner.symlink_to(root / "data" / "sub", target_is_directory=True)
    with pytest.raises(PathOutsideWorkspaceError):
        safe_path(root, "data/alias/file")


@pytest.mark.skipif(os.name != "nt", reason="Windows drive and UNC forms")
def test_windows_specific_forms(root: Path) -> None:  # pragma: no cover - windows only
    for bad in ("D:\\other", "d:/other", "\\\\?\\C:\\x", "CON", "data/aux.txt:stream"):
        try:
            resolved = safe_path(root, bad)
        except PathOutsideWorkspaceError:
            continue
        assert resolved.is_relative_to(root.resolve())
