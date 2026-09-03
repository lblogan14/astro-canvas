"""Cubes stay on disk: mappable blob parts, memory-mapped reads, bounded summaries.

The rule from phase 08: a cube read back out of the cache must not be copied into the server's
heap, must not be charged to the memory LRU, and previewing it must touch only a bounded slice of
the array however large it is.
"""

from __future__ import annotations

import gc
import tracemalloc
from pathlib import Path

import numpy as np
import pytest
from astro_canvas_core.types import SUMMARY_BYTES, Cube3D, Spectrum1D

from astro_canvas.engine.cache import MMAP_HANDLE_BYTES, BlobStore, OutputRef, value_nbytes
from astro_canvas.sdk import is_memmapped
from astro_canvas.sdk.memmap import MMAP_MIN_BYTES_ENV, memmap_part, stored_part_offset

NZ, NY, NX = 400, 40, 40
"""2.56 MB of float32 - big enough to see the difference, small enough for a fast test."""


@pytest.fixture
def small_mmap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Map anything above 64 KiB so the fixtures do not have to be huge."""
    monkeypatch.setenv(MMAP_MIN_BYTES_ENV, str(64 * 1024))


def make_cube(nz: int = NZ, ny: int = NY, nx: int = NX) -> Cube3D:
    rng = np.random.default_rng(8)
    flux = rng.normal(size=(nz, ny, nx)).astype(np.float32)
    flux[nz // 2, ny // 2, nx // 2] = np.nan
    return Cube3D(
        flux=flux,
        var=np.ones((nz, ny, nx), dtype=np.float32),
        wave=np.linspace(4000.0, 5000.0, nz),
        header={"OBJECT": "synthetic"},
    )


def store(cube: Cube3D, root: Path) -> Path:
    blobs = BlobStore(root)
    return blobs.path(blobs.put(cube.to_blob().pack()))


def test_flux_and_var_get_their_own_mappable_parts(small_mmap: None, tmp_path: Path) -> None:
    blob = make_cube().to_blob()
    assert set(blob.parts) >= {"flux.npy", "var.npy"}
    assert blob.manifest["mmap"] == {"flux": "flux.npy", "var": "var.npy"}
    path = tmp_path / "blob.zip"
    path.write_bytes(blob.pack())
    # Uncompressed members: the raw array bytes are addressable inside the packed blob.
    assert stored_part_offset(path, "flux.npy") is not None
    assert memmap_part(path, "flux.npy") is not None


def test_from_blob_file_maps_without_copying(small_mmap: None, tmp_path: Path) -> None:
    cube = make_cube()
    back = Cube3D.from_blob_file(store(cube, tmp_path / "blobs"))
    assert is_memmapped(back.flux) and back.var is not None and is_memmapped(back.var)
    assert np.array_equal(back.flux, cube.flux, equal_nan=True)
    assert np.array_equal(back.wave, cube.wave)
    # The LRU must not think a mapped cube occupies its byte budget.
    assert value_nbytes(back) < 8 * MMAP_HANDLE_BYTES
    assert value_nbytes(cube) > cube.flux.nbytes


def test_from_blob_still_copies(small_mmap: None) -> None:
    """The in-memory path (process pool results, tests) round-trips the same values."""
    cube = make_cube(60, 8, 8)
    back = Cube3D.from_blob(cube.to_blob())
    assert not is_memmapped(back.flux)
    assert np.array_equal(back.flux, cube.flux, equal_nan=True)


def test_below_the_threshold_nothing_is_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MMAP_MIN_BYTES_ENV, str(1024 * 1024 * 1024))
    blob = make_cube(20, 8, 8).to_blob()
    assert "mmap" not in blob.manifest
    assert set(blob.parts) == {"arrays.npz"}


def test_other_types_are_unaffected(tmp_path: Path) -> None:
    """A type without ``__mmap_fields__`` loads through ``from_blob`` as before."""
    spec = Spectrum1D(wave=np.linspace(1, 10, 32), flux=np.ones(32))
    path = tmp_path / "spec.zip"
    path.write_bytes(spec.to_blob().pack())
    back = Spectrum1D.from_blob_file(path)
    assert np.array_equal(back.flux, spec.flux)


def test_cache_load_maps_the_cube(small_mmap: None, tmp_path: Path) -> None:
    """``OutputCache.load`` is the path the scheduler and the workers take."""
    from astro_canvas.engine.cache import MemoryLRU, OutputCache
    from astro_canvas.sdk import TypeRegistry

    types = TypeRegistry()
    types.add(Cube3D)
    blobs = BlobStore(tmp_path / "blobs")
    cache = OutputCache(memory=MemoryLRU(64 * 1024 * 1024), blobs=blobs, index=None, types=types)
    cube = make_cube()
    blob_hash = blobs.put(cube.to_blob().pack())
    loaded = cache.load(OutputRef("k", "out", Cube3D.type_id(), blob_hash, 0))
    assert isinstance(loaded, Cube3D) and is_memmapped(loaded.flux)


def test_summary_reads_only_a_bounded_slice(small_mmap: None, tmp_path: Path) -> None:
    """Summarising a cube far larger than ``SUMMARY_BYTES`` must not copy it into the heap.

    ``tracemalloc`` sees numpy's own allocations (``np.lib.tracemalloc_domain``) but not the pages
    a memory map faults in, which is exactly the quantity the rule is about: what the preview
    *copies*, not what the kernel caches.
    """
    nz = (4 * SUMMARY_BYTES) // (NY * NX * 4) + 1
    cube = make_cube(nz)
    path = store(cube, tmp_path / "blobs")
    del cube
    gc.collect()
    mapped = Cube3D.from_blob_file(path)
    assert mapped.flux.nbytes > 4 * SUMMARY_BYTES
    tracemalloc.start()
    try:
        summary = mapped.summary()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert summary["shape"] == [nz, NY, NX]
    assert len(summary["spectrum"]["wave"]) <= 512
    # float64 working copies of a 32 MB float32 budget, plus the tile: comfortably under 4x.
    assert peak < 4 * SUMMARY_BYTES, f"summary allocated {peak / 1e6:.0f} MB"


def test_summary_is_json_safe(small_mmap: None) -> None:
    """NaNs must travel as ``null``: ``json.dumps`` emits bare ``NaN``, which browsers reject."""
    import json

    summary = make_cube(40, 8, 8).summary()
    assert None in summary["spectrum"]["flux"] or all(
        v is None or isinstance(v, float) for v in summary["spectrum"]["flux"]
    )
    assert "NaN" not in json.dumps(summary)
