"""Viewport-aware summaries (design 6.4): spectra, images, cubes, tables and figures."""

from __future__ import annotations

import base64
import time

import numpy as np
import pyarrow as pa
import pytest
from astro_canvas_core import types as T

from astro_canvas.engine.events import decode_frame, output_frame
from astro_canvas.sdk import decimate, decimate_indices


def _spectrum(n: int) -> T.Spectrum1D:
    wave = np.linspace(3500.0, 9500.0, n)
    flux = np.sin(wave / 40.0) + 0.01 * np.arange(n) / n
    return T.Spectrum1D(wave=wave, flux=flux, error=np.full(n, 0.1), continuum=np.ones(n))


def test_spectrum_summary_aligns_every_series_and_honours_viewport() -> None:
    spec = _spectrum(50_000)
    summary = spec.summary()
    assert summary["n"] == 50_000 and summary["n_view"] == 50_000
    assert len(summary["wave"]) <= 4000 and len(summary["wave"]) == len(summary["flux"])
    assert len(summary["error"]) == len(summary["continuum"]) == len(summary["wave"])
    assert summary["range"] == [3500.0, 9500.0] and summary["wave"][0] == 3500.0
    assert summary["wave"][-1] == 9500.0  # extrema kept by MinMaxLTTB
    assert summary["wave_unit"] == "Angstrom" and summary["frame"] == "observed"

    zoomed = spec.summary({"lo": 4000, "hi": 4010, "n_out": 100})
    assert zoomed["n_view"] < 200 and len(zoomed["wave"]) <= 100
    assert min(zoomed["wave"]) >= 4000 and max(zoomed["wave"]) <= 4010
    assert spec.summary({"n_out": "bogus"})["n"] == 50_000  # bad viewport values fall back
    capped = spec.summary({"n_out": 10**9})
    assert len(capped["wave"]) <= 20_000
    assert "error" not in T.Spectrum1D(wave=spec.wave, flux=spec.flux).summary()


def test_one_million_point_summary_is_fast() -> None:
    spec = _spectrum(1_000_000)
    start = time.perf_counter()
    summary = spec.summary({"n_out": 4000})
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert len(summary["wave"]) <= 4000
    # Budget from the phase brief: preview latency < 300 ms end-to-end; the server side must be
    # well under it (typically 20-60 ms on a laptop; CI runners are slower).
    assert elapsed_ms < 250, f"summary took {elapsed_ms:.0f} ms"
    start = time.perf_counter()
    frame = output_frame("n", "out", spec)
    encode_ms = (time.perf_counter() - start) * 1000
    assert encode_ms < 500, f"binary frame took {encode_ms:.0f} ms"
    msg_type, header, payload = decode_frame(frame)
    assert msg_type == 1 and header["data"]["wave_unit"] == "Angstrom"
    arrays = {a["name"]: a for a in header["arrays"]}
    assert arrays["wave"]["dtype"] == "f8" and arrays["wave"]["shape"] == [1_000_000]
    assert len(payload) == sum(a["nbytes"] for a in header["arrays"])


def test_decimate_indices_and_decimate_agree() -> None:
    x = np.linspace(0, 1, 10_000)
    y = np.sin(x * 50)
    idx = decimate_indices(x, y, n_out=200)
    xs, ys = decimate(x, y, n_out=200)
    np.testing.assert_array_equal(xs, x[idx])
    np.testing.assert_array_equal(ys, y[idx])
    assert idx.dtype == np.intp and len(idx) <= 200
    assert decimate_indices(x[:10], y[:10], n_out=200).tolist() == list(range(10))
    with pytest.raises(ValueError, match="1-d"):
        decimate_indices(np.zeros((2, 2)), np.zeros(4))


