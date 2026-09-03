"""ds9 region files: pixel and sky round-trips, ``regions``-package parity, and the node pair."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from astro_canvas_core.types import Cube3D, Image2D, Region, Region2D
from astro_canvas_rbcodes.kernels import ds9 as D
from astro_canvas_rbcodes.nodes import ifu

from astro_canvas.sdk import NullContext

CIRCLE = Region(shape="circle", pixel=[17.5, 19.5, 5.0], label="disc")
ANNULUS = Region(shape="annulus", pixel=[17.5, 19.5, 13.0, 16.0], label="sky", role="background")
BOX = Region(shape="box", pixel=[10.0, 12.0, 8.0, 6.0, 30.0], label="bar")
# Half-pixel offsets: an edge running exactly along a row of pixel centres would make
# inclusion of that whole row depend on the last decimal of the sky round-trip.
POLYGON = Region(shape="polygon", pixel=[4.5, 4.5, 14.5, 4.5, 9.5, 14.5], label="tri")
ALL = [CIRCLE, ANNULUS, BOX, POLYGON]


@pytest.fixture
def mapper(ifu_cube: Cube3D) -> D.SkyMapper:
    made = D.SkyMapper.from_dict(ifu_cube.wcs)
    assert made is not None
    return made


def test_pixel_roundtrip_is_exact() -> None:
    back = D.from_ds9(D.to_ds9(ALL))
    assert [r.shape for r in back] == [r.shape for r in ALL]
    assert [r.label for r in back] == [r.label for r in ALL]
    assert [r.role for r in back] == ["source", "background", "source", "source"]
    for original, parsed in zip(ALL, back, strict=True):
        assert np.allclose(parsed.pixel, original.pixel, atol=1e-4)


def test_sky_roundtrip_returns_to_the_same_pixels(mapper: D.SkyMapper) -> None:
    """Pixel -> sky -> ds9 text -> sky -> pixel must land within a hundredth of a pixel."""
    with_sky = [D.with_sky(region, mapper) for region in ALL]
    back = D.from_ds9(D.to_ds9(with_sky, sky=True), mapper)
    assert len(back) == len(ALL)
    for original, parsed in zip(ALL, back, strict=True):
        assert np.allclose(parsed.pixel, original.pixel, atol=0.01), original.shape


def test_masks_survive_the_sky_roundtrip(mapper: D.SkyMapper, ifu_cube: Cube3D) -> None:
    """What actually matters downstream: the same spaxels are extracted after a round-trip.

    Degrees are written with six decimals and sizes with four, so a pixel whose centre sits on an
    aperture edge can land on either side afterwards; the mask must agree everywhere else.
    """
    ny, nx = ifu_cube.shape[1:]
    with_sky = [D.with_sky(region, mapper) for region in ALL]
    back = D.from_ds9(D.to_ds9(with_sky, sky=True), mapper)
    for original, parsed in zip(ALL, back, strict=True):
        mine = D.region_mask(parsed, ny, nx)
        theirs = D.region_mask(original, ny, nx)
        assert theirs.sum() > 20
        assert int((mine ^ theirs).sum()) <= 2, original.shape


def test_image_coordinates_are_one_based() -> None:
    text = D.to_ds9([CIRCLE])
    assert "image" in text
    assert "circle(18.5000,20.5000,5.0000)" in text


def test_sky_sizes_are_written_in_arcseconds(mapper: D.SkyMapper) -> None:
    text = D.to_ds9([D.with_sky(CIRCLE, mapper)], sky=True)
    assert "fk5" in text
    assert '1.8000"' in text, "5 spaxels at 0.36 arcsec each"


def test_labels_and_background_tags_travel_in_the_comment() -> None:
    text = D.to_ds9([ANNULUS])
    assert "text={sky}" in text and "tag={background}" in text


def test_excluded_and_annotation_shapes_are_skipped() -> None:
    text = "\n".join(
        [
            "image",
            "-circle(10,10,3)",
            "# compass(10,10,20) compass=icrs {N} {E} 1 1",
            "vector(1,2,3,4)",
            "ellipse(5,5,3,2,0)",
            "circle(20,20,4) # text={keep}",
        ]
    )
    parsed = D.from_ds9(text)
    assert [r.label for r in parsed] == ["keep"]


def test_sky_regions_without_a_wcs_are_skipped() -> None:
    assert D.from_ds9('fk5\ncircle(150.1,2.2,1.8")') == []


@pytest.mark.parametrize(
    ("text", "arcsec"),
    [('12.5"', 12.5), ("0.5'", 30.0), ("0.01d", 36.0), ("0.001", 3.6)],
)
def test_angular_sizes_are_parsed(text: str, arcsec: float) -> None:
    assert D._parse_size_arcsec(text) == pytest.approx(arcsec)


def test_regions_match_the_regions_package(mapper: D.SkyMapper, tmp_path: Path) -> None:
    """Acceptance: what this pack writes is what the ``regions`` package reads back."""
    regions_pkg = pytest.importorskip("regions", reason="the regions package is not installed")
    from astropy.coordinates import SkyCoord

    with_sky = [D.with_sky(region, mapper) for region in (CIRCLE, ANNULUS, BOX)]
    path = tmp_path / "sky.reg"
    # The sample cube's header says RADESYS = ICRS, so the file is labelled icrs; writing it as
    # fk5 (what rb_ifuview always does) would move every centre by about 0.03 arcseconds.
    path.write_text(D.to_ds9(with_sky, sky=True, frame="icrs"), encoding="utf-8")
    parsed = regions_pkg.Regions.read(str(path), format="ds9")
    assert len(parsed) == 3

    circle = parsed[0]
    expected = SkyCoord(with_sky[0].sky[0], with_sky[0].sky[1], unit="deg", frame="icrs")
    assert circle.center.separation(expected).arcsec < 0.01
    assert circle.radius.to("arcsec").value == pytest.approx(1.8, rel=1e-3)

    annulus = parsed[1]
    assert annulus.inner_radius.to("arcsec").value == pytest.approx(13.0 * 0.36, rel=1e-2)
    assert annulus.outer_radius.to("arcsec").value == pytest.approx(16.0 * 0.36, rel=1e-2)

    pixel_path = tmp_path / "pixel.reg"
    pixel_path.write_text(D.to_ds9(ALL), encoding="utf-8")
    in_pixels = regions_pkg.Regions.read(str(pixel_path), format="ds9")
    assert len(in_pixels) == 4
    # ds9 image coordinates are 1-based; the regions package keeps them 0-based.
    assert in_pixels[0].center.x == pytest.approx(CIRCLE.pixel[0], abs=1e-3)
    assert in_pixels[0].center.y == pytest.approx(CIRCLE.pixel[1], abs=1e-3)
    assert in_pixels[0].radius == pytest.approx(CIRCLE.pixel[2], abs=1e-3)

    fk5_path = tmp_path / "fk5.reg"
    fk5_path.write_text(D.to_ds9(with_sky, sky=True), encoding="utf-8")
    as_fk5 = regions_pkg.Regions.read(str(fk5_path), format="ds9")
    assert as_fk5[0].center.frame.name == "fk5"


def test_the_node_pair_round_trips_through_the_workspace(workspace: Path, ifu_cube: Cube3D) -> None:
    ctx = NullContext(workspace=workspace)
    written = ifu.regions_to_ds9(Region2D(regions=ALL), "outputs/apertures.reg", "image", ctx)
    assert written.path == "outputs/apertures.reg"
    assert (workspace / written.path).is_file()
    back = ifu.regions_from_ds9("outputs/apertures.reg", ctx=ctx)
    assert [r.label for r in back.regions] == [r.label for r in ALL]
    assert back.regions[1].role == "background"


def test_the_node_pair_round_trips_in_sky_coordinates(workspace: Path, ifu_cube: Cube3D) -> None:
    ctx = NullContext(workspace=workspace)
    _, regions = ifu.aperture_extract(ifu_cube, [CIRCLE, ANNULUS], "sum")
    ifu.regions_to_ds9(regions, "outputs/sky.reg", "fk5", ctx)
    reference = Image2D(data=np.zeros((40, 36), dtype=np.float32), wcs=ifu_cube.wcs)
    back = ifu.regions_from_ds9("outputs/sky.reg", reference, ctx)
    assert np.allclose(back.regions[0].pixel, CIRCLE.pixel, atol=0.01)
    assert back.regions[1].role == "background"


def test_reading_a_file_with_nothing_usable_is_an_error(workspace: Path) -> None:
    ctx = NullContext(workspace=workspace)
    (workspace / "empty.reg").write_text("image\n# just a comment\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no circle/box/annulus/polygon"):
        ifu.regions_from_ds9("empty.reg", ctx=ctx)


def test_reading_without_a_path_is_an_error() -> None:
    with pytest.raises(ValueError, match="choose a .reg file"):
        ifu.regions_from_ds9("")


def test_region_summary_lists_every_aperture() -> None:
    summary = Region2D(regions=ALL).summary()
    assert summary["count"] == 4
    assert summary["regions"][1]["role"] == "background"
    assert summary["regions"][0]["pixel"] == CIRCLE.pixel
