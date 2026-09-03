"""``rbcodes.ifu.aperture_extract``: masks, extraction methods, background and rbcodes parity."""

from __future__ import annotations

import numpy as np
import pytest
from astro_canvas_core.types import Cube3D, Region, Region2D
from astro_canvas_rbcodes.kernels import ds9 as D
from astro_canvas_rbcodes.kernels import ifu as K
from astro_canvas_rbcodes.nodes import ifu

from tests.packs.rbcodes.conftest import requires_rbcodes

DISC = Region(shape="circle", pixel=[17.5, 19.5, 5.0], label="disc")
CLUMP = Region(shape="circle", pixel=[29.0, 32.0, 3.0], label="clump")
SKY = Region(shape="annulus", pixel=[17.5, 19.5, 13.0, 16.0], label="sky", role="background")
BOX = Region(shape="box", pixel=[17.5, 19.5, 8.0, 6.0, 0.0], label="box")
TRIANGLE = Region(shape="polygon", pixel=[10.0, 10.0, 20.0, 10.0, 15.0, 20.0], label="tri")


def test_circle_mask_matches_rbcodes_convention() -> None:
    """``make_circular_mask``: a pixel is in when its centre is within the radius."""
    mask = K.circle_mask(10, 10, 4.0, 4.0, 2.0)
    assert mask[4, 4] and mask[4, 6] and mask[2, 4]
    assert not mask[4, 7]
    assert mask.sum() == 13


def test_region_mask_covers_every_shape() -> None:
    assert D.region_mask(DISC, 40, 36).sum() == K.circle_mask(40, 36, 17.5, 19.5, 5.0).sum()
    assert D.region_mask(SKY, 40, 36).sum() == K.annulus_mask(40, 36, 17.5, 19.5, 13.0, 16.0).sum()
    assert D.region_mask(BOX, 40, 36).sum() == K.box_mask(40, 36, 17.5, 19.5, 8.0, 6.0).sum()
    triangle = D.region_mask(TRIANGLE, 40, 36)
    assert triangle[12, 15] and not triangle[19, 11]


def test_extraction_equals_the_kernel_on_the_same_mask(ifu_cube: Cube3D) -> None:
    """The acceptance check: the node's spectrum is ``extract_aperture`` over the same mask."""
    spectra, _ = ifu.aperture_extract(ifu_cube, [DISC], "sum")
    mask = D.region_mask(DISC, *ifu_cube.shape[1:])
    expected, error = K.extract_aperture(ifu_cube.flux, ifu_cube.var, mask)
    assert np.allclose(spectra.items[0].flux, expected, rtol=0, atol=1e-10)
    assert spectra.items[0].error is not None
    assert np.allclose(spectra.items[0].error, error, rtol=0, atol=1e-10)
    assert np.array_equal(spectra.items[0].wave, ifu_cube.wave)


@pytest.mark.parametrize("method", ["sum", "mean", "median", "variance_weighted"])
def test_every_method_extracts_the_line(ifu_cube: Cube3D, method: str) -> None:
    spectra, _ = ifu.aperture_extract(ifu_cube, [DISC], method)  # type: ignore[arg-type]
    flux = spectra.items[0].flux
    peak = int(np.nanargmax(flux))
    assert 4995.0 < ifu_cube.wave[peak] < 5020.0
    assert spectra.items[0].meta["n_spaxels"] == int(D.region_mask(DISC, 40, 36).sum())


def test_variance_weighted_needs_a_variance_cube(ifu_cube: Cube3D) -> None:
    plain = ifu_cube.model_copy(update={"var": None})
    with pytest.raises(ValueError, match="variance"):
        ifu.aperture_extract(plain, [DISC], "variance_weighted")


def test_background_subtraction_removes_the_continuum(ifu_cube: Cube3D) -> None:
    raw, _ = ifu.aperture_extract(ifu_cube, [DISC, SKY], "mean")
    subtracted, _ = ifu.aperture_extract(ifu_cube, [DISC, SKY], "mean", "mean")
    off_line = ifu_cube.wave < 4950.0
    assert float(np.median(raw.items[0].flux[off_line])) > 2.0
    assert abs(float(np.median(subtracted.items[0].flux[off_line]))) < 0.2


def test_background_regions_are_not_extracted(ifu_cube: Cube3D) -> None:
    spectra, regions = ifu.aperture_extract(ifu_cube, [DISC, CLUMP, SKY], "sum")
    assert spectra.labels == ["disc", "clump"]
    assert len(regions.regions) == 3
    assert [r.role for r in regions.regions] == ["source", "source", "background"]


