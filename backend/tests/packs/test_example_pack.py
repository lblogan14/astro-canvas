"""The pack authoring tutorial's code, tested.

`docs/packs/tutorial.md` builds `docs/examples/snr-pack` step by step. A tutorial whose code is
only transcribed goes stale within a phase, so the example is a real package in the repository
and these are the assertions its own `tests/test_snr_node.py` makes.

The rbcodes call itself only runs where rbcodes imports (it pins `python<3.11` upstream); the
schema half — which is what a pack author gets wrong — runs everywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from astro_canvas_core.types import Spectrum1D

from astro_canvas.sdk import NodeRegistry, NullContext

EXAMPLE = Path(__file__).resolve().parents[3] / "docs" / "examples" / "snr-pack" / "src"


@pytest.fixture(scope="module", autouse=True)
def example_on_path() -> None:
    """The example is not installed (it is not a workspace member): import it from the tree."""
    if str(EXAMPLE) not in sys.path:
        sys.path.insert(0, str(EXAMPLE))


@pytest.fixture(scope="module")
def spec() -> NodeRegistry:
    import astro_canvas_snr

    registry = NodeRegistry()
    astro_canvas_snr.register(registry)
    return registry


def spectrum(n: int = 600) -> Spectrum1D:
    rng = np.random.default_rng(7)
    wave = np.linspace(4000.0, 5000.0, n)
    flux = 10.0 + rng.normal(scale=0.5, size=n)
    return Spectrum1D(wave=wave, flux=flux, error=np.full(n, 0.5))


def test_the_tutorials_pack_registers_and_describes_itself(spec: NodeRegistry) -> None:
    node = spec.spec("snr.spectrum.estimate")
    assert node.name == "Estimate SNR"
    assert node.category == "Spectra/Measure"
    assert node.cost == "cheap"
    assert node.preview == "spectrum-thumb"
    assert [port.name for port in node.inputs] == ["spec"]
    assert [port.type for port in node.inputs] == ["astro.Spectrum1D"]
    assert [port.name for port in node.outputs] == ["snr", "median"]
    assert [port.type for port in node.outputs] == ["astro.Spectrum1D", "astro.Float"]
    assert [param.name for param in node.params] == [
        "binsize",
        "wave_min",
        "wave_max",
        "robust",
        "sigma",
    ]
    assert node.description.startswith("Signal-to-noise per pixel")


def test_the_docstring_is_the_parameter_help(spec: NodeRegistry) -> None:
    params = {param.name: param for param in spec.spec("snr.spectrum.estimate").params}
    assert params["binsize"].default == 3
    assert params["binsize"].description == (
        "Pixels combined before the ratio is taken (1 leaves the grid alone)."
    )
    assert params["wave_min"].widget == "wavelength"
    assert params["robust"].description == (
        "Reduce with a sigma-clipped median rather than a plain one."
    )


def test_a_spectrum_without_errors_says_so() -> None:
    from astro_canvas_snr.nodes import estimate_snr

    bare = Spectrum1D(wave=np.linspace(1.0, 2.0, 10), flux=np.ones(10))
    with pytest.raises(ValueError, match="error array"):
        estimate_snr(bare, ctx=NullContext())


def test_the_numbers_are_rbcodes_own() -> None:
    pytest.importorskip("rbcodes", reason="rbcodes pins python<3.11 upstream")
    from astro_canvas_snr.nodes import estimate_snr
    from rbcodes.utils.compute_SNR_1d import estimate_snr as reference

    sample = spectrum()
    curve, median = estimate_snr(sample, binsize=3, ctx=NullContext())
    expected = reference(
        sample.wave,
        sample.flux,
        sample.error,
        binsize=3,
        snr_range=[-1, -1],
        verbose=False,
        plot=False,
    )
    assert np.allclose(curve.flux, expected["snr"], rtol=1e-12)
    assert median == pytest.approx(float(expected["median_snr"]), rel=1e-12)
    assert curve.flux_unit == "SNR / pixel"


def test_a_range_narrows_the_measurement() -> None:
    pytest.importorskip("rbcodes", reason="rbcodes pins python<3.11 upstream")
    from astro_canvas_snr.nodes import estimate_snr

    sample = spectrum()
    whole, _ = estimate_snr(sample, binsize=1, ctx=NullContext())
    part, _ = estimate_snr(sample, binsize=1, wave_min=4400.0, wave_max=4600.0, ctx=NullContext())
    assert len(part) < len(whole)
    assert float(part.wave.min()) >= 4400.0
    assert float(part.wave.max()) <= 4600.0
