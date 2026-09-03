"""``/api/workspace``: info, select, tree, upload (plain and chunked), info, download, sniff."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from fastapi.testclient import TestClient

from astro_canvas.engine.events import EventBus, WorkspaceChanged
from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.app import create_app
from astro_canvas.server.watcher import WorkspaceWatcher
from astro_canvas.settings import Settings
from tests.conftest import authed_client


@pytest.fixture
def api(settings: Settings, test_discovery: DiscoveryResult) -> Iterator[TestClient]:
    settings.watch_workspace = False
    with authed_client(create_app(settings, test_discovery)) as client:
        yield client


def _root(api: TestClient) -> Path:
    return Path(api.get("/api/workspace").json()["root"])


def test_info_tree_mkdir_and_hidden_state_dir(api: TestClient, settings: Settings) -> None:
    info = api.get("/api/workspace").json()
    assert Path(info["root"]) == settings.workspace.resolve()
    assert info["recent"][0] == info["root"]
    assert {"samples_dir", "downloads_dir", "uploads_dir"} <= set(info)

    created = api.post("/api/workspace/mkdir", json={"path": "data/raw"})
    assert created.status_code == 201 and created.json()["path"] == "data/raw"
    (_root(api) / "data" / "spec.fits").write_bytes(b"SIMPLE  = T")

    tree = api.get("/api/workspace/tree").json()
    names = [e["name"] for e in tree["entries"]]
    assert ".astro-canvas" not in names and "data" in names
    data = next(e for e in tree["entries"] if e["name"] == "data")
    assert data["is_dir"] and data["children"] is None

    deep = api.get("/api/workspace/tree", params={"path": "data", "depth": 2}).json()
    assert deep["path"] == "data"
    raw = next(e for e in deep["entries"] if e["name"] == "raw")
    assert raw["children"] == []
    spec = next(e for e in deep["entries"] if e["name"] == "spec.fits")
    assert spec["mime"] == "application/fits" and spec["size"] == 11

    hidden = api.get("/api/workspace/tree", params={"hidden": "true"}).json()
    assert ".astro-canvas" in [e["name"] for e in hidden["entries"]]
    assert api.get("/api/workspace/tree", params={"path": "nope"}).status_code == 404


@pytest.mark.parametrize(
    "bad", ["../x", "/etc/passwd", "C:/Windows", "data/../../x", "..\\x", "\\\\srv\\share"]
)
def test_path_traversal_is_rejected_with_400(api: TestClient, bad: str) -> None:
    assert api.get("/api/workspace/tree", params={"path": bad}).status_code == 400
    assert api.get("/api/workspace/info", params={"path": bad}).status_code == 400
    assert api.get("/api/workspace/file", params={"path": bad}).status_code == 400
    assert api.get("/api/workspace/sniff", params={"path": bad}).status_code == 400
    assert api.post("/api/workspace/mkdir", json={"path": bad}).status_code == 400
    assert api.delete("/api/workspace/file", params={"path": bad}).status_code == 400
    upload = api.post("/api/workspace/upload", files={"file": ("x.txt", b"hi")}, data={"dir": bad})
    assert upload.status_code == 400
    upload = api.post(
        "/api/workspace/upload", files={"file": ("x.txt", b"hi")}, data={"filename": bad}
    )
    assert upload.status_code == 400


def test_symlink_inside_workspace_is_rejected(api: TestClient, tmp_path: Path) -> None:
    root = _root(api)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("x", encoding="utf-8")
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted here")
    assert api.get("/api/workspace/tree", params={"path": "link"}).status_code == 400
    assert api.get("/api/workspace/file", params={"path": "link/secret"}).status_code == 400


def test_upload_info_download_and_delete(api: TestClient) -> None:
    payload = b"\x00\x01" * 5000
    response = api.post(
        "/api/workspace/upload", files={"file": ("blob.bin", payload)}, data={"dir": "uploads"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["complete"] and body["received"] == len(payload)
    assert body["file"]["path"] == "uploads/blob.bin" and body["file"]["size"] == len(payload)
    assert len(body["file"]["blake3"]) == 64

    again = api.post("/api/workspace/upload", files={"file": ("blob.bin", payload)})
    assert again.status_code == 409
    renamed = api.post(
        "/api/workspace/upload",
        files={"file": ("blob.bin", payload)},
        data={"on_conflict": "rename"},
    )
    assert renamed.json()["file"]["path"] == "uploads/blob (1).bin"
    replaced = api.post(
        "/api/workspace/upload", files={"file": ("blob.bin", b"new")}, data={"overwrite": "true"}
    )
    assert replaced.json()["file"]["size"] == 3

    info = api.get("/api/workspace/info", params={"path": "uploads/blob.bin"}).json()
    assert info["size"] == 3 and info["blake3"] == replaced.json()["file"]["blake3"]
    cheap = api.get("/api/workspace/info", params={"path": "uploads/blob.bin", "hash": "false"})
    assert cheap.json()["blake3"] is None

    download = api.get("/api/workspace/file", params={"path": "uploads/blob.bin"})
    assert download.status_code == 200 and download.content == b"new"
    assert api.get("/api/workspace/info", params={"path": "uploads/none"}).status_code == 404
    assert api.get("/api/workspace/file", params={"path": "uploads"}).status_code == 404

    assert api.delete("/api/workspace/file", params={"path": "uploads/blob.bin"}).status_code == 204
    assert api.delete("/api/workspace/file", params={"path": "uploads/blob.bin"}).status_code == 404
    assert api.delete("/api/workspace/file", params={"path": "uploads"}).status_code == 409
    assert (
        api.delete(
            "/api/workspace/file", params={"path": "uploads", "recursive": "true"}
        ).status_code
        == 204
    )
    assert api.delete("/api/workspace/file", params={"path": ""}).status_code == 400
    assert api.delete("/api/workspace/file", params={"path": ".astro-canvas"}).status_code == 400


def test_chunked_upload_assembles_in_order(api: TestClient) -> None:
    chunks = [b"a" * 1000, b"b" * 1000, b"c" * 10]
    for index, chunk in enumerate(chunks):
        response = api.post(
            "/api/workspace/upload",
            files={"file": ("big.dat", chunk)},
            data={
                "dir": "data",
                "upload_id": "up-1",
                "chunk_index": str(index),
                "chunk_count": str(len(chunks)),
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["complete"] is (index == len(chunks) - 1)
        assert body["received"] == len(chunk)
    assert body["file"]["path"] == "data/big.dat" and body["file"]["size"] == 2010
    assert (_root(api) / "data" / "big.dat").read_bytes() == b"".join(chunks)
    assert not list((_root(api) / ".astro-canvas" / "uploads").glob("*.part"))

    late = api.post(
        "/api/workspace/upload",
        files={"file": ("x.dat", b"x")},
        data={"upload_id": "fresh", "chunk_index": "1", "chunk_count": "2"},
    )
    assert late.status_code == 409
    bad_id = api.post(
        "/api/workspace/upload",
        files={"file": ("x.dat", b"x")},
        data={"upload_id": "../evil", "chunk_index": "0", "chunk_count": "2"},
    )
    assert bad_id.status_code == 400
    out_of_range = api.post(
        "/api/workspace/upload",
        files={"file": ("x.dat", b"x")},
        data={"upload_id": "ok", "chunk_index": "5", "chunk_count": "2"},
    )
    assert out_of_range.status_code == 400


def _write_fits_fixtures(root: Path) -> None:
    n = 64
    spec_hdu = fits.PrimaryHDU(np.ones(n, dtype=np.float32))
    spec_hdu.header.update({"CRVAL1": 4000.0, "CDELT1": 1.0, "CRPIX1": 1, "CTYPE1": "WAVE"})
    spec_hdu.writeto(root / "spec1d.fits")
    fits.PrimaryHDU(np.zeros((8, 8), dtype=np.float32)).writeto(root / "image.fits")
    fits.PrimaryHDU(np.zeros((4, 3, 3), dtype=np.float32)).writeto(root / "cube.fits")
    sdss = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="flux", format="E", array=np.ones(n)),
            fits.Column(name="loglam", format="E", array=np.linspace(3.6, 3.8, n)),
            fits.Column(name="ivar", format="E", array=np.ones(n)),
        ],
        name="COADD",
    )
    fits.HDUList([fits.PrimaryHDU(), sdss]).writeto(root / "sdss.fits")
    table = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="RA", format="D", array=np.zeros(3)),
            fits.Column(name="DEC", format="D", array=np.zeros(3)),
        ]
    )
    fits.HDUList([fits.PrimaryHDU(), table]).writeto(root / "catalog.fits")
    muse = fits.HDUList(
        [fits.PrimaryHDU(), fits.ImageHDU(np.zeros((3, 2, 2), dtype=np.float32), name="DATA")]
    )
    muse.writeto(root / "muse.fits")
    Table({"wave": [1.0, 2.0], "flux": [3.0, 4.0]}).write(root / "spec.ecsv", format="ascii.ecsv")
    Table({"a": [1, 2], "b": ["x", "y"]}).write(root / "rows.csv", format="ascii.csv")
    (root / "two_cols.dat").write_text("6559.6 278.8\n6560.8 329.6\n", encoding="utf-8")
    (root / "rbspec.json").write_text(
        '{"wave_slice": [1, 2], "flux_slice": [1, 1], "zabs": 0.0}', encoding="utf-8"
    )
    (root / "notes.md").write_text("# hi\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "kind", "node"),
    [
        ("spec1d.fits", "spectrum", "core.io.load_spectrum"),
        ("image.fits", "image", "core.io.load_image"),
        ("cube.fits", "cube", "core.io.load_cube"),
        ("sdss.fits", "spectrum", "core.io.load_spectrum"),
        ("catalog.fits", "table", "core.io.load_table"),
        ("muse.fits", "cube", "core.io.load_cube"),
        ("spec.ecsv", "spectrum", "core.io.load_spectrum"),
        ("rows.csv", "table", "core.io.load_table"),
        ("two_cols.dat", "spectrum", "core.io.load_spectrum"),
        ("rbspec.json", "spectrum", "core.io.load_spectrum"),
        ("notes.md", "unknown", None),
    ],
)
def test_sniff_picks_the_loader(api: TestClient, name: str, kind: str, node: str | None) -> None:
    root = _root(api)
    if not (root / "spec1d.fits").exists():
        _write_fits_fixtures(root)
    body = api.get("/api/workspace/sniff", params={"path": name}).json()
    assert body["kind"] == kind and body["node"] == node, body


def test_select_switches_workspace_and_recent(api: TestClient, tmp_path: Path) -> None:
    original = _root(api)
    api.post("/api/workflows", json={"id": "wf", "nodes": {}})
    assert api.get("/api/workflows/wf").status_code == 200

    other = tmp_path / "other-ws"
    missing = api.post("/api/workspace/select", json={"path": str(other)})
    assert missing.status_code == 404
    relative = api.post("/api/workspace/select", json={"path": "relative/dir"})
    assert relative.status_code == 400
    created = api.post("/api/workspace/select", json={"path": str(other), "create": True})
    assert created.status_code == 200
    body = created.json()
    assert Path(body["root"]) == other.resolve() and body["recent"][:2] == [
        str(other.resolve()),
        str(original),
    ]
    assert (other / ".astro-canvas" / "app.db").is_file()
    assert api.get("/api/workflows/wf").status_code == 404  # the other workspace is empty
    assert api.get("/api/system").json()["workspace"] == str(other.resolve())

    file_path = other / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    not_dir = api.post("/api/workspace/select", json={"path": str(file_path)})
    assert not_dir.status_code == 400

    back = api.post("/api/workspace/select", json={"path": str(original)})
    assert back.status_code == 200 and api.get("/api/workflows/wf").status_code == 200


async def test_watcher_publishes_broadcast_changes(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (root / ".astro-canvas").mkdir(parents=True)
    bus = EventBus()
    bus.bind()
    sub = bus.subscribe("some-workflow")
    watcher = WorkspaceWatcher(bus, root, debounce_ms=50)
    watcher.start()
    assert watcher.running
    await asyncio.sleep(0.3)  # let the OS watch attach
    (root / ".astro-canvas" / "ignored.db").write_text("x", encoding="utf-8")
    (root / "new.fits").write_bytes(b"SIMPLE")
    event: Any = None
    for _ in range(50):
        event = await sub.next(timeout=0.2)
        if event is not None:
            break
    assert isinstance(event, WorkspaceChanged), "no workspace.changed event within 10 s"
    assert "new.fits" in event.paths and not any(".astro-canvas" in p for p in event.paths)
    await watcher.stop()
    assert not watcher.running
    watcher.start()  # restartable
    await watcher.stop()
    sub.close()
