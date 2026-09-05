"""The 1e6-point spectrum path: decimation for the preview, blobs, and the full-array frame.

Design 1.6 asks for a million-point spectrum to feel immediate. Nothing on that path may be
linear in the *rendered* points: the preview is a MinMaxLTTB decimation to a fixed budget, the
full array travels as a binary frame rather than JSON, and caching a spectrum is a blob write.
"""

from __future__ import annotations

import numpy as np
import pytest
from astro_canvas_core.types import Spectrum1D

from astro_canvas.engine.cache import BlobStore
from astro_canvas.engine.events import output_frame
from tests.perf.conftest import Perf

pytestmark = pytest.mark.perf

N = 1_000_000


@pytest.fixture(scope="module")
def spectrum() -> Spectrum1D:
    rng = np.random.default_rng(13)
    wave = np.linspace(3000.0, 10000.0, N)
    flux = np.sin(wave / 40.0) + rng.normal(scale=0.05, size=N)
    return Spectrum1D(wave=wave, flux=flux, error=np.full(N, 0.05))


def test_preview_decimation_is_interactive(perf: Perf, spectrum: Spectrum1D) -> None:
    """A node thumbnail asks for 4000 points out of a million."""
    spectrum.summary()  # warm tsdownsample's first call
    with perf.timed("spectrum.summary 1e6 -> 4000 points", gate=120.0) as t:
        summary = spectrum.summary()
    assert len(summary["wave"]) <= 4000
    assert t.elapsed < 120.0

    with perf.timed("spectrum.summary 1e6 -> 20000 points (viewer)", gate=200.0) as t:
        zoomed = spectrum.summary({"n_out": 20000})
    assert len(zoomed["wave"]) <= 20000
    assert t.elapsed < 200.0

    # Zooming in must not cost more than the whole range did.
    with perf.timed("spectrum.summary zoomed to 1% of the range", gate=200.0) as t:
        spectrum.summary({"n_out": 20000, "lo": 5000.0, "hi": 5070.0})
    assert t.elapsed < 200.0


def test_blob_round_trip(
    perf: Perf, spectrum: Spectrum1D, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Caching a spectrum is a blob write; reading it back rehydrates the arrays."""
    blobs = BlobStore(tmp_path_factory.mktemp("blobs"))
    with perf.timed("Spectrum1D.to_blob + pack (1e6 x 3 float64)", gate=400.0) as t:
        data = spectrum.to_blob().pack()
    assert t.elapsed < 400.0
    perf.record("blob size", len(data) / 1e6, "MB")

    blob_hash = blobs.put(data)
    path = blobs.path(blob_hash)
    with perf.timed("Spectrum1D.from_blob_file", gate=400.0) as t:
        restored = Spectrum1D.from_blob_file(path)
    assert t.elapsed < 400.0
    assert len(restored) == N


def test_full_array_frame(perf: Perf, spectrum: Spectrum1D) -> None:
    """`output.request` hands the browser the raw buffers, not 1e6 JSON numbers."""
    with perf.timed("output_frame for a 1e6-point spectrum", gate=300.0) as t:
        frame = output_frame("n", "out", spectrum)
    assert t.elapsed < 300.0
    perf.record("frame size", len(frame) / 1e6, "MB")
    # The frame is the arrays plus a small msgpack header, not a JSON re-encoding of them.
    arrays = [spectrum.wave, spectrum.flux, spectrum.error]
    raw = sum(a.nbytes for a in arrays if a is not None)
    assert len(frame) <= raw + 8192
