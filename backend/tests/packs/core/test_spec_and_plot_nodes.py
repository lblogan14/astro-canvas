"""``core.spec.*`` additions (rebin, smooth, air/vac, normalize, snr) and ``core.plot.*``."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from astro_canvas_core.nodes import plot as plot_nodes
from astro_canvas_core.nodes import spec as spec_nodes
from astro_canvas_core.types import Continuum, Figure, Image2D, Spectrum1D, Table

from astro_canvas.sdk import NullContext


def _spec(n: int = 200) -> Spectrum1D:
    wave = np.linspace(4000.0, 4199.0, n)
    flux = 2.0 + 0.5 * np.sin(wave / 5.0)
    return Spectrum1D(wave=wave, flux=flux, error=np.full(n, 0.2), continuum=np.full(n, 2.0))


def test_rebin_averages_and_propagates_errors() -> None:
    spec = _spec(10)
    out = spec_nodes.rebin(spec, factor=3)
    assert len(out) == 3 and out.wave[0] == pytest.approx(4000.0 + 199.0 / 9.0)
    assert out.error is not None and out.error[0] == pytest.approx(0.2 / np.sqrt(3))
    assert out.continuum is not None and out.continuum[0] == 2.0
    assert spec_nodes.rebin(spec, factor=1) is spec and spec_nodes.rebin(spec, factor=50) is spec


def test_smooth_boxcar_and_gaussian_handle_nans() -> None:
    spec = _spec(100)
    flux = spec.flux.copy()
    flux[50] = np.nan
    spec = spec.model_copy(update={"flux": flux})
    box = spec_nodes.smooth(spec, width=3.0, kernel="boxcar")
    assert np.isfinite(box.flux[50]) and abs(box.flux[10] - spec.flux[10]) < 0.2
    assert box.error is not None and box.error[10] == pytest.approx(0.2 / np.sqrt(3), rel=1e-6)
    gauss = spec_nodes.smooth(spec, width=2.0, kernel="gaussian")
    assert np.isfinite(gauss.flux).all() and gauss.flux.std() < spec.flux[np.isfinite(flux)].std()
    assert gauss.wave is spec.wave or np.array_equal(gauss.wave, spec.wave)


def test_air_to_vac_matches_rbcodes_formula_and_round_trips() -> None:
    spec = _spec(50)
    vac = spec_nodes.air_to_vac(spec)
    sigma_sq = (1e4 / spec.wave) ** 2
    factor = 1 + 5.792105e-2 / (238.0185 - sigma_sq) + 1.67918e-3 / (57.362 - sigma_sq)
    np.testing.assert_allclose(vac.wave, spec.wave * factor)
    assert vac.meta["airvac"] == "vac" and spec_nodes.air_to_vac(vac) is vac
    back = spec_nodes.air_to_vac(vac, direction="vac_to_air")
    np.testing.assert_allclose(back.wave, spec.wave)
    uv = Spectrum1D(wave=np.array([1200.0, 1500.0]), flux=np.ones(2))
    np.testing.assert_array_equal(spec_nodes.air_to_vac(uv).wave, uv.wave)  # below 2000 A
    velocity = spec.model_copy(update={"frame": "velocity"})
    with pytest.raises(ValueError, match="velocity"):
        spec_nodes.air_to_vac(velocity)


def test_normalize_uses_port_or_own_continuum() -> None:
    spec = _spec(20)
    own = spec_nodes.normalize(spec)
    np.testing.assert_allclose(own.flux, spec.flux / 2.0)
    assert own.flux_unit == "normalized" and own.error is not None
    np.testing.assert_allclose(own.error, 0.1)
    cont = Continuum(cont=np.full(20, 4.0), method="poly", order=2)
    ported = spec_nodes.normalize(spec, cont)
    np.testing.assert_allclose(ported.flux, spec.flux / 4.0)
    bare = Spectrum1D(wave=spec.wave, flux=spec.flux)
    with pytest.raises(ValueError, match="no continuum"):
        spec_nodes.normalize(bare)
    with pytest.raises(ValueError, match="different lengths"):
        spec_nodes.normalize(bare, Continuum(cont=np.ones(3)))
    zero = spec.model_copy(update={"continuum": np.zeros(20)})
    assert np.isnan(spec_nodes.normalize(zero).flux).all()


def test_snr_median_in_range() -> None:
    spec = _spec(100)
    assert spec_nodes.snr(spec) == pytest.approx(np.median(spec.flux / 0.2))
    window = spec_nodes.snr(spec, lo=4000.0, hi=4010.0)
    keep = (spec.wave >= 4000.0) & (spec.wave <= 4010.0)
    assert window == pytest.approx(np.median(spec.flux[keep] / 0.2))
    with pytest.raises(ValueError, match="no error"):
        spec_nodes.snr(Spectrum1D(wave=spec.wave, flux=spec.flux))
    with pytest.raises(ValueError, match="no valid pixels"):
        spec_nodes.snr(spec, lo=9000.0, hi=9100.0)


def test_plot_spectrum_builds_plotly_traces() -> None:
    spec = _spec(50_000)
    fig = plot_nodes.plot_spectrum(spec, max_points=1000, title="hello")
    assert isinstance(fig, Figure) and fig.kind == "plotly" and fig.plotly is not None
    traces = fig.plotly["data"]
    assert [t["name"] for t in traces] == ["flux", "error", "continuum"]
    assert all(t["type"] == "scattergl" and len(t["x"]) <= 1000 for t in traces)
    assert fig.plotly["layout"]["title"]["text"] == "hello"
    assert "Wavelength" in fig.plotly["layout"]["xaxis"]["title"]["text"]
    plain = plot_nodes.plot_spectrum(spec, show_error=False, show_continuum=False)
    assert len(plain.plotly["data"]) == 1
    velocity = spec.model_copy(update={"frame": "velocity", "wave_unit": "km / s"})
    vel_layout = plot_nodes.plot_spectrum(velocity).plotly["layout"]
    assert "Velocity" in vel_layout["xaxis"]["title"]["text"]
    json.dumps(fig.plotly)  # JSON-safe (NaN-free)


def test_plot_image_scales_and_stretches() -> None:
    rng = np.random.default_rng(3)
    data = rng.normal(10, 1, (300, 200)).astype(np.float32)
    data[0, 0] = np.nan
    image = Image2D(data=data, unit="adu", header={"OBJECT": "field"})
    fig = plot_nodes.plot_image(image, max_size=100)
    trace = fig.plotly["data"][0]
    assert trace["type"] == "heatmap" and len(trace["z"]) == 100 and len(trace["z"][0]) == 67
    assert trace["z"][0][0] is None and 5 < trace["zmin"] < 10 < trace["zmax"] < 15
    assert trace["colorscale"] == "Viridis" and fig.plotly["layout"]["title"]["text"] == "field"
    for scale in ("minmax", "percentile"):
        assert plot_nodes.plot_image(image, scale=scale).plotly is not None
    asinh = plot_nodes.plot_image(image, stretch="asinh", colormap="gray").plotly["data"][0]
    assert asinh["zmin"] == 0.0 and asinh["zmax"] == 1.0 and asinh["colorscale"] == "Greys"
    log = plot_nodes.plot_image(image, stretch="log").plotly["data"][0]
    assert log["zmax"] == 1.0
    json.dumps(fig.plotly)


def test_plot_table_and_export(tmp_path: Path) -> None:
    table = Table(
        columns={"name": np.array(["a", "b"]), "v": np.array([1.0, np.nan])}, units={"v": "Jy"}
    )
    fig = plot_nodes.plot_table(table, rows=1, title="t")
    trace = fig.plotly["data"][0]
    assert trace["type"] == "table" and trace["header"]["values"] == ["name", "v (Jy)"]
    assert trace["cells"]["values"] == [["a"], [1.0]]

    ctx = NullContext(workspace=tmp_path)
    out = plot_nodes.figure_export.call(
        inputs={"figure": fig}, params={"path": "out/f.json"}, ctx=ctx
    )
    assert out.path == "out/f.json"
    assert json.loads((tmp_path / out.path).read_text(encoding="utf-8"))
    html = plot_nodes.figure_export.call(
        inputs={"figure": fig}, params={"path": "out/f.html", "format": "html"}, ctx=ctx
    )
    assert "<html" in (tmp_path / html.path).read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="only PNG figures"):
        plot_nodes.figure_export.call(
            inputs={"figure": fig}, params={"path": "out/f.png", "format": "png"}, ctx=ctx
        )
    png = Figure(kind="png", png=b"\x89PNG")
    saved = plot_nodes.figure_export.call(
        inputs={"figure": png}, params={"path": "out/p.png", "format": "png"}, ctx=ctx
    )
    assert (tmp_path / saved.path).read_bytes() == b"\x89PNG"
    with pytest.raises(ValueError, match="cannot be exported"):
        plot_nodes.figure_export.call(
            inputs={"figure": png}, params={"path": "out/p.json"}, ctx=ctx
        )
