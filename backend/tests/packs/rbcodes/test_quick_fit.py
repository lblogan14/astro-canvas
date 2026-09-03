"""``rbcodes.multispec.quick_fit`` and the vendored ``LineFitter``: synthetic recovery and parity.

The kernel is a port of ``rbcodes.GUIs.multispecviewer.LineFitter``, which is Qt-free, so where
rbcodes is installed the node calls it directly; the parity test asserts both give the same
numbers on the same input.
"""

from __future__ import annotations

import numpy as np
import pytest
from astro_canvas_core.types import Spectrum1D
from astro_canvas_rbcodes.kernels import line_fit as F
from astro_canvas_rbcodes.nodes import multispec as MS

from tests.packs.rbcodes.conftest import requires_rbcodes

CENTER = 6600.0
SIGMA = 2.0
AMPLITUDE = 30.0
SLOPE = 0.05
BASE = 10.0


def synthetic(direction: int = 1, sigma: float = SIGMA) -> tuple[np.ndarray, np.ndarray]:
    """A tilted continuum with one Gaussian feature at ``CENTER``."""
    wave = np.arange(6500.0, 6700.0, 0.5)
    continuum = BASE + SLOPE * (wave - wave[0])
    line = AMPLITUDE * np.exp(-0.5 * ((wave - CENTER) / sigma) ** 2)
    return wave, continuum + direction * line


def anchors(wave: np.ndarray, flux: np.ndarray, x1: float, x2: float) -> tuple[float, float]:
    """Continuum level at the two window edges (what a user clicks)."""
    return (
        float(flux[int(np.argmin(np.abs(wave - x1)))]),
        float(flux[int(np.argmin(np.abs(wave - x2)))]),
    )


def spectrum(wave: np.ndarray, flux: np.ndarray) -> Spectrum1D:
    return Spectrum1D(wave=wave, flux=flux, meta={"source": "synthetic"})


# --- the kernel -----------------------------------------------------------------------------------


def test_gaussian_recovers_an_emission_line() -> None:
    wave, flux = synthetic()
    y1, y2 = anchors(wave, flux, 6580.0, 6620.0)
    fit = F.fit_gaussian(wave, flux, 6580.0, y1, 6620.0, y2)

    assert fit.kind == "gaussian" and fit.direction == 1
    assert fit.centroid == pytest.approx(CENTER, abs=1e-3)
    assert fit.sigma_ang == pytest.approx(SIGMA, rel=1e-3)
    assert fit.fwhm_ang == pytest.approx(F.FWHM_PER_SIGMA * SIGMA, rel=1e-3)
    assert fit.fwhm_kms == pytest.approx(fit.fwhm_ang / CENTER * F.C_KMS, rel=1e-6)
    assert fit.amplitude == pytest.approx(AMPLITUDE, rel=1e-3)
    assert fit.asymmetric is False
    assert fit.n_pixels == 81
    assert fit.fit_wave.shape == (300,) and fit.fit_flux.shape == (300,)
    # The model curve sits on the tilted continuum at the window edges.
    assert fit.fit_flux[0] == pytest.approx(y1, abs=0.2)
    assert fit.fit_flux[-1] == pytest.approx(y2, abs=0.2)


def test_gaussian_recovers_an_absorption_line() -> None:
    wave, flux = synthetic(direction=-1)
    y1, y2 = anchors(wave, flux, 6580.0, 6620.0)
    fit = F.fit_gaussian(wave, flux, 6580.0, y1, 6620.0, y2)
    assert fit.direction == -1
    assert fit.amplitude == pytest.approx(-AMPLITUDE, rel=1e-3)
    assert fit.centroid == pytest.approx(CENTER, abs=1e-3)


def test_com_matches_the_gaussian_centroid() -> None:
    wave, flux = synthetic()
    y1, y2 = anchors(wave, flux, 6580.0, 6620.0)
    fit = F.fit_com(wave, flux, 6580.0, y1, 6620.0, y2)
    assert fit.kind == "com" and fit.direction == 1
    assert fit.centroid == pytest.approx(CENTER, abs=1e-2)
    # Clipping the negative wing at zero widens the centre of mass beyond the true sigma.
    assert fit.sigma_ang > SIGMA
    assert fit.fwhm_ang == pytest.approx(F.FWHM_PER_SIGMA * fit.sigma_ang, rel=1e-9)
    assert fit.fit_wave.size == 0


def test_anchors_may_be_given_right_to_left() -> None:
    wave, flux = synthetic()
    y1, y2 = anchors(wave, flux, 6580.0, 6620.0)
    forward = F.fit_gaussian(wave, flux, 6580.0, y1, 6620.0, y2)
    backward = F.fit_gaussian(wave, flux, 6620.0, y2, 6580.0, y1)
    assert backward.centroid == pytest.approx(forward.centroid, abs=1e-9)
    assert backward.window == forward.window


def test_a_truncated_profile_is_flagged_asymmetric() -> None:
    wave, flux = synthetic()
    y1, y2 = anchors(wave, flux, 6596.0, 6620.0)
    fit = F.fit_gaussian(wave, flux, 6596.0, y1, 6620.0, y2)
    assert fit.asymmetric is True


def test_too_few_pixels_is_an_error() -> None:
    wave, flux = synthetic()
    with pytest.raises(ValueError, match="need >= 5"):
        F.fit_gaussian(wave, flux, 6600.0, 10.0, 6601.0, 10.0)
    with pytest.raises(ValueError, match="need >= 3"):
        F.fit_com(wave, flux, 6600.0, 10.0, 6600.6, 10.0)