def test_image_summary_tile_zscale_and_viewport_size() -> None:
    rng = np.random.default_rng(0)
    data = rng.normal(100.0, 5.0, (600, 900)).astype(np.float32)
    data[10, 10] = np.nan
    data[300, 450] = 5000.0
    image = T.Image2D(data=data, unit="adu", header={"OBJECT": "blob"})
    summary = image.summary()
    tile = summary["tile"]
    assert summary["shape"] == [600, 900] and summary["object"] == "blob"
    assert tile["step"] == 8 and tile["width"] == 113 and tile["height"] == 75
    raw = base64.b64decode(tile["b64"])
    assert len(raw) == tile["width"] * tile["height"] * 4
    decoded = np.frombuffer(raw, dtype="<f4").reshape(tile["height"], tile["width"])
    np.testing.assert_array_equal(decoded, data[::8, ::8])
    lo, hi = tile["zscale"]
    assert 70 < lo < 100 < hi < 130  # zscale ignores the hot pixel
    assert tile["minmax"][0] < 100 and tile["percentile"][1] < 200
    big = image.summary({"n_out": 1024})["tile"]
    assert big["step"] == 1 and big["width"] == 900
    small = image.summary({"n_out": 16})["tile"]
    assert small["width"] <= 16 and small["height"] <= 16
    assert T.zscale_limits(np.array([np.nan, np.nan])) == (0.0, 1.0)
    assert T.zscale_limits(np.array([3.0, 3.0, 3.0])) == (3.0, 3.0)
    with pytest.raises(ValueError, match="2-d"):
        T.image_tile(np.zeros(5), 8)


def test_cube_summary_white_light_and_band() -> None:
    nz, ny, nx = 40, 12, 10
    wave = 5000.0 + np.arange(nz)
    flux = np.zeros((nz, ny, nx), dtype=np.float32)
    flux[20, 6, 4] = 100.0  # an emission line in one spaxel at 5020 A
    flux[:, 2, 2] = 1.0  # a continuum source
    cube = T.Cube3D(flux=flux, wave=wave, instrument="KCWI", header={"_WAVEUNIT": "Angstrom"})
    summary = cube.summary()
    assert summary["shape"] == [nz, ny, nx] and summary["instrument"] == "KCWI"
    assert summary["wave_range"] == [5000.0, 5039.0] and summary["has_var"] is False
    tile = np.frombuffer(base64.b64decode(summary["tile"]["b64"]), dtype="<f4").reshape(ny, nx)
    assert tile[2, 2] == pytest.approx(1.0) and tile[6, 4] == pytest.approx(100.0 / nz)
    assert len(summary["spectrum"]["wave"]) == nz and summary["spectrum"]["flux"][20] == 101.0
    band = cube.summary({"lo": 5019, "hi": 5021})
    band_tile = np.frombuffer(base64.b64decode(band["tile"]["b64"]), dtype="<f4").reshape(ny, nx)
    assert band_tile[6, 4] == pytest.approx(100.0 / 3) and band["band"] == [5019.0, 5021.0]
    empty_band = cube.white_light(9000.0, 9100.0)  # falls back to the whole cube
    assert empty_band[2, 2] == pytest.approx(1.0)


def test_table_summary_has_json_head_and_arrow_head() -> None:
    table = T.Table(
        columns={
            "name": np.array(["a", "b", "c"]),
            "value": np.array([1.5, np.nan, 3.0]),
            "count": np.array([1, 2, 3]),
        },
        units={"value": "Jy"},
    )
    summary = table.summary({"rows": 2})
    assert summary["n_rows"] == 3 and summary["columns"] == ["name", "value", "count"]
    assert summary["head"]["value"] == [1.5, None] and summary["head"]["name"] == ["a", "b"]
    assert summary["dtypes"]["count"].endswith("i8")
    arrow = pa.ipc.open_stream(pa.py_buffer(base64.b64decode(summary["arrow_b64"]))).read_all()
    assert arrow.num_rows == 2 and arrow.column("name").to_pylist() == ["a", "b"]
    assert table.summary()["head"]["count"] == [1, 2, 3]


def test_figure_summary_inlines_small_payloads() -> None:
    fig = T.Figure(kind="plotly", plotly={"data": [{"x": [1, 2], "y": [3, 4]}], "layout": {}})
    summary = fig.summary()
    assert summary["kind"] == "plotly" and summary["plotly"]["data"][0]["x"] == [1, 2]
    huge = T.Figure(kind="plotly", plotly={"data": [{"x": list(range(200_000))}]})
    assert "plotly" not in huge.summary() and huge.summary()["size"] > 400_000
    png = T.Figure(kind="png", png=b"\x89PNG\r\n")
    assert base64.b64decode(png.summary()["png_b64"]) == b"\x89PNG\r\n"
