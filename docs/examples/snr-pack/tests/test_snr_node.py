"""The test a pack author writes: the schema is what the UI shows, the numbers are rbcodes'.

This is the file the tutorial ends with. The repository runs the same assertions from
`backend/tests/packs/test_example_pack.py`, so the tutorial's code cannot rot.
"""

from __future__ import annotations

import numpy as np
import pytest
from astro_canvas_core.types import Spectrum1D

from astro_canvas.sdk import NodeRegistry, NullContext

# The whole module needs rbcodes, which pins `python<3.11` upstream; skip rather than fail.
pytest.importorskip("rbcodes", reason="rbcodes pins python<3.11 upstream")

import astro_canvas_snr  # noqa: E402
from astro_canvas_snr.nodes import estimate_snr  # noqa: E402
from rbcodes.utils.compute_SNR_1d import estimate_snr as reference  # noqa: E402


def spectrum(n: int = 600) -> Spectrum1D:
    rng = np.random.default_rng(7)
    wave = np.linspace(4000.0, 5000.0, n)
    flux = 10.0 + rng.normal(scale=0.5, size=n)
    return Spectrum1D(wave=wave, flux=flux, error=np.full(n, 0.5))


def test_the_schema_is_what_the_ui_will_show() -> None:
    """Everything the node library and the parameter form render comes from introspection."""
    registry = NodeRegistry()
    astro_canvas_snr.register(registry)
    spec = registry.spec("snr.spectrum.estimate")

    assert spec.name == "Estimate SNR"
    assert spec.category == "Spectra/Measure"
    assert [port.name for port in spec.inputs] == ["spec"]
    assert [port.type for port in spec.inputs] == ["astro.Spectrum1D"]
    assert [port.name for port in spec.outputs] == ["snr", "median"]
    assert [param.name for param in spec.params] == [
        "binsize",
        "wave_min",
        "wave_max",
        "robust",
        "sigma",
    ]
    # The docstring is the contract: its summary and its Args become the UI's text.
    assert spec.description.startswith("Signal-to-noise per pixel")
    binsize = next(param for param in spec.params if param.name == "binsize")
    assert binsize.description == (
        "Pixels combined before the ratio is taken (1 leaves the grid alone)."
    )
    assert binsize.default == 3


def test_the_numbers_are_rbcodes_own() -> None:
    spec = spectrum()
    curve, median = estimate_snr(spec, binsize=3, ctx=NullContext())
    expected = reference(
        spec.wave, spec.flux, spec.error, binsize=3, snr_range=[-1, -1], verbose=False, plot=False
    )
    assert np.allclose(curve.flux, expected["snr"], rtol=1e-12)
    assert median == pytest.approx(float(expected["median_snr"]), rel=1e-12)
    assert curve.flux_unit == "SNR / pixel"
    # Binning by three leaves a third of the pixels.
    assert len(curve) == pytest.approx(len(spec) / 3, abs=2)


def test_a_range_narrows_the_measurement() -> None:
    spec = spectrum()
    whole, _ = estimate_snr(spec, binsize=1, ctx=NullContext())
    part, _ = estimate_snr(spec, binsize=1, wave_min=4400.0, wave_max=4600.0, ctx=NullContext())
    assert len(part) < len(whole)
    assert float(part.wave.min()) >= 4400.0
    assert float(part.wave.max()) <= 4600.0


def test_a_spectrum_without_errors_says_so() -> None:
    bare = Spectrum1D(wave=np.linspace(1.0, 2.0, 10), flux=np.ones(10))
    with pytest.raises(ValueError, match="error array"):
        estimate_snr(bare, ctx=NullContext())
