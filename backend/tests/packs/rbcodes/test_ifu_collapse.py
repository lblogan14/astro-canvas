"""``rbcodes.ifu`` collapses and subcubes: values, wavelength windows, WCS and rbcodes parity."""

from __future__ import annotations

import numpy as np
import pytest
from astro_canvas_core.io.image import read_cube
from astro_canvas_core.types import Cube3D
from astro_canvas_rbcodes.kernels import ifu as K
from astro_canvas_rbcodes.nodes import ifu

from tests.packs.rbcodes.conftest import requires_rbcodes


def test_whitelight_matches_a_nan_aware_mean(ifu_cube: Cube3D) -> None:
    image = ifu.whitelight(ifu_cube)
    expected = np.nanmean(np.asarray(ifu_cube.flux, dtype=np.float64), axis=0)
    assert image.data.shape == ifu_cube.shape[1:]
    assert np.allclose(image.data, expected, rtol=1e-6)
    assert image.header["_KIND"] == "whitelight"


def test_whitelight_band_restricts_the_channels(ifu_cube: Cube3D) -> None:
    image = ifu.whitelight(ifu_cube, 5000.0, 5015.0, "sum")
    band = (ifu_cube.wave >= 5000.0) & (ifu_cube.wave <= 5015.0)
    expected = np.nansum(np.asarray(ifu_cube.flux, dtype=np.float64)[band], axis=0)
    assert np.allclose(image.data, expected, rtol=1e-6)
    assert image.header["_BAND"] == [5000.0, 5015.0]


def test_whitelight_carries_the_two_axis_wcs(ifu_cube: Cube3D) -> None:
    """A collapse of a 3-axis cube must present a 2-axis WCS or the readout mislabels the sky."""
    image = ifu.whitelight(ifu_cube)
    assert image.wcs is not None
    assert image.wcs["naxis"] == 2
    assert image.wcs["ctype"] == ["RA---TAN", "DEC--TAN"]
    assert len(image.wcs["crval"]) == 2


def test_narrowband_needs_a_window(ifu_cube: Cube3D) -> None:
    with pytest.raises(ValueError, match="wavelength window is empty"):
        ifu.narrowband(ifu_cube, 5010.0, 5010.0)


def test_narrowband_finds_the_line(ifu_cube: Cube3D) -> None:
    """On-band flux at the disc centre must exceed a continuum window of the same width."""
    on = ifu.narrowband(ifu_cube, 5000.0, 5015.0)
    off = ifu.narrowband(ifu_cube, 4905.0, 4920.0)
    assert float(on.data[20, 18]) > 3 * float(off.data[20, 18])


def test_continuum_sub_removes_the_baseline(ifu_cube: Cube3D) -> None:
    image = ifu.continuum_sub(ifu_cube, 5000.0, 5015.0, 4905.0, 4935.0, 5040.0, 5055.0)
    corner = float(np.nanmedian(image.data[:6, :6]))
    assert abs(corner) < 0.2, "an empty corner must be near zero after subtraction"
    assert float(image.data[20, 18]) > 10


def test_continuum_sub_requires_a_blue_window(ifu_cube: Cube3D) -> None:
    with pytest.raises(ValueError, match="blue continuum window is required"):
        ifu.continuum_sub(ifu_cube, 5000.0, 5015.0)


def test_subcube_crops_and_shifts_crpix(ifu_cube: Cube3D) -> None:
    cut = ifu.subcube(ifu_cube, 4950.0, 5050.0, 5, 30, 4, 28)
    assert cut.shape == (int(((ifu_cube.wave >= 4950) & (ifu_cube.wave <= 5050)).sum()), 24, 25)
    assert np.allclose(cut.flux[0], ifu_cube.flux[ifu_cube.band(4950.0, 5050.0)][0, 4:28, 5:30])
    assert cut.var is not None
    assert ifu_cube.wcs is not None and cut.wcs is not None
    assert cut.wcs["crpix"][0] == ifu_cube.wcs["crpix"][0] - 5
    assert cut.wcs["crpix"][1] == ifu_cube.wcs["crpix"][1] - 4
    assert cut.header["_CROP"] == [5, 30, 4, 28]


def test_subcube_rejects_a_box_outside_the_field(ifu_cube: Cube3D) -> None:
    with pytest.raises(ValueError, match="outside a"):
        ifu.subcube(ifu_cube, 0.0, 0.0, 0, 500)


def test_subcube_keeps_the_sky_position_of_a_pixel(ifu_cube: Cube3D) -> None:
    """The whole point of shifting CRPIX: a spaxel keeps its sky coordinates after the crop."""
    from astro_canvas_rbcodes.kernels.ds9 import SkyMapper

    full = SkyMapper.from_dict(ifu_cube.wcs)
    cut = ifu.subcube(ifu_cube, 0.0, 0.0, 6, 30, 3, 30)
    mapped = SkyMapper.from_dict(cut.wcs)
    assert full is not None and mapped is not None
    assert np.allclose(full.to_sky(10.0, 12.0), mapped.to_sky(4.0, 9.0), atol=1e-9)


def test_summary_of_a_collapse_is_a_tile(ifu_cube: Cube3D) -> None:
    summary = ifu.whitelight(ifu_cube).summary({"n_out": 64})
    assert summary["tile"]["width"] <= 64
    assert summary["shape"] == [40, 36]


def test_loader_choice_is_a_parameter() -> None:
    params = {
        p.name: p
        for p in __import__(
            "astro_canvas_core.nodes.io", fromlist=["load_cube"]
        ).load_cube.spec.params
    }
    assert params["loader"].json_schema["enum"] == ["auto", "rbcodes"]


@requires_rbcodes
def test_collapses_match_rbcodes(ifu_cube: Cube3D) -> None:
    """The vendored kernels and ``GUIs.ifuviewer.processing.cube_collapse`` must agree exactly."""
    from rbcodes.GUIs.ifuviewer.processing import cube_collapse

    flux = np.asarray(ifu_cube.flux, dtype=np.float64)
    wave = np.asarray(ifu_cube.wave)
    for method in ("mean", "sum", "median"):
        mine = K.build_whitelight(flux, wave, 4990.0, 5030.0, method)
        theirs = cube_collapse.build_whitelight(flux, wave, 4990.0, 5030.0, method)
        assert np.allclose(mine, theirs, rtol=0, atol=1e-10, equal_nan=True)
    mine_cs = K.build_continuum_sub(flux, wave, 5000, 5015, 4905, 4935, 5040, 5055, "mean")
    theirs_cs = cube_collapse.build_continuum_sub(
        flux, wave, 5000, 5015, 4905, 4935, 5040, 5055, "mean"
    )
    assert np.allclose(mine_cs, theirs_cs, rtol=0, atol=1e-10, equal_nan=True)


@requires_rbcodes
def test_rbcodes_loader_reads_the_same_cube(samples) -> None:  # type: ignore[no-untyped-def]
    """``loader='rbcodes'`` goes through ``auto_cube.load_fits`` and lands on the same arrays."""
    mine = read_cube(samples / "synthetic_ifu_icubes.fits")
    theirs = read_cube(samples / "synthetic_ifu_icubes.fits", loader="rbcodes")
    assert theirs.shape == mine.shape
    assert np.allclose(theirs.flux, mine.flux, equal_nan=True)
    assert np.allclose(theirs.wave, mine.wave)
    assert theirs.instrument == "KCWI"
    assert theirs.header["_LOADER"] == "KCWICube"
