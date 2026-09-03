"""``save_rbspec_json`` writes the ``rb_spec.save_slice`` schema; ``load_rbspec_json`` reads it."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from astro_canvas_core.types import EWMeasurement, Spectrum1D
from astro_canvas_rbcodes.nodes import absorption as A
from astro_canvas_rbcodes.nodes import continuum as C
from astro_canvas_rbcodes.nodes import io as IO

from astro_canvas.sdk import NullContext
from tests.packs.rbcodes.conftest import requires_rbcodes

SAVE_SLICE_KEYS = {
    "zabs",
    "linelist",
    "line_sel_flag",
    "trans",
    "fval",
    "trans_wave",
    "vmin",
    "vmax",
    "W",
    "W_e",
    "N",
    "N_e",
    "logN",
    "logN_e",
    "vel_centroid",
    "vel_disp",
    "vel50_err",
    "SNR",
    "wave_slice",
    "flux_slice",
    "error_slice",
    "velo",
    "cont",
    "fnorm",
    "enorm",
    "Tau",
    "slice_spec_lam_min",
    "slice_spec_lam_max",
    "slice_spec_method",
    "continuum_masks",
    "continuum_mask_wavelengths",
    "continuum_fit_params",
    "metadata",
}


@pytest.fixture
def pipeline(sdss1: Spectrum1D) -> tuple[Spectrum1D, Spectrum1D, object, EWMeasurement]:
    rest = A.set_redshift(sdss1, z=1.3855)
    tr = A.set_transition(rest, wrest=2796.35)
    sl = A.slice_spectrum(rest, tr, vmin=-1500, vmax=1500)
    cont, norm = C.fit(sl, masks=[(-300, 250), (500, 1000)])
    ew = A.compute_ew(norm, tr)
    return sl, norm, cont, ew


def test_saved_file_has_the_save_slice_schema_and_rbspec_scaling(
    pipeline: tuple[Spectrum1D, Spectrum1D, object, EWMeasurement],
    ctx: NullContext,
    workspace: Path,
    sdss1: Spectrum1D,
) -> None:
    sl, norm, cont, ew = pipeline
    out = IO.save_rbspec_json(norm, cont, ew, path="outputs/mgii.json", linelist="atom", ctx=ctx)  # type: ignore[arg-type]
    target = workspace / "outputs" / "mgii.json"
    assert out.path == "outputs/mgii.json" and target.is_file() and out.size > 1000
    data = json.loads(target.read_text(encoding="utf-8"))
    assert set(data) == SAVE_SLICE_KEYS
    assert data["trans"] == "MgII 2796" and data["fval"] == pytest.approx(0.6123)
    assert (
        data["zabs"] == 1.3855 and data["linelist"] == "atom" and data["line_sel_flag"] == "closest"
    )
    assert data["W"] == ew.W and data["logN"] == ew.logN and data["SNR"] == -99
    n = len(sl)
    for key in ("wave_slice", "flux_slice", "error_slice", "velo", "cont", "fnorm", "enorm", "Tau"):
        assert len(data[key]) == n, key
    assert data["continuum_masks"] == [-300.0, 250.0, 500.0, 1000.0]
    assert len(data["continuum_mask_wavelengths"]) == 4
    assert data["continuum_fit_params"]["legendre_order"] == 1
    assert data["continuum_fit_params"]["method"] == "polynomial"
    assert data["slice_spec_lam_min"] == -1500 and data["slice_spec_method"] is True
    assert data["metadata"]["rbcodes_version"] and "field_descriptions" in data["metadata"]
    assert data["metadata"]["astro_canvas"]["backend"] in ("rbcodes", "vendored")
    # rb_spec divides by the spectrum's median flux at load time: flux_slice is in those units.
    scale = float(np.nanmedian(sdss1.flux))
    np.testing.assert_allclose(np.asarray(data["flux_slice"]) * scale, sl.flux, rtol=1e-9)
    np.testing.assert_allclose(np.asarray(data["fnorm"]), norm.flux, rtol=1e-12)
    np.testing.assert_allclose(
        np.asarray(data["Tau"]), -np.log(np.clip(norm.flux, np.finfo(float).eps, None))
    )
    np.testing.assert_allclose(np.asarray(data["velo"]), sl.wave, rtol=1e-12)


def test_load_roundtrips_the_saved_measurement(
    pipeline: tuple[Spectrum1D, Spectrum1D, object, EWMeasurement], ctx: NullContext
) -> None:
    sl, norm, cont, ew = pipeline
    IO.save_rbspec_json(norm, cont, ew, path="outputs/rt.json", ctx=ctx)  # type: ignore[arg-type]
    spec, normalized, continuum, measurement = IO.load_rbspec_json(path="outputs/rt.json", ctx=ctx)
    assert (
        spec.frame == "velocity" and spec.v0_wrest == pytest.approx(2796.352) and spec.z == 1.3855
    )
    assert spec.continuum is not None and len(spec) == len(sl)
    np.testing.assert_allclose(normalized.flux, norm.flux, rtol=1e-12)
    assert normalized.flux_unit == "normalized"
    assert continuum.masks == [(-300.0, 250.0), (500.0, 1000.0)] and continuum.order == 1
    assert pytest.approx(ew.W) == measurement.W and measurement.logN == pytest.approx(ew.logN)
    assert measurement.transition is not None and measurement.transition.name == "MgII 2796"
    assert measurement.SNR is None and measurement.vmin == -200.0
    assert spec.meta["rb_spec"]["linelist"] == "atom"
    with pytest.raises(ValueError, match="choose a file"):
        IO.load_rbspec_json(path="", ctx=ctx)


def test_load_rejects_other_json(ctx: NullContext, workspace: Path) -> None:
    (workspace / "other.json").write_text(
        json.dumps({"wave": [1, 2], "flux": [1, 1]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="not an rb_spec JSON"):
        IO.load_rbspec_json(path="other.json", ctx=ctx)


def test_core_loader_reads_the_saved_file(
    pipeline: tuple[Spectrum1D, Spectrum1D, object, EWMeasurement], ctx: NullContext
) -> None:
    from astro_canvas_core.nodes.io import load_spectrum

    sl, norm, cont, ew = pipeline
    IO.save_rbspec_json(norm, cont, ew, path="outputs/core.json", ctx=ctx)  # type: ignore[arg-type]
    loaded = load_spectrum(path="outputs/core.json", ctx=ctx)
    assert len(loaded) == len(sl) and loaded.meta.get("rb_spec_analysis", {}).get(
        "W"
    ) == pytest.approx(ew.W)


@requires_rbcodes
def test_rbcodes_load_rb_spec_object_opens_the_file(
    pipeline: tuple[Spectrum1D, Spectrum1D, object, EWMeasurement],
    ctx: NullContext,
    workspace: Path,
) -> None:
    from rbcodes.GUIs.rb_spec import load_rb_spec_object

    sl, norm, cont, ew = pipeline
    IO.save_rbspec_json(norm, cont, ew, path="outputs/rb.json", ctx=ctx)  # type: ignore[arg-type]
    obj = load_rb_spec_object(str(workspace / "outputs" / "rb.json"), verbose=False)
    assert obj is not None and obj.trans == "MgII 2796"
    assert pytest.approx(ew.W) == obj.W and len(obj.wave) == len(sl)
    assert list(obj.continuum_masks) == [-300.0, 250.0, 500.0, 1000.0]
    # And rbcodes recomputes the same equivalent width from the stored arrays.
    obj.linelist = "atom"
    obj.compute_EW(obj.trans_wave, vmin=-200.0, vmax=200.0)
    assert pytest.approx(ew.W, rel=1e-9) == obj.W
