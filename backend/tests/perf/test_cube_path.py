"""The IFU cube path on a KCWI-sized cube: cache it, map it back, collapse it, preview it.

Design 1.6 wants a cube's white-light image inside two seconds. The cube here is 97 MB of flux
(plus the same again of variance), which is a real KCWI shape rather than the 900 KB synthetic one
the samples ship; the recorded MB/s is what makes an extrapolation to the 500 MB cube of
`docs/dev/cube-memory.md` honest rather than a guess.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from astro_canvas_core.types import SUMMARY_BYTES, Cube3D

from astro_canvas.engine.cache import BlobStore
from astro_canvas.sdk import is_memmapped
from astro_canvas.sdk.memmap import MMAP_MIN_BYTES_ENV
from tests.perf.conftest import Perf

pytestmark = pytest.mark.perf

NZ, NY, NX = 3800, 80, 80
"""97 MB of float32 flux: a KCWI pointing, not the 900 KB sample cube."""

MB = 1024 * 1024


@pytest.fixture(scope="module")
def cube() -> Cube3D:
    rng = np.random.default_rng(4)
    flux = rng.normal(size=(NZ, NY, NX)).astype(np.float32)
    flux[NZ // 3, NY // 2, NX // 2] = np.nan
    return Cube3D(
        flux=flux,
        var=np.ones((NZ, NY, NX), dtype=np.float32),
        wave=np.linspace(3500.0, 5600.0, NZ),
        header={"OBJECT": "perf"},
    )


@pytest.fixture(scope="module")
def mapped(
    cube: Cube3D, perf: Perf, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Cube3D, Path]:
    """The cube as the engine sees it after a cache hit: read back memory-mapped."""
    blobs = BlobStore(tmp_path_factory.mktemp("cube-blobs"))
    with perf.timed("Cube3D.to_blob + pack (97 MB flux + 97 MB var)", gate=6000.0) as write:
        data = cube.to_blob().pack()
    perf.record(
        "cache write rate",
        (cube.flux.nbytes + cube.var.nbytes) / MB / (write.elapsed / 1000),
        "MB/s",
    )
    path = blobs.path(blobs.put(data))
    with perf.timed("Cube3D.from_blob_file (memory-mapped)", gate=500.0) as t:
        restored = Cube3D.from_blob_file(path)
    assert t.elapsed < 500.0
    assert is_memmapped(restored.flux), "the gate below only means anything on a mapped cube"
    return restored, path


def test_white_light_of_the_whole_cube(perf: Perf, mapped: tuple[Cube3D, Path]) -> None:
    """The node's own collapse: every channel, straight off the mapped array."""
    restored, _ = mapped
    with perf.timed("white light over 3800 channels (full read)", gate=2000.0) as t:
        image = restored.white_light()
    assert image.shape == (NY, NX)
    assert t.elapsed < 2000.0
    perf.record("white light read rate", restored.flux.nbytes / MB / (t.elapsed / 1000), "MB/s")


def test_bounded_preview_is_independent_of_the_cube(
    perf: Perf, mapped: tuple[Cube3D, Path]
) -> None:
    """A thumbnail reads `SUMMARY_BYTES`, not the cube: this is the number that must not grow."""
    restored, _ = mapped
    restored.summary()  # first touch faults in the pages the stride visits
    with perf.timed("Cube3D.summary (white light + integrated, capped)", gate=400.0) as t:
        summary = restored.summary()
    assert t.elapsed < 400.0
    assert "tile" in summary
    perf.record("summary budget", SUMMARY_BYTES / MB, "MB")

    with perf.timed("white light capped to the summary budget", gate=300.0) as t:
        restored.white_light(max_bytes=SUMMARY_BYTES)
    assert t.elapsed < 300.0

    with perf.timed("integrated spectrum capped to the summary budget", gate=300.0) as t:
        channels, values = restored.integrated(max_bytes=SUMMARY_BYTES)
    assert channels.size == values.size
    assert t.elapsed < 300.0


def test_mapping_threshold_is_what_keeps_it_off_the_heap(
    perf: Perf, cube: Cube3D, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With mapping disabled the same cache hit copies both arrays into the heap."""
    monkeypatch.setenv(MMAP_MIN_BYTES_ENV, "0")
    blobs = BlobStore(tmp_path / "unmapped")
    path = blobs.path(blobs.put(cube.to_blob().pack()))
    with perf.timed("Cube3D.from_blob_file with mapping disabled", gate=20_000.0) as t:
        copied = Cube3D.from_blob_file(path)
    assert not is_memmapped(copied.flux)
    perf.record("copying read rate", copied.flux.nbytes * 2 / MB / (t.elapsed / 1000), "MB/s")
