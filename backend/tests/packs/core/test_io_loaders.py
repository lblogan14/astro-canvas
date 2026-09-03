"""``core.io.*`` loaders and savers against the bundled sample data (astropy path, no rbcodes)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from astro_canvas_core.io import spectrum as spectrum_io
from astro_canvas_core.io.fits_meta import header_to_dict, spectral_axis, wcs_dict
from astro_canvas_core.io.image import ImageReadError, read_cube, read_image
from astro_canvas_core.io.paths import WorkspacePathError, file_fingerprint, resolve_in_workspace
from astro_canvas_core.io.spectrum import SpectrumReadError, read_spectrum
from astro_canvas_core.io.table import TableReadError, read_table
from astro_canvas_core.nodes import io as io_nodes
from astro_canvas_core.types import File, Json, Spectrum1D
from astropy.io import fits
from astropy.table import Table as AstroTable
from astropy.wcs import WCS

from astro_canvas.sdk import NullContext

SAMPLE = "samples/rbcodes"


# --- spectra --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["sdss1.fits", "sdss2.fits", "spec-0398-51789-0282.fits"])
def test_sdss_spectra_load_with_vacuum_wavelengths_and_errors(samples: Path, name: str) -> None:
    spec = read_spectrum(samples / name, use_rbcodes=False)
    assert spec.meta["format"] == "sdss" and spec.meta["airvac"] == "vac"
    assert len(spec) > 3000 and spec.wave_unit == "Angstrom"
    assert np.all(np.diff(spec.wave) > 0) and 3500 < spec.wave[0] < 4000 and spec.wave[-1] > 9000
    assert spec.error is not None and np.nanmedian(spec.error) > 0
    assert spec.continuum is not None  # the SDSS ``model`` column
    assert spec.flux_unit.startswith("1e-17")
    assert "TELESCOP" in spec.meta and spec.meta["TELESCOP"].startswith("SDSS")
    with fits.open(samples / name) as hdul:
        loglam = np.asarray(hdul[1].data["loglam"], dtype=np.float64)
        ivar = np.asarray(hdul[1].data["ivar"], dtype=np.float64)
    np.testing.assert_allclose(spec.wave, 10.0**loglam)
    good = ivar > 0
    np.testing.assert_allclose(spec.error[good], 1.0 / np.sqrt(ivar[good]))
    assert np.all(np.isnan(spec.error[~good]))


def test_multi_extension_fits_matches_rbcodes_layout(samples: Path) -> None:
    spec = read_spectrum(samples / "test.fits", use_rbcodes=False)
    with fits.open(samples / "test.fits") as hdul:
        np.testing.assert_array_equal(spec.flux, np.asarray(hdul["FLUX"].data, dtype=np.float64))
        np.testing.assert_array_equal(spec.wave, hdul["WAVELENGTH"].data)
        assert spec.error is not None and spec.continuum is not None
        np.testing.assert_array_equal(spec.error, hdul["ERROR"].data)
        np.testing.assert_array_equal(spec.continuum, hdul["CONTINUUM"].data)
    assert len(spec) == 19663 and spec.meta["format"] == "fits"


def test_binary_table_and_ascii_spectra(samples: Path) -> None:
    table = read_spectrum(samples / "galaxy1.fits", use_rbcodes=False)
    assert table.error is not None and table.continuum is not None and len(table) > 100
    ascii_spec = read_spectrum(samples / "spectrum_OII_carc_Middle.dat", use_rbcodes=False)
    assert ascii_spec.meta["format"] == "ascii"
    assert ascii_spec.wave[0] == pytest.approx(6559.607421875)
    assert ascii_spec.error is not None and ascii_spec.continuum is not None
    assert ascii_spec.error[0] == pytest.approx(13.57089614868164)


def test_format_override_and_errors(samples: Path, tmp_path: Path) -> None:
    forced = read_spectrum(samples / "sdss1.fits", "sdss", use_rbcodes=False)
    assert forced.meta["format"] == "sdss"
    with pytest.raises(SpectrumReadError, match="unknown spectrum format"):
        read_spectrum(samples / "sdss1.fits", "nope")
    with pytest.raises(FileNotFoundError):
        read_spectrum(samples / "missing.fits")
    fits.PrimaryHDU(np.zeros((100, 100), dtype=np.float32)).writeto(tmp_path / "img.fits")
    with pytest.raises(SpectrumReadError, match="not a spectrum"):
        read_spectrum(tmp_path / "img.fits", use_rbcodes=False)
    table = fits.BinTableHDU.from_columns([fits.Column(name="RA", format="D", array=np.zeros(3))])
    fits.HDUList([fits.PrimaryHDU(), table]).writeto(tmp_path / "cat.fits")
    with pytest.raises(SpectrumReadError, match="wavelength/flux"):
        read_spectrum(tmp_path / "cat.fits", use_rbcodes=False)


def test_header_axis_single_extension_with_sidecar_error(tmp_path: Path) -> None:
    n = 50
    hdu = fits.PrimaryHDU(np.linspace(1, 2, n).astype(np.float32))
    hdu.header.update({"CRVAL1": 3.5, "CDELT1": 1e-4, "CRPIX1": 1.0, "DC-FLAG": 1, "BUNIT": "adu"})
    hdu.writeto(tmp_path / "log.fits")
    fits.PrimaryHDU(np.full(n, 0.1, dtype=np.float32)).writeto(tmp_path / "loge.fits")
    spec = read_spectrum(tmp_path / "log.fits", use_rbcodes=False)
    np.testing.assert_allclose(spec.wave, 10.0 ** (3.5 + 1e-4 * np.arange(n)))
    assert spec.error is not None and spec.error[0] == pytest.approx(0.1)
    assert spec.flux_unit == "adu"
    # Linear axis with a micron unit is converted to Angstrom.
    lin = fits.PrimaryHDU(np.ones(10, dtype=np.float32))
    lin.header.update({"CRVAL1": 1.0, "CDELT1": 0.01, "CRPIX1": 1.0, "CUNIT1": "um"})
    lin.writeto(tmp_path / "um.fits")
    um = read_spectrum(tmp_path / "um.fits", use_rbcodes=False)
    assert um.wave_unit == "Angstrom" and um.wave[0] == pytest.approx(1e4)
    assert um.meta["wave_unit_original"] == "um"
    with pytest.raises(ValueError, match="CRVAL1"):
        spectral_axis(fits.Header({"NAXIS1": 5}))


def test_sdss_spspec_desi_brick_and_desi_coadd(tmp_path: Path) -> None:
    rows = np.vstack([np.ones(20), np.zeros(20), np.full(20, 0.5)]).astype(np.float32)
    sp = fits.PrimaryHDU(rows)
    sp.header.update({"CRVAL1": 3.6, "CD1_1": 1e-4, "CRPIX1": 1, "DC-FLAG": 1})
    sp.writeto(tmp_path / "spSpec.fits")
    spec = read_spectrum(tmp_path / "spSpec.fits", use_rbcodes=False)
    assert spec.meta["layout"] == "sdss-spSpec" and spec.error is not None
    assert spec.error[0] == pytest.approx(0.5) and spec.wave[0] == pytest.approx(10**3.6)

    brick_flux = fits.PrimaryHDU(np.ones((2, 10), dtype=np.float32))
    brick_flux.name = "FLUX"
    brick = fits.HDUList(
        [
            brick_flux,
            fits.ImageHDU(np.full((2, 10), 4.0, dtype=np.float32), name="IVAR"),
            fits.ImageHDU(np.arange(10, dtype=np.float64) + 4000, name="WAVELENGTH"),
        ]
    )
    brick.writeto(tmp_path / "brick.fits")
    desi = read_spectrum(tmp_path / "brick.fits", use_rbcodes=False)
    assert desi.meta["format"] == "desi" and desi.error is not None
    assert desi.error[0] == pytest.approx(0.5) and desi.wave[-1] == 4009

    coadd = fits.HDUList([fits.PrimaryHDU()])
    for cam, start in (("R", 5000.0), ("B", 3600.0)):
        coadd.append(
            fits.ImageHDU(np.arange(5, dtype=np.float64) + start, name=f"{cam}_WAVELENGTH")
        )
        coadd.append(fits.ImageHDU(np.full((1, 5), 2.0, dtype=np.float32), name=f"{cam}_FLUX"))
        coadd.append(fits.ImageHDU(np.full((1, 5), 1.0, dtype=np.float32), name=f"{cam}_IVAR"))
    coadd.writeto(tmp_path / "coadd.fits")
    joined = read_spectrum(tmp_path / "coadd.fits", use_rbcodes=False)
    assert joined.meta["cameras"] == ["B", "R"] and len(joined) == 10
    assert np.all(np.diff(joined.wave) > 0) and joined.wave[0] == 3600.0


def test_json_spectra_and_ecsv(tmp_path: Path) -> None:
    rbspec = {
        "wave_slice": [1000.0, 1001.0, 1002.0],
        "flux_slice": [1.0, 0.5, 1.0],
        "error_slice": [0.1, 0.1, 0.1],
        "fnorm": [1.0, 0.5, 1.0],
        "zabs": 1.0,
        "W": 0.4,
    }
    (tmp_path / "rb.json").write_text(json.dumps(rbspec), encoding="utf-8")
    spec = read_spectrum(tmp_path / "rb.json", use_rbcodes=False)
    assert spec.z == 1.0 and spec.wave[0] == 2000.0 and spec.meta["rb_spec_analysis"]["W"] == 0.4
    assert spec.continuum is not None and spec.continuum[1] == pytest.approx(1.0)

    native = {
        "wavelength": [500.0, 501.0],
        "flux": [1.0, 2.0],
        "error": [0.1, 0.2],
        "metadata": {"airvac": "air"},
        "units": {"wave": "nm", "flux": "Jy"},
    }
    (tmp_path / "native.json").write_text(json.dumps(native), encoding="utf-8")
    spec2 = read_spectrum(tmp_path / "native.json", use_rbcodes=False)
    assert spec2.wave[0] == pytest.approx(5000.0) and spec2.flux_unit == "Jy"
    assert spec2.meta["airvac"] == "air"
    (tmp_path / "bad.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(SpectrumReadError):
        read_spectrum(tmp_path / "bad.json", use_rbcodes=False)

    table = AstroTable({"wave": [1.0, 2.0], "flux": [3.0, 4.0], "ivar": [4.0, 4.0]})
    table["wave"].unit = "nm"
    table.write(tmp_path / "spec.ecsv", format="ascii.ecsv")
    ecsv = read_spectrum(tmp_path / "spec.ecsv", use_rbcodes=False)
    assert ecsv.meta["format"] == "ecsv" and ecsv.wave[0] == pytest.approx(10.0)
    assert ecsv.error is not None and ecsv.error[0] == pytest.approx(0.5)


def test_unsorted_wavelengths_are_sorted(tmp_path: Path) -> None:
    (tmp_path / "rev.dat").write_text("3.0 30\n1.0 10\n2.0 20\n", encoding="utf-8")
    spec = read_spectrum(tmp_path / "rev.dat", use_rbcodes=False)
    assert spec.wave.tolist() == [1.0, 2.0, 3.0] and spec.flux.tolist() == [10.0, 20.0, 30.0]


def test_rbcodes_path_is_optional(monkeypatch: pytest.MonkeyPatch, samples: Path) -> None:
    monkeypatch.setattr(spectrum_io, "rbcodes_available", lambda: True)
    monkeypatch.setattr(spectrum_io, "_read_with_rbcodes", lambda path: None)
    spec = read_spectrum(samples / "sdss1.fits")  # falls back to astropy
    assert spec.meta["format"] == "sdss"
    assert isinstance(spectrum_io.rbcodes_available(), bool)


# --- images and cubes -----------------------------------------------------------------------------


def test_read_image_and_wcs_dict(samples: Path) -> None:
    image = read_image(samples / "synthetic_image.fits")
    assert image.shape == (80, 96) and image.data.dtype == np.float32
    assert image.unit == "count" and image.header["OBJECT"] == "Synthetic field"
    assert image.wcs is not None and image.wcs["ctype"] == ["RA---TAN", "DEC--TAN"]
    assert image.wcs["cd"][0][0] == pytest.approx(-2.5e-5 * np.cos(np.radians(15.0)))
    with fits.open(samples / "synthetic_image.fits") as hdul:
        wcs = WCS(hdul[0].header)
        header = hdul[0].header
    ra, dec = wcs.all_pix2world([[10.0, 20.0]], 0)[0]
    # A pure-dict WCS must carry everything the frontend needs for a TAN inverse.
    assert set(image.wcs) >= {"crval", "crpix", "cd", "ctype", "naxis"}
    assert image.wcs["crval"] == [header["CRVAL1"], header["CRVAL2"]]
    assert header_to_dict(header)["COMMENT"][0].startswith("Synthetic")
    assert wcs_dict(fits.Header({"NAXIS": 2})) is None
    assert 150.0 < ra < 150.3 and 2.5 < dec < 2.7


def test_read_image_extension_selection_and_errors(tmp_path: Path) -> None:
    hdul = fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.ImageHDU(np.ones((4, 5), dtype=np.int16), name="SCI"),
            fits.ImageHDU(np.zeros((4, 5), dtype=np.float32), name="ERR"),
        ]
    )
    hdul.writeto(tmp_path / "multi.fits")
    image = read_image(tmp_path / "multi.fits")
    assert image.header["_EXTNAME"] == "SCI" and image.data.dtype == np.float32
    assert read_image(tmp_path / "multi.fits", "ERR").data.sum() == 0
    assert read_image(tmp_path / "multi.fits", "2").data.sum() == 0
    with pytest.raises(ImageReadError):
        read_image(tmp_path / "multi.fits", "nope")
    with pytest.raises(ImageReadError):
        read_image(tmp_path / "multi.fits", 0)
    fits.PrimaryHDU(np.zeros(5, dtype=np.float32)).writeto(tmp_path / "one_d.fits")
    with pytest.raises(ImageReadError, match="no 2-d array"):
        read_image(tmp_path / "one_d.fits")


def test_read_kcwi_cube_with_variance_sidecar(samples: Path) -> None:
    cube = read_cube(samples / "synthetic_kcwi_icubes.fits")
    assert cube.shape == (240, 30, 24) and cube.instrument == "KCWI"
    assert cube.var is not None and cube.var.shape == cube.flux.shape
    assert cube.var[0, 0, 0] == pytest.approx(0.05**2)
    np.testing.assert_allclose(cube.wave, 3500.0 + 0.5 * np.arange(240))
    assert cube.header["_WAVEUNIT"] == "Angstrom" and cube.wcs is not None
    assert cube.wcs["ctype"][2] == "AWAV" and cube.wcs["naxis"] == 3
    white = cube.white_light(3555.0, 3565.0)
    assert white.shape == (30, 24)
    assert tuple(np.unravel_index(white.argmax(), white.shape)) in {(14, 11), (14, 12)}


def test_read_muse_and_manga_style_cubes(tmp_path: Path) -> None:
    data = np.random.default_rng(1).normal(size=(6, 3, 4)).astype(np.float32)
    muse = fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.ImageHDU(data, name="DATA"),
            fits.ImageHDU(np.full(data.shape, 2.0, dtype=np.float32), name="STAT"),
        ]
    )
    muse[1].header.update(
        {"CTYPE3": "AWAV", "CUNIT3": "nm", "CRVAL3": 480.0, "CD3_3": 0.125, "CRPIX3": 1.0}
    )
    muse[0].header["INSTRUME"] = "MUSE"
    muse.writeto(tmp_path / "muse.fits")
    cube = read_cube(tmp_path / "muse.fits")
    assert cube.instrument == "MUSE" and cube.var is not None and cube.var[0, 0, 0] == 2.0
    assert cube.wave[0] == pytest.approx(4800.0) and cube.wave[1] == pytest.approx(4801.25)
    assert cube.header["_WAVEUNIT_ORIGINAL"] == "nm"

    manga = fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.ImageHDU(data, name="FLUX"),
            fits.ImageHDU(np.full(data.shape, 4.0, dtype=np.float32), name="IVAR"),
            fits.ImageHDU(np.arange(6, dtype=np.float64) * 10 + 3600, name="WAVE"),
        ]
    )
    manga[0].header["INSTRUME"] = "MaNGA"
    manga.writeto(tmp_path / "manga.fits")
    cube2 = read_cube(tmp_path / "manga.fits")
    assert cube2.var is not None and cube2.var[0, 0, 0] == pytest.approx(0.25)
    assert cube2.wave[-1] == 3650.0 and cube2.instrument == "MaNGA"

    plain = fits.PrimaryHDU(data)
    plain.writeto(tmp_path / "plain.fits")
    cube3 = read_cube(tmp_path / "plain.fits")
    assert cube3.var is None and cube3.wave.tolist() == [0, 1, 2, 3, 4, 5]
    assert cube3.header["_WAVEUNIT"] == "pixel" and cube3.wcs is None
    with pytest.raises(ImageReadError):
        read_cube(tmp_path / "plain.fits", var_ext="7")


# --- tables ---------------------------------------------------------------------------------------


def test_read_tables_from_fits_ecsv_csv_json(samples: Path, tmp_path: Path) -> None:
    from_fits = read_table(samples / "galaxy1.fits")
    assert set(from_fits.columns) == {"WAVELENGTH", "FLUX", "ERROR", "CONTINUUM"}
    assert from_fits.meta["extname"] == "" or isinstance(from_fits.meta["extname"], str)
    assert from_fits.meta["source"] == "galaxy1.fits"

    table = AstroTable({"a": [1, 2], "b": ["x", "y"], "c": [1.5, np.nan]})
    table["c"].unit = "km / s"
    table.write(tmp_path / "t.ecsv", format="ascii.ecsv")
    ecsv = read_table(tmp_path / "t.ecsv")
    assert ecsv.columns["a"].dtype == np.int64 and ecsv.columns["b"].dtype.kind == "U"
    assert ecsv.units == {"c": "km / s"} and np.isnan(ecsv.columns["c"][1])
    table.write(tmp_path / "t.csv", format="ascii.csv")
    csv = read_table(tmp_path / "t.csv")
    assert csv.n_rows == 2 and csv.columns["b"].tolist() == ["x", "y"]
    (tmp_path / "rows.json").write_text(
        '[{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]', encoding="utf-8"
    )
    assert read_table(tmp_path / "rows.json").columns["a"].tolist() == [1, 2]
    (tmp_path / "cols.json").write_text('{"a": [1, 2]}', encoding="utf-8")
    assert read_table(tmp_path / "cols.json").n_rows == 2
    (tmp_path / "scalar.json").write_text("5", encoding="utf-8")
    with pytest.raises(TableReadError):
        read_table(tmp_path / "scalar.json")
    with pytest.raises(TableReadError, match="unknown table format"):
        read_table(tmp_path / "t.csv", "nope")
    with pytest.raises(FileNotFoundError):
        read_table(tmp_path / "missing.csv")
    with pytest.raises(TableReadError):
        read_table(samples / "test.fits")  # image extensions only
    with pytest.raises(TableReadError):
        read_table(samples / "galaxy1.fits", ext="0")
    assert read_table(samples / "galaxy1.fits", ext="1").n_rows == from_fits.n_rows


def test_multidimensional_columns_are_skipped(samples: Path) -> None:
    table = read_table(samples / "sdss1.fits", ext="SPZLINE")
    assert "LINENAME" in table.columns and table.columns["LINENAME"].dtype.kind == "U"
    coadd = read_table(samples / "sdss1.fits", ext="COADD")
    assert coadd.n_rows > 3000 and "loglam" in coadd.columns


# --- nodes, paths and savers ----------------------------------------------------------------------


def test_load_nodes_run_through_the_node_api(ctx: NullContext) -> None:
    spec = io_nodes.load_spectrum.call(params={"path": f"{SAMPLE}/sdss1.fits"}, ctx=ctx)
    assert isinstance(spec, Spectrum1D) and len(spec) > 3000
    image = io_nodes.load_image.call(params={"path": f"{SAMPLE}/synthetic_image.fits"}, ctx=ctx)
    assert image.shape == (80, 96)
    cube = io_nodes.load_cube.call(params={"path": f"{SAMPLE}/synthetic_kcwi_icubes.fits"}, ctx=ctx)
    assert cube.shape == (240, 30, 24)
    table = io_nodes.load_table.call(params={"path": f"{SAMPLE}/galaxy1.fits", "ext": "1"}, ctx=ctx)
    assert table.n_rows > 0
    for loader in (
        io_nodes.load_spectrum,
        io_nodes.load_image,
        io_nodes.load_cube,
        io_nodes.load_table,
    ):
        with pytest.raises(ValueError, match="choose a file"):
            loader.call(params={}, ctx=ctx)
        with pytest.raises(WorkspacePathError):
            loader.call(params={"path": "../outside.fits"}, ctx=ctx)
    spec_spec = io_nodes.load_spectrum.spec
    assert [p.name for p in spec_spec.params] == ["path", "format", "use_rbcodes"]
    assert spec_spec.params[0].widget == "file" and spec_spec.fingerprint is True
    assert spec_spec.params[1].json_schema["enum"][0] == "auto"


def test_file_fingerprint_tracks_mtime_and_size(workspace: Path) -> None:
    target = workspace / "samples" / "rbcodes" / "sdss1.fits"
    first = file_fingerprint(path=f"{SAMPLE}/sdss1.fits", workspace=workspace)
    stat = target.stat()
    assert first == f"{stat.st_mtime_ns}:{stat.st_size}"
    assert file_fingerprint(path="", workspace=workspace) == "no-path"
    assert file_fingerprint(path="nope.fits", workspace=workspace) == "missing"
    assert file_fingerprint(path="../x", workspace=workspace) == "missing"
    assert file_fingerprint(path="x") == "no-path"
    assert io_nodes.load_spectrum.fingerprint_wants_workspace is True


def test_resolve_in_workspace_rejects_escapes(workspace: Path) -> None:
    assert resolve_in_workspace(workspace, "samples/rbcodes").is_dir()
    for bad in ("../x", "/abs", "C:/win", "a/../../b", "//server/share"):
        with pytest.raises(WorkspacePathError):
            resolve_in_workspace(workspace, bad)


def test_save_nodes_round_trip(ctx: NullContext, workspace: Path) -> None:
    spec = io_nodes.load_spectrum.call(params={"path": f"{SAMPLE}/test.fits"}, ctx=ctx)
    for fmt in ("fits", "ecsv", "json", "csv"):
        saved = io_nodes.save_spectrum.call(
            inputs={"spec": spec}, params={"path": f"outputs/spec.{fmt}", "format": fmt}, ctx=ctx
        )
        assert isinstance(saved, File) and saved.path == f"outputs/spec.{fmt}" and saved.size > 0
        assert saved.blake3 is not None and len(saved.blake3) == 64
        back = read_spectrum(workspace / saved.path, use_rbcodes=False)
        np.testing.assert_allclose(back.wave, spec.wave)
        np.testing.assert_allclose(back.flux, spec.flux, rtol=1e-6)
        assert back.error is not None and back.continuum is not None
    fits_meta = fits.getheader(workspace / "outputs" / "spec.fits")
    assert fits_meta["FRAME"] == "observed" and fits_meta["WAVEUNIT"] == "Angstrom"

    table = io_nodes.load_table.call(params={"path": f"{SAMPLE}/galaxy1.fits"}, ctx=ctx)
    for fmt in ("ecsv", "csv", "fits", "votable", "json"):
        saved = io_nodes.save_table.call(
            inputs={"table": table}, params={"path": f"outputs/t.{fmt}", "format": fmt}, ctx=ctx
        )
        again = read_table(workspace / saved.path, "votable" if fmt == "votable" else "auto")
        assert again.n_rows == table.n_rows and set(again.columns) == set(table.columns)

    saved = io_nodes.save_json.call(
        inputs={"value": Json(value={"a": [1, 2], "b": "x"})},
        params={"path": "outputs/v.json"},
        ctx=ctx,
    )
    assert json.loads((workspace / saved.path).read_text(encoding="utf-8")) == {
        "a": [1, 2],
        "b": "x",
    }
    assert saved.mime == "application/json"
    with pytest.raises(WorkspacePathError):
        io_nodes.save_json.call(
            inputs={"value": Json(value=1)}, params={"path": "../x.json"}, ctx=ctx
        )
