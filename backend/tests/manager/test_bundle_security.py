"""Hostile ``.acw`` fixtures: path traversal, zip bombs, pickles, and symlinked members.

Design 11: a bundle arrives from outside the machine, so nothing is extracted before the whole
archive has been inspected, and pickle is never read from one.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from astro_canvas.manager.archive import ArchiveError, inspect_zip, safe_extract
from astro_canvas.manager.bundles import BundleError, open_bundle
from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings
from tests.conftest import authed_client

DOC = b'{"format": "astro-canvas/workflow", "version": 1, "id": "wf", "name": "Evil"}'


def build(members: dict[str, bytes], *, with_workflow: bool = True) -> bytes:
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if with_workflow:
            zf.writestr("workflow.json", DOC)
        for name, payload in members.items():
            zf.writestr(name, payload)
    return sink.getvalue()


def build_raw(names: list[str]) -> bytes:
    """A zip whose member names bypass ``writestr``'s sanitising (an attacker's toolchain)."""
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w") as zf:
        zf.writestr("workflow.json", DOC)
        for name in names:
            info = zipfile.ZipInfo(filename="placeholder")
            info.filename = name  # set after construction: writestr would normalise it
            zf.writestr(info, b"pwned")
    return sink.getvalue()


@pytest.fixture
def client(settings: Settings, discovery: DiscoveryResult) -> Iterator[TestClient]:
    with authed_client(create_app(settings, discovery)) as client:
        yield client


def upload(client: TestClient, payload: bytes) -> object:
    return client.post(
        "/api/bundles/import", files={"file": ("evil.acw", payload, "application/zip")}
    )


# --- path traversal -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../evil.txt",
        "../../etc/passwd",
        "inputs/../../escape.txt",
        "/absolute.txt",
        "C:/windows/system32/evil.txt",
        "inputs/..\\..\\escape.txt",
    ],
)
def test_traversal_entries_are_rejected(name: str) -> None:
    with (
        zipfile.ZipFile(io.BytesIO(build_raw([name]))) as zf,
        pytest.raises(ArchiveError, match="unsafe entry"),
    ):
        inspect_zip(zf)


def test_a_traversal_bundle_is_refused_by_the_import_endpoint(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    response = upload(client, build_raw(["../../pwned.txt"]))
    assert response.status_code == 400
    assert "unsafe entry" in response.json()["detail"]
    assert not (Path(settings.workspace).parent / "pwned.txt").exists()
    assert not (tmp_path / "pwned.txt").exists()


def test_safe_extract_writes_only_under_the_destination(tmp_path: Path) -> None:
    payload = build({"inputs/data/a.txt": b"ok", "outputs/b.json": b"{}"})
    dest = tmp_path / "out"
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        written = safe_extract(zf, dest)
    assert {p.relative_to(dest).as_posix() for p in written} == {
        "workflow.json",
        "inputs/data/a.txt",
        "outputs/b.json",
    }


def test_a_symlink_member_is_rejected() -> None:
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w") as zf:
        zf.writestr("workflow.json", DOC)
        info = zipfile.ZipInfo("inputs/link")
        info.external_attr = (0o120777 << 16) | 0o200000
        zf.writestr(info, "/etc/passwd")
    with (
        zipfile.ZipFile(io.BytesIO(sink.getvalue())) as zf,
        pytest.raises(ArchiveError, match="symlink"),
    ):
        inspect_zip(zf)


# --- pickle ----------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["outputs/model.pkl", "inputs/data.pickle", "a/b/c.joblib"])
def test_pickle_shaped_members_are_rejected(name: str, client: TestClient) -> None:
    """Nothing in a bundle is ever unpickled, so a pickle has no business being in one."""
    payload = build({name: b"\x80\x04\x95dangerous"})
    with pytest.raises(BundleError, match="never read from a bundle"):
        open_bundle(payload)
    assert upload(client, payload).status_code == 400


def test_the_word_pickle_never_appears_in_the_import_path() -> None:
    """A grep-level guard: no module under ``manager/`` may import pickle."""
    manager = Path(__file__).resolve().parents[2] / "src" / "astro_canvas" / "manager"
    for path in manager.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "import pickle" not in source, f"{path.name} imports pickle"
        assert "pickle.load" not in source, f"{path.name} calls pickle.load"


# --- zip bombs -------------------------------------------------------------------------------


def test_a_zip_bomb_is_refused_before_anything_is_written(client: TestClient) -> None:
    """1 MiB of zeros compresses to a few hundred bytes; the ratio cap catches it."""
    payload = build({"inputs/bomb.bin": b"\0" * (8 * 1024 * 1024)})
    assert len(payload) < 64 * 1024
    with pytest.raises(BundleError, match="expands"):
        open_bundle(payload)
    assert upload(client, payload).status_code == 400


def test_an_oversized_archive_is_refused() -> None:
    payload = build({"inputs/big.bin": b"x" * 4096})
    with (
        zipfile.ZipFile(io.BytesIO(payload)) as zf,
        pytest.raises(ArchiveError, match="expands to more than"),
    ):
        inspect_zip(zf, max_total_bytes=1024, max_ratio=1e9)


def test_too_many_entries_is_refused() -> None:
    payload = build({f"inputs/f{i}.txt": b"x" for i in range(50)})
    with (
        zipfile.ZipFile(io.BytesIO(payload)) as zf,
        pytest.raises(ArchiveError, match="entries"),
    ):
        inspect_zip(zf, max_entries=10)


def test_a_normal_bundle_passes_every_check() -> None:
    payload = build({"inputs/a.txt": b"hello", "figures/card.png": b"\x89PNG\r\n\x1a\n"})
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        info = inspect_zip(zf)
    assert "workflow.json" in info.names
    assert info.total_bytes > 0


# --- malformed archives ----------------------------------------------------------------------


def test_a_file_that_is_not_a_zip_or_a_document_is_refused(client: TestClient) -> None:
    assert upload(client, b"PK\x03\x04 not really a zip").status_code == 400
    assert upload(client, b"just some text").status_code == 400


def test_a_zip_without_a_workflow_is_refused(client: TestClient) -> None:
    response = upload(client, build({"README.md": b"hi"}, with_workflow=False))
    assert response.status_code == 400
    assert "workflow.json" in response.json()["detail"]
