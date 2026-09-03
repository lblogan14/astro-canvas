"""``rbcodes.ifu.moment_maps`` / ``snr_map``: the known velocity field, masking, rbcodes parity."""

from __future__ import annotations

import numpy as np
import pytest
from astro_canvas_core.types import Cube3D
from astro_canvas_rbcodes.kernels import ifu as K
from astro_canvas_rbcodes.nodes import ifu

from tests.packs.rbcodes.conftest import requires_rbcodes

LAMBDA_REST = 5007.0
GRADIENT = 8.0
"""km/s per pixel along x, the gradient ``sample_data/make_cube.py`` puts into the disc."""
CENTRE_X, CENTRE_Y = 17.5, 19.5
SIGMA_KMS = 65.0
C_KMS = 2.998e5


def noiseless_disc(nz: int = 160, ny: int = 40, nx: int = 36) -> tuple[Cube3D, np.ndarray]:
    """A cube with an analytic velocity field and no noise, plus that field.

    The same disc as the bundled sample, with the noise and the continuum left out so the moment
    maps can be compared with the input velocities rather than with a noise floor.
    """
    wave = 4900.0 + np.arange(nz, dtype=np.float64)
    y, x = np.mgrid[0:ny, 0:nx]
    amplitude = 120.0 * np.exp(-(((x - CENTRE_X) / 7.0) ** 2 + ((y - CENTRE_Y) / 5.0) ** 2) / 2.0)
    velocity = (x - CENTRE_X) * GRADIENT
    centre = LAMBDA_REST * (1.0 + velocity / C_KMS)
    sigma = SIGMA_KMS / C_KMS * LAMBDA_REST
    flux = amplitude[None] * np.exp(-((wave[:, None, None] - centre[None]) ** 2) / (2.0 * sigma**2))
    cube = Cube3D(
        flux=flux.astype(np.float32),
        var=np.full(flux.shape, 0.01, dtype=np.float32),
        wave=wave,
        header={"BUNIT": "flux"},
    )
    return cube, velocity


def test_moment1_recovers_the_input_velocity_field() -> None:
    """Acceptance: the velocity map matches the known field to better than 1 km/s."""
    cube, velocity = noiseless_disc()
    maps = ifu.moment_maps(cube, 4980.0, 5035.0, LAMBDA_REST, subtract_continuum=False)
    assert maps.m1 is not None
    bright = np.asarray(cube.flux).max(axis=0) > 5.0
    assert bright.sum() > 400
    assert np.nanmax(np.abs(maps.m1[bright] - velocity[bright])) < 1.0


def test_moment2_recovers_the_line_width() -> None:
    cube, _ = noiseless_disc()
    maps = ifu.moment_maps(cube, 4980.0, 5035.0, LAMBDA_REST, subtract_continuum=False)
    assert maps.m2 is not None
    bright = np.asarray(cube.flux).max(axis=0) > 20.0
    assert np.allclose(maps.m2[bright], SIGMA_KMS, rtol=0.05)


def test_moment0_is_the_integrated_line_flux() -> None:
    cube, _ = noiseless_disc()
    maps = ifu.moment_maps(cube, 4980.0, 5035.0, LAMBDA_REST, subtract_continuum=False)
    expected = K.moment0(cube.flux, cube.wave, 4980.0, 5035.0)
    assert np.allclose(maps.m0, expected, rtol=1e-5)
    assert maps.window == (4980.0, 5035.0)
    assert maps.lambda_rest == LAMBDA_REST


def test_maps_carry_the_two_axis_wcs(ifu_cube: Cube3D) -> None:
    maps = ifu.moment_maps(ifu_cube, 4980.0, 5035.0, LAMBDA_REST)
    assert maps.wcs is not None and maps.wcs["naxis"] == 2
    assert maps.unit == ifu_cube.header["BUNIT"]


def test_continuum_subtraction_changes_moment0(ifu_cube: Cube3D) -> None:
    """The sample cube has a flat continuum of 3.0; leaving it in inflates m0 everywhere."""
    with_cont = ifu.moment_maps(
        ifu_cube, 4980.0, 5035.0, LAMBDA_REST, 4905.0, 4935.0, 5040.0, 5055.0, False
    )
    without = ifu.moment_maps(
        ifu_cube, 4980.0, 5035.0, LAMBDA_REST, 4905.0, 4935.0, 5040.0, 5055.0, True
    )
    corner = (slice(0, 6), slice(0, 6))
    assert float(np.median(with_cont.m0[corner])) > 100
    assert abs(float(np.median(without.m0[corner]))) < 20


def test_snr_threshold_blanks_the_velocity_maps(ifu_cube: Cube3D) -> None:
    windows = (4905.0, 4935.0, 5040.0, 5055.0)
    loose = ifu.moment_maps(ifu_cube, 4980.0, 5035.0, LAMBDA_REST, *windows, snr_min=0.0)
    strict = ifu.moment_maps(ifu_cube, 4980.0, 5035.0, LAMBDA_REST, *windows, snr_min=8.0)
    assert loose.m1 is not None and strict.m1 is not None
    assert np.isfinite(strict.m1).sum() < np.isfinite(loose.m1).sum()
    assert np.isfinite(strict.m1).sum() > 0
    assert strict.snr is not None