def test_com_without_signal_is_an_error() -> None:
    wave = np.arange(6500.0, 6600.0, 0.5)
    flux = np.zeros_like(wave)
    with pytest.raises(ValueError, match="Sum of weights is zero"):
        F.fit_com(wave, flux, 6520.0, 0.0, 6560.0, 0.0)


def test_linear_continuum_is_the_line_through_the_anchors() -> None:
    wave = np.array([10.0, 20.0, 30.0])
    assert F.linear_continuum(wave, 10.0, 1.0, 30.0, 3.0).tolist() == [1.0, 2.0, 3.0]


# --- the node -------------------------------------------------------------------------------------


def test_quick_fit_node_returns_one_row() -> None:
    wave, flux = synthetic()
    y1, y2 = anchors(wave, flux, 6580.0, 6620.0)
    table = MS.quick_fit(spectrum(wave, flux), x1=6580.0, y1=y1, x2=6620.0, y2=y2)

    assert table.n_rows == 1
    assert set(table.columns) == {
        "kind",
        "centroid",
        "fwhm_ang",
        "fwhm_kms",
        "sigma_ang",
        "amplitude",
        "direction",
        "asymmetric",
        "n_pixels",
    }
    assert table.columns["centroid"][0] == pytest.approx(CENTER, abs=1e-3)
    assert table.units["centroid"] == "Angstrom" and table.units["fwhm_kms"] == "km / s"
    assert table.meta["window"] == [6580.0, 6620.0]
    assert table.meta["continuum"] == [y1, y2]
    assert table.meta["source"] == "rbcodes.multispec.quick_fit"


def test_quick_fit_node_supports_centre_of_mass() -> None:
    wave, flux = synthetic()
    y1, y2 = anchors(wave, flux, 6580.0, 6620.0)
    table = MS.quick_fit(spectrum(wave, flux), x1=6580.0, y1=y1, x2=6620.0, y2=y2, kind="com")
    assert table.columns["kind"][0] == "com"
    assert table.columns["centroid"][0] == pytest.approx(CENTER, abs=1e-2)


def test_quick_fit_refuses_degenerate_and_velocity_input() -> None:
    wave, flux = synthetic()
    with pytest.raises(ValueError, match="different wavelengths"):
        MS.quick_fit(spectrum(wave, flux), x1=6600.0, y1=1.0, x2=6600.0, y2=1.0)
    velocity = Spectrum1D(
        wave=np.linspace(-500.0, 500.0, 64),
        flux=np.ones(64),
        frame="velocity",
        v0_wrest=CENTER,
    )
    with pytest.raises(ValueError, match="not a velocity slice"):
        MS.quick_fit(velocity, x1=-100.0, y1=1.0, x2=100.0, y2=1.0)


def test_quick_fit_on_the_sdss_galaxy_finds_h_alpha(samples_galaxy: Spectrum1D) -> None:
    """H-alpha at z = 0.00586 sits at 6601.4 A in the SDSS star-forming galaxy."""
    table = MS.quick_fit(samples_galaxy, x1=6590.0, y1=20.0, x2=6615.0, y2=20.0)
    assert table.columns["direction"][0] == 1
    assert table.columns["centroid"][0] == pytest.approx(6601.4, abs=2.0)
    assert table.columns["fwhm_ang"][0] > 0.5


# --- parity with rbcodes --------------------------------------------------------------------------


@requires_rbcodes
@pytest.mark.parametrize("kind", ["gaussian", "com"])
@pytest.mark.parametrize("direction", [1, -1])
def test_kernel_matches_rbcodes_line_fitter(kind: str, direction: int) -> None:
    from rbcodes.GUIs.multispecviewer import LineFitter  # noqa: PLC0415

    wave, flux = synthetic(direction=direction)
    y1, y2 = anchors(wave, flux, 6580.0, 6620.0)
    mine = (F.fit_gaussian if kind == "gaussian" else F.fit_com)(wave, flux, 6580.0, y1, 6620.0, y2)
    theirs = (LineFitter.fit_gaussian if kind == "gaussian" else LineFitter.fit_com)(
        wave, flux, 6580.0, y1, 6620.0, y2
    )

    assert mine.centroid == pytest.approx(theirs["centroid"], rel=1e-9)
    assert mine.amplitude == pytest.approx(theirs["amplitude"], rel=1e-9)
    assert mine.direction == theirs["direction"]
    assert mine.asymmetric == theirs["asymmetric"]
    expected_fwhm = theirs.get("fwhm_ang", theirs.get("fwhm_equiv_ang"))
    assert mine.fwhm_ang == pytest.approx(expected_fwhm, rel=1e-9)
    assert mine.fwhm_kms == pytest.approx(theirs["fwhm_kms"], rel=1e-9)


@requires_rbcodes
def test_the_node_dispatches_to_rbcodes() -> None:
    """With rbcodes installed the node runs upstream's fitter and reports the same numbers."""
    wave, flux = synthetic()
    y1, y2 = anchors(wave, flux, 6580.0, 6620.0)
    table = MS.quick_fit(spectrum(wave, flux), x1=6580.0, y1=y1, x2=6620.0, y2=y2)
    kernel = F.fit_gaussian(wave, flux, 6580.0, y1, 6620.0, y2)
    assert table.meta["rbcodes"]["backend"] == "rbcodes"
    assert table.columns["centroid"][0] == pytest.approx(kernel.centroid, rel=1e-9)
    assert table.columns["n_pixels"][0] == kernel.n_pixels
    assert table.columns["sigma_ang"][0] == pytest.approx(kernel.sigma_ang, rel=1e-9)