def test_background_without_a_background_region_is_an_error(ifu_cube: Cube3D) -> None:
    with pytest.raises(ValueError, match="needs at least one background aperture"):
        ifu.aperture_extract(ifu_cube, [DISC], "sum", "mean")


def test_only_background_regions_is_an_error(ifu_cube: Cube3D) -> None:
    with pytest.raises(ValueError, match="marked as background"):
        ifu.aperture_extract(ifu_cube, [SKY], "sum")


def test_no_regions_at_all_is_an_error(ifu_cube: Cube3D) -> None:
    with pytest.raises(ValueError, match="draw at least one aperture"):
        ifu.aperture_extract(ifu_cube, [])


def test_an_aperture_off_the_field_is_reported(ifu_cube: Cube3D) -> None:
    off = Region(shape="circle", pixel=[500.0, 500.0, 2.0], label="nowhere")
    with pytest.raises(ValueError, match="covers no spaxel"):
        ifu.aperture_extract(ifu_cube, [off])


def test_the_seed_input_fills_in_while_the_parameter_is_empty(ifu_cube: Cube3D) -> None:
    """The multispec pattern: the parameter wins, the input seeds it."""
    seeded, _ = ifu.aperture_extract(ifu_cube, [], "sum", "none", Region2D(regions=[CLUMP]))
    assert seeded.labels == ["clump"]
    edited, _ = ifu.aperture_extract(ifu_cube, [DISC], "sum", "none", Region2D(regions=[CLUMP]))
    assert edited.labels == ["disc"]


def test_output_regions_gain_sky_coordinates(ifu_cube: Cube3D) -> None:
    _, regions = ifu.aperture_extract(ifu_cube, [DISC])
    sky = regions.regions[0].sky
    assert sky is not None and len(sky) == 3
    assert 150.0 < sky[0] < 150.2 and 2.1 < sky[1] < 2.3
    assert sky[2] == pytest.approx(5.0 * 0.36, rel=0.02), 'radius in arcsec at 0.36"/spaxel'


def test_iau_names_come_from_the_sky_position(ifu_cube: Cube3D) -> None:
    _, regions = ifu.aperture_extract(ifu_cube, [DISC, CLUMP])
    table = ifu.iau_names(regions)
    assert list(table.columns["label"]) == ["disc", "clump"]
    assert all(str(name).startswith("J10") for name in table.columns["name"])
    assert table.columns["ra"][0] != table.columns["ra"][1]
    assert table.units["ra"] == "deg"


def test_iau_names_fall_back_to_an_index_without_a_wcs() -> None:
    table = ifu.iau_names(Region2D(regions=[DISC]))
    assert list(table.columns["name"]) == ["J001"]
    assert np.isnan(table.columns["ra"][0])


@requires_rbcodes
def test_extraction_matches_rbcodes(ifu_cube: Cube3D) -> None:
    """Acceptance: the node reproduces ``processing.aperture_extract`` on the same mask to 1e-10."""
    from rbcodes.GUIs.ifuviewer.processing import aperture_extract as upstream

    # The node sums the cube's own float32 array; casting to float64 first would change the
    # accumulation order and show a 1e-5 difference that has nothing to do with the algorithm.
    flux = np.asarray(ifu_cube.flux)
    var = np.asarray(ifu_cube.var)
    mask = upstream.make_circular_mask(40, 36, 17.5, 19.5, 5.0)
    assert np.array_equal(mask, D.region_mask(DISC, 40, 36))

    spectra, _ = ifu.aperture_extract(ifu_cube, [DISC], "sum")
    theirs, their_error = upstream.extract_aperture(flux, var, mask)
    assert np.allclose(spectra.items[0].flux, theirs, rtol=0, atol=1e-10)
    assert np.allclose(spectra.items[0].error, their_error, rtol=0, atol=1e-10)

    weighted, _ = ifu.aperture_extract(ifu_cube, [DISC], "variance_weighted")
    their_weighted, _ = upstream.extract_variance_weighted(flux, var, mask)
    assert np.allclose(weighted.items[0].flux, their_weighted, rtol=0, atol=1e-10, equal_nan=True)

    annulus = upstream.make_annulus_mask(40, 36, 17.5, 19.5, 13.0, 16.0)
    assert np.array_equal(annulus, D.region_mask(SKY, 40, 36))
    subtracted, _ = ifu.aperture_extract(ifu_cube, [DISC, SKY], "sum", "mean")
    expected = upstream.subtract_background(theirs, flux, annulus, "mean")
    # Upstream never widens, so its background level is float32; the node subtracts in float64.
    assert expected.dtype == np.float32
    assert np.allclose(subtracted.items[0].flux, expected, rtol=1e-6, atol=0)