def test_maps_summary_carries_one_tile_per_map(ifu_cube: Cube3D) -> None:
    summary = ifu.moment_maps(ifu_cube, 4980.0, 5035.0, LAMBDA_REST).summary({"n_out": 48})
    assert [m["key"] for m in summary["maps"]] == ["m0", "m1", "m2", "snr"]
    assert summary["maps"][1]["unit"] == "km/s"
    assert all(m["tile"]["width"] <= 48 for m in summary["maps"])


def test_snr_map_uses_the_variance_cube(ifu_cube: Cube3D) -> None:
    image = ifu.snr_map(ifu_cube, 4990.0, 5025.0)
    assert image.data.shape == ifu_cube.shape[1:]
    assert float(image.data[20, 18]) > float(image.data[2, 2])


def test_snr_map_without_noise_information_is_an_error(ifu_cube: Cube3D) -> None:
    plain = ifu_cube.model_copy(update={"var": None})
    with pytest.raises(ValueError, match="no noise estimate"):
        ifu.snr_map(plain, 4990.0, 5025.0)


def test_snr_map_falls_back_to_the_continuum_windows(ifu_cube: Cube3D) -> None:
    plain = ifu_cube.model_copy(update={"var": None})
    image = ifu.snr_map(plain, 4990.0, 5025.0, 4905.0, 4935.0, 5040.0, 5055.0)
    assert np.isfinite(image.data).any()


def test_moment_map_rejects_an_unknown_order() -> None:
    cube, _ = noiseless_disc(40, 8, 8)
    with pytest.raises(ValueError, match="unsupported moment order"):
        K.moment_map(cube.flux, cube.wave, 4980.0, 5035.0, 3, LAMBDA_REST)
    with pytest.raises(ValueError, match="lambda_rest is required"):
        K.moment_map(cube.flux, cube.wave, 4980.0, 5035.0, 1, None)


def test_empty_window_is_an_error() -> None:
    cube, _ = noiseless_disc(40, 8, 8)
    with pytest.raises(ValueError, match="no channels"):
        K.moment0(cube.flux, cube.wave, 9000.0, 9100.0)


def test_sky_stats_summarises_a_background_region() -> None:
    cube, _ = noiseless_disc(160, 12, 12)
    mask = np.zeros((12, 12), dtype=bool)
    mask[:3, :3] = True
    stats = K.sky_stats(cube.flux, cube.wave, mask, 4980.0, 5035.0)
    assert stats is not None
    assert stats["n_spaxels"] == 9
    assert "sigma_m0" in stats and stats["n_channels"] == 56  # 4980-5035 inclusive
    assert K.sky_stats(cube.flux, cube.wave, np.zeros((12, 12), dtype=bool)) is None


@requires_rbcodes
def test_moments_match_rbcodes(ifu_cube: Cube3D) -> None:
    """Acceptance: the moment maps agree with ``processing.moment_maps`` well under 1 km/s."""
    from rbcodes.GUIs.ifuviewer.processing import moment_maps as upstream

    flux = np.asarray(ifu_cube.flux, dtype=np.float64)
    wave = np.asarray(ifu_cube.wave)
    for order in (0, 1, 2):
        mine = K.moment_map(flux, wave, 4980.0, 5035.0, order, LAMBDA_REST)
        theirs = upstream.moment_map(flux, wave, 4980.0, 5035.0, order, LAMBDA_REST)
        assert np.allclose(mine, theirs, rtol=0, atol=1e-10, equal_nan=True)

    mine_sub = K.subtract_linear_continuum(flux, wave, 4905, 4935, 5040, 5055)
    theirs_sub = upstream.subtract_linear_continuum(flux, wave, 4905, 4935, 5040, 5055)
    assert np.allclose(mine_sub, theirs_sub, rtol=0, atol=1e-10, equal_nan=True)

    m0 = K.moment0(flux, wave, 4980.0, 5035.0)
    var = np.asarray(ifu_cube.var, dtype=np.float64)
    mine_snr = K.compute_snr_map(m0, flux, wave, 4980.0, 5035.0, var=var)
    theirs_snr = upstream.compute_snr_map(m0, flux, wave, 4980.0, 5035.0, var=var)
    assert np.allclose(mine_snr, theirs_snr, rtol=0, atol=1e-10, equal_nan=True)

    mine_stats = K.sky_stats(flux, wave, _corner_mask(), 4980.0, 5035.0)
    theirs_stats = upstream.sky_stats(flux, wave, _corner_mask(), 4980.0, 5035.0)
    assert mine_stats is not None and theirs_stats is not None
    for key, value in theirs_stats.items():
        assert mine_stats[key] == pytest.approx(value, rel=1e-12)


def _corner_mask() -> np.ndarray:
    mask = np.zeros((40, 36), dtype=bool)
    mask[:5, :5] = True
    return mask
