"""BlobStore, OutputIndex, MemoryLRU, OutputCache GC, Workspace paths and migrations."""

from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
from astro_canvas_core import types as T

from astro_canvas.engine.cache import (
    BlobStore,
    MemoryLRU,
    OutputCache,
    OutputIndex,
    OutputRef,
    digest,
    value_nbytes,
)
from astro_canvas.sdk import NodeRegistry
from astro_canvas.store.db import current_revision
from astro_canvas.store.models import Output
from astro_canvas.store.workspace import PathOutsideWorkspaceError, Workspace, safe_path


def test_blobstore_put_get_is_content_addressed(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    key = store.put(b"hello")
    assert key == digest(b"hello") and store.has(key)
    assert store.put(b"hello") == key
    assert store.get(key) == b"hello"
    assert store.path(key).parent.name == key[:2]
    assert not list(store.root.rglob(".tmp-*"))
    assert store.size() == 5
    with pytest.raises(KeyError):
        store.get("0" * 64)
    with pytest.raises(ValueError):
        store.path("../evil")
    assert store.delete(key) and not store.delete(key)


def test_blobstore_gc_by_age_then_size_keeps_protected(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    keys = [store.put(bytes([i]) * 100) for i in range(5)]
    now = time.time()
    for i, key in enumerate(keys):  # oldest first
        os.utime(store.path(key), (now - 1000 + i, now - 1000 + i))
    removed = store.gc(max_age=timedelta(seconds=999), now=now, keep={keys[0]})
    assert removed == [keys[1]] or set(removed) <= set(keys[1:])  # keys[0] protected by ``keep``
    assert store.has(keys[0])
    removed = store.gc(max_bytes=250, now=now, keep={keys[0]})
    assert store.size() <= 250 + 100 and store.has(keys[0])
    assert all(not store.has(k) for k in removed)


def test_memory_lru_evicts_by_bytes() -> None:
    lru = MemoryLRU(max_bytes=300)
    small = {"out": T.Float(value=1.0)}
    lru.put("a", small, nbytes=100)
    lru.put("b", small, nbytes=100)
    lru.put("c", small, nbytes=100)
    assert lru.get("a") is not None  # touch a -> b is now the oldest
    lru.put("d", small, nbytes=100)
    assert "b" not in lru and "a" in lru and lru.nbytes == 300
    lru.put("huge", small, nbytes=10_000)  # larger than the cache: dropped immediately
    assert "huge" not in lru
    lru.pop("a")
    assert "a" not in lru and len(lru) == 2
    lru.clear()
    assert lru.nbytes == 0 and lru.get("c") is None
    spec = T.Spectrum1D(wave=np.zeros(1000), flux=np.zeros(1000))
    assert value_nbytes(spec) >= 16_000


def test_output_index_and_cache_round_trip(tmp_path: Path, registry: NodeRegistry) -> None:
    ws = Workspace(tmp_path / "ws")
    index = OutputIndex(ws.sessions)
    cache = OutputCache(
        memory=MemoryLRU(1 << 20), blobs=ws.blobs, index=index, types=registry.types
    )
    spec = T.Spectrum1D(wave=np.linspace(1, 2, 10), flux=np.ones(10))
    refs = cache.store("k1", "test.spec.make", {"out": spec, "n": T.Int(value=10)})
    assert set(refs) == {"out", "n"} and refs["out"].type_id == "astro.Spectrum1D"
    cache.memory.clear()
    loaded = cache.lookup("k1")
    assert loaded is not None and np.array_equal(loaded["out"].wave, spec.wave)  # type: ignore[attr-defined]
    assert "k1" in cache.memory  # rehydrated into memory
    assert cache.refs("k1") == refs and cache.lookup("missing") is None
    assert index.total_bytes() == sum(r.nbytes for r in refs.values())
    # astro.Any values stay memory-only.
    cache.store("k2", "test.any.make", {"out": T.Any(value=object())})
    assert cache.refs("k2") is None and cache.is_memory_only("k2")
    cache.memory.clear()
    assert cache.lookup("k2") is None
    # A blob deleted behind the index's back is treated as a miss and forgotten.
    ws.blobs.delete(refs["out"].blob_hash)
    assert cache.lookup("k1") is None and index.get("k1") is None
    ws.close()


def test_output_cache_gc_keeps_store_under_size(tmp_path: Path, registry: NodeRegistry) -> None:
    ws = Workspace(tmp_path / "ws")
    index = OutputIndex(ws.sessions)
    cache = OutputCache(
        memory=MemoryLRU(1 << 20),
        blobs=ws.blobs,
        index=index,
        types=registry.types,
        max_disk_bytes=30_000,
    )
    for i in range(10):
        spec = T.Spectrum1D(wave=np.linspace(1, 2, 500) + i, flux=np.ones(500))
        cache.store(f"k{i}", "t", {"out": spec})
        time.sleep(0.002)
    before = ws.blobs.size()
    assert before > 30_000
    removed = cache.gc()
    assert removed and ws.blobs.size() <= 30_000
    assert index.total_bytes() <= 30_000
    assert cache.refs("k0") is None and cache.refs("k9") is not None  # LRU: oldest evicted
    # Age-based eviction.
    cache.max_age = timedelta(seconds=0)
    time.sleep(0.01)
    cache.gc()
    assert index.total_bytes() == 0 and ws.blobs.size() == 0
    with ws.session() as session:
        assert session.query(Output).count() == 0
    ws.close()


def test_output_index_evict_and_manual_refs(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "ws")
    index = OutputIndex(ws.sessions)
    index.put([OutputRef("k", "out", "astro.Float", "ab" * 32, 10, "t")], {"out": {"type": "x"}})
    got = index.get("k", touch=False)
    assert got is not None and got["out"].nbytes == 10
    assert index.referenced_hashes() == {"ab" * 32}
    assert index.evict(max_bytes=None, max_age=None) == []
    index.forget("k")
    assert index.get("k") is None
    ws.close()


def test_workspace_layout_migrations_and_safe_paths(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "ws")
    assert ws.state_dir.name == ".astro-canvas"
    assert ws.blobs_dir.is_dir() and ws.scratch_dir.is_dir() and ws.db_path.is_file()
    assert current_revision(ws.engine) == "0002"
    again = Workspace(ws.root)  # idempotent re-open
    assert current_revision(again.engine) == "0002"
    scratch = ws.new_scratch()
    assert scratch.parent == ws.scratch_dir
    assert ws.clear_scratch() == 1 and not scratch.exists()
    (ws.root / "data").mkdir()
    assert ws.safe_path("data/spec.fits") == (ws.root / "data" / "spec.fits").resolve()
    assert safe_path(ws.root, "data\\sub\\x.txt").is_relative_to(ws.root)
    for bad in ("../x", "/abs/path", "C:/win", "a/../../b", "data/../../x"):
        with pytest.raises(PathOutsideWorkspaceError):
            ws.safe_path(bad)
    ws.close()
    again.close()


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_safe_path_rejects_symlinks(tmp_path: Path) -> None:  # pragma: no cover - posix only
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    (root / "link").symlink_to(tmp_path / "outside")
    with pytest.raises(PathOutsideWorkspaceError):
        safe_path(root, "link/file")
