"""``FileIndex`` (cached blake3), ``list_dir`` and ``RecentWorkspaces``."""

from __future__ import annotations

import os
import time
from pathlib import Path

from blake3 import blake3

from astro_canvas.store.db import current_revision
from astro_canvas.store.files import guess_mime, hash_path, list_dir
from astro_canvas.store.recent import RecentWorkspaces
from astro_canvas.store.workspace import Workspace


def test_migration_adds_files_table(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "ws")
    assert current_revision(ws.engine) == "0002"
    assert ws.samples_dir.is_dir() and ws.downloads_dir.is_dir() and ws.uploads_dir.is_dir()
    assert ws.relative(ws.samples_dir / "x.fits") == "samples/x.fits"
    ws.close()


def test_file_index_caches_by_mtime_and_size(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ws = Workspace(tmp_path / "ws")
    target = ws.root / "data"
    target.write_bytes(b"hello" * 1000)
    info = ws.files.info(ws.root, target)
    assert info.path == "data" and info.size == 5000 and info.mime is None
    assert info.blake3 == blake3(b"hello" * 1000).hexdigest() == hash_path(target)

    calls = {"n": 0}
    real = hash_path

    def counting(path: Path) -> str:
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr("astro_canvas.store.files.hash_path", counting)
    again = ws.files.info(ws.root, target)
    assert again.blake3 == info.blake3 and calls["n"] == 0  # served from the table

    target.write_bytes(b"world" * 1000)
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    changed = ws.files.info(ws.root, target)
    assert changed.blake3 != info.blake3 and calls["n"] == 1

    cheap = ws.files.info(ws.root, target, hash=False)
    assert cheap.blake3 is None and cheap.size == 5000
    ws.files.forget("data")
    assert ws.files.cached_hash("data", stat.st_mtime_ns, 5000) is None
    ws.close()


def test_list_dir_sorts_folders_first_and_skips_hidden(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (root / "b_dir" / "inner").mkdir(parents=True)
    (root / "a_dir").mkdir()
    (root / ".astro-canvas").mkdir()
    (root / "zeta.fits").write_bytes(b"x")
    (root / "Alpha.ecsv").write_text("# %ECSV\n", encoding="utf-8")
    (root / "b_dir" / "inner" / "deep.dat").write_text("1 2\n", encoding="utf-8")

    entries = list_dir(root, root)
    assert [e.name for e in entries] == ["a_dir", "b_dir", "Alpha.ecsv", "zeta.fits"]
    assert entries[1].children is None  # lazy at depth 1
    assert entries[2].mime == "text/x-ecsv" and entries[3].mime == "application/fits"

    deep = list_dir(root, root, depth=3)
    b_dir = deep[1]
    assert b_dir.children is not None and b_dir.children[0].name == "inner"
    inner = b_dir.children[0]
    assert inner.children is not None and inner.children[0].path == "b_dir/inner/deep.dat"

    hidden = list_dir(root, root, hidden=True)
    assert hidden[0].name == ".astro-canvas"
    assert list_dir(root, root / "missing") == []
    assert guess_mime("x.fit") == "application/fits" and guess_mime("x.h5") == "application/x-hdf5"


def test_recent_workspaces_round_trip(tmp_path: Path) -> None:
    recent = RecentWorkspaces(tmp_path / "config", limit=3)
    assert recent.list() == []
    a, b, c, d = (tmp_path / name for name in "abcd")
    recent.touch(a)
    recent.touch(b)
    assert recent.list() == [str(b.resolve()), str(a.resolve())]
    recent.touch(a)
    assert recent.list()[0] == str(a.resolve())
    recent.touch(c)
    recent.touch(d)
    assert len(recent.list()) == 3 and str(b.resolve()) not in recent.list()
    recent.remove(d)
    assert recent.list()[0] == str(c.resolve())
    recent.path.write_text("not json", encoding="utf-8")
    assert recent.list() == []
    recent.path.write_text('{"a": 1}', encoding="utf-8")
    assert recent.list() == []
    time.sleep(0)  # keep the mtime distinct on coarse filesystems
