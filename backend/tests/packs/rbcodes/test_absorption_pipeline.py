"""The node pipeline reproduces rbcodes' numbers (reference fixtures) and the template runs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from astro_canvas_core.types import EWMeasurement, Redshift, Spectrum1D, Transition
from astro_canvas_rbcodes import _rb
from astro_canvas_rbcodes.nodes import absorption as A
from astro_canvas_rbcodes.nodes import continuum as C

from astro_canvas.cli import run_headless
from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.engine.graph import compile as compile_workflow
from astro_canvas.sdk import discover
from astro_canvas.settings import Settings

TEMPLATE = (
    Path(__file__).resolve().parents[4]
    / "packs"
    / "rbcodes"
    / "templates"
    / "absorption-line-measurement.acw"
)

# rbcodes' own tests accept 5 % on W and 0.3 dex on log N; the pipeline is the same code path,
# so we hold it to a much tighter bound and keep rbcodes' tolerances as a documented ceiling. The
# residual comes from rb_spec keeping the SDSS wavelength grid in float32 (``10**loglam`` on the
# raw column, then ``wave / (1 + z)`` in float32): pixel widths carry ~1e-4 relative noise, which
# leaves up to ~1e-4 on W_e and N_e. The float64 kernels agree with rbcodes to 1e-9 on identical
# arrays (``test_kernels_match_rbcodes.py``).
REL = 2e-4
VEL_ABS = 0.05


def run_case(sdss1: Spectrum1D, case: dict[str, Any]) -> tuple[EWMeasurement, Any, Spectrum1D]:
    rest = A.set_redshift(sdss1, z=case["zabs"])
    tr = A.set_transition(rest, wrest=case["wrest"], linelist=case["linelist"], method="closest")
    sl = A.slice_spectrum(rest, tr, vmin=case["slice"][0], vmax=case["slice"][1], use_vel=True)
    flat = case["masks"]
    masks = [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
    cont, norm = C.fit(
        sl,
        method="polynomial",
        order=case["order"],
        masks=masks,
        optimize_order=case["optimize"],
        min_order=0,
        max_order=7,
        sigma_clip=True,
        n_sigma=3.0,
        use_weights=case.get("use_weights", False),
    )
    ew = A.compute_ew(norm, tr, vmin=case["ew"][0], vmax=case["ew"][1], snr=case.get("snr", False))
    return ew, cont, sl


@pytest.mark.parametrize(
    "case_id",
    ["sdss1_mgii2796", "sdss1_mgii2803", "sdss1_feii2600_fixed_order", "sdss1_mgii2796_weighted"],
)
def test_pipeline_matches_rbcodes_reference(
    sdss1: Spectrum1D, reference: dict[str, Any], case_id: str
) -> None:
    entry = reference["cases"][case_id]
    case, expected = entry["case"], entry["expected"]
    ew, cont, sl = run_case(sdss1, case)
    assert ew.transition is not None
    assert ew.transition.name == expected["transition"]["name"]
    assert ew.transition.wrest == pytest.approx(expected["transition"]["wrest"])
    assert len(sl) == expected["n_slice"]
    assert float(sl.wave[0]) == pytest.approx(expected["velo_first"], abs=VEL_ABS)
    assert float(sl.wave[-1]) == pytest.approx(expected["velo_last"], abs=VEL_ABS)
    assert cont.order == expected["legendre_order"]
    # rb_spec divides flux by the spectrum median before fitting; the continuum scales with it.
    scale = float(np.nanmedian(sdss1.flux))
    assert float(np.median(cont.cont)) / scale == pytest.approx(expected["cont_median"], rel=REL)
    assert float(cont.cont[0]) / scale == pytest.approx(expected["cont_first"], rel=REL)
    for key in ("W", "W_e", "N", "N_e", "logN", "logN_e"):
        assert getattr(ew, key) == pytest.approx(expected[key], rel=REL, abs=1e-9), key
    for key in ("vel_centroid", "vel_disp", "vel50_err"):
        assert getattr(ew, key) == pytest.approx(expected[key], rel=REL, abs=VEL_ABS), key
    if expected["SNR"] is not None:
        assert pytest.approx(expected["SNR"], rel=REL) == ew.SNR
    else:
        assert ew.SNR is None
    # rbcodes' own tolerances, for the record.
    assert abs(ew.W - expected["W"]) <= 0.05 * abs(expected["W"])
    assert abs(ew.logN - expected["logN"]) <= 0.3


def test_reference_fixture_records_its_provenance(reference: dict[str, Any]) -> None:
    assert reference["rbcodes_version"] == _rb.VENDORED_VERSION
    assert (
        reference["python"].startswith("3.10") and "numpy" in reference and "astropy" in reference
    )


def test_set_redshift_and_slice_bookkeeping(sdss1: Spectrum1D) -> None:
    rest = A.set_redshift(sdss1, z=1.3855)
    assert rest.frame == "rest" and rest.z == 1.3855
    assert float(rest.wave[0]) == pytest.approx(float(sdss1.wave[0]) / 2.3855)
    again = A.set_redshift(rest, z=0.5)
    assert float(again.wave[0]) == pytest.approx(float(sdss1.wave[0]) / 1.5)  # never compounds
    from_port = A.set_redshift(sdss1, z=0.1, redshift=Redshift(z=1.3855))
    np.testing.assert_allclose(from_port.wave, rest.wave)
    assert rest.meta["rb_spec"]["zabs"] == 1.3855 and rest.meta["rbcodes"]["backend"] in (
        "rbcodes",
        "vendored",
    )
    tr = A.set_transition(rest, wrest=2796.35)
    passthrough = A.set_transition(
        rest, wrest=1.0, transition=Transition(name="X", wrest=5.0, fval=1.0)
    )
    assert passthrough.name == "X"
    sl = A.slice_spectrum(rest, tr, vmin=-1500, vmax=1500)
    assert sl.frame == "velocity" and sl.wave_unit == "km / s" and sl.v0_wrest == tr.wrest
    assert sl.wave.min() >= -1500 and sl.wave.max() <= 1500 and sl.z == 1.3855
    block = sl.meta["rb_spec"]
    assert block["slice_spec_lam_min"] == -1500 and block["slice_spec_method"] is True
    assert block["flux_scale"] == pytest.approx(float(np.nanmedian(sdss1.flux)))
    assert A.slice_bounds(sl) == (-1500.0, 1500.0)
    by_wave = A.slice_spectrum(rest, tr, vmin=2790.0, vmax=2800.0, use_vel=False)
    assert 0 < len(by_wave) < len(sl) and by_wave.frame == "velocity"
    with pytest.raises(ValueError, match="No data points"):
        A.slice_spectrum(rest, tr, vmin=5e5, vmax=6e5)
    with pytest.raises(ValueError, match="velocity"):
        A.set_redshift(sl, z=1.0)
    with pytest.raises(ValueError, match="no redshift"):
        A.slice_spectrum(sdss1.model_copy(update={"z": None}), tr)


def test_compute_ew_options_and_doublet_figure(sdss1: Spectrum1D) -> None:
    rest = A.set_redshift(sdss1, z=1.3855)
    tr = A.set_transition(rest, wrest=2796.35)
    sl = A.slice_spectrum(rest, tr, vmin=-1500, vmax=1500)
    _, norm = C.fit(sl, masks=[(-300, 250), (500, 1000)])
    base = A.compute_ew(norm, tr)
    off = A.compute_ew(norm, tr, saturation="off")
    custom = A.compute_ew(norm, tr, saturation="custom", sat_threshold=0.5)
    assert off.W != custom.W and base.saturated is False and base.flag == 0
    assert custom.saturated is True and custom.flag == 1
    with_snr = A.compute_ew(norm, tr, snr=True, binsize=2)
    assert with_snr.SNR is not None and with_snr.SNR > 5
    with pytest.raises(ValueError, match="error array"):
        A.compute_ew(norm.model_copy(update={"error": None}), tr)
    # Non-detection: a flat unity spectrum gives log N = 0 and log N_e as the limit.
    flat = norm.model_copy(update={"flux": np.ones_like(norm.flux)})
    none = A.compute_ew(flat, tr)
    assert none.logN == 0.0 and none.logN_e is not None and none.logN_e > 0
    fig = A.doublet_check(norm, lam1=2796.35, lam2=2803.53)
    assert fig.kind == "plotly" and fig.plotly is not None
    assert len(fig.plotly["data"]) == 4 and "MgII 2796" in fig.plotly["layout"]["title"]["text"]


def test_template_compiles_and_runs_headless(tmp_path: Path, workspace: Path) -> None:
    registry = discover().registry
    doc = WorkflowDoc.model_validate_json(TEMPLATE.read_text(encoding="utf-8"))
    graph = compile_workflow(doc, registry)
    assert not hasattr(graph, "node_errors") or not graph.node_errors, graph
    settings = Settings(
        workspace=workspace, config_dir=tmp_path / "config", process_pool=False, auth=False
    )
    summary = asyncio.run(run_headless(settings, TEMPLATE, None))
    assert summary["status"] == "done", summary
    states = {k: v["state"] for k, v in summary["nodes"].items()}
    assert states == {k: "done" for k in states}, states
    saved = workspace / "outputs" / "sdss1_MgII2796_z1.3855.json"
    assert saved.is_file()
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["trans"] == "MgII 2796" and data["W"] == pytest.approx(2.07114, abs=2e-5)
    assert data["continuum_masks"] == [-300.0, 250.0, 500.0, 1000.0]
