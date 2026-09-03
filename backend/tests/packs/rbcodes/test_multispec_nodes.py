"""``rbcodes.multispec.*`` nodes: the viewer's catalogues, the adapters and the velocity stack.

The viewer node is interactive: its parameters hold the edited catalogues and its outputs are
those catalogues as tables, so these tests exercise the seed -> edit -> output path the
``multispec-viewer`` editor drives.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
from astro_canvas_core.nodes.io import load_spectrum
from astro_canvas_core.nodes.list import collect
from astro_canvas_core.types import LineList, Redshift, Spectrum1D, SpectrumCollection, Table
from astro_canvas_rbcodes.kernels import multispec_io as M
from astro_canvas_rbcodes.nodes import multispec as MS
from astro_canvas_rbcodes.nodes import zfind as Z
from astro_canvas_rbcodes.nodes.lines import line_list
from astro_canvas_rbcodes.types import (
    AbsorberCandidate,
    AbsorberResult,
    AbsorberSystem,
    IdentifiedLine,
    MultispecView,
)

from astro_canvas.cli import run_headless
from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.engine.graph import compile as compile_workflow
from astro_canvas.sdk import NullContext, discover
from astro_canvas.settings import Settings
from tests.packs.rbcodes.conftest import SAMPLES

TEMPLATE = (
    Path(__file__).resolve().parents[4]
    / "packs"
    / "rbcodes"
    / "templates"
    / "multi-spectrum-viewer.acw"
)
MGII_Z = 1.3855


@pytest.fixture(scope="module")
def three() -> SpectrumCollection:
    ctx = NullContext(workspace=SAMPLES)
    return collect(
        load_spectrum(path="sdss1.fits", ctx=ctx),
        load_spectrum(path="sdss2.fits", ctx=ctx),
        load_spectrum(path="spec-0398-51789-0282.fits", ctx=ctx),
    )


# --- registration ------------------------------------------------------------------------------


def test_the_pack_registers_the_multispec_nodes() -> None:
    registry = discover().registry
    ids = {spec.id for spec in registry.list() if spec.id.startswith("rbcodes.multispec.")}
    assert ids == {
        "rbcodes.multispec.absorber_catalog",
        "rbcodes.multispec.export_linelist",
        "rbcodes.multispec.import_linelist",
        "rbcodes.multispec.quick_fit",
        "rbcodes.multispec.reconcile_linelists",
        "rbcodes.multispec.view",
        "rbcodes.multispec.vstack",
    }
    view = registry.spec("rbcodes.multispec.view")
    assert view.editor == "multispec-viewer"
    assert [o.name for o in view.outputs] == ["absorbers", "identified_lines", "view"]
    assert [i.name for i in view.inputs] == [
        "spectra",
        "absorber_seed",
        "line_seed",
        "extra_lines",
        "extra_lines_2",
        "redshift",
    ]
    params = {p.name: p for p in view.params}
    assert params["catalog"].widget == "json" and params["identifications"].widget == "json"
    assert params["z"].widget == "redshift"
    assert set(params["linelist"].json_schema["enum"]) == set(M.LINE_LIST_OPTIONS)
    assert registry.types.spec("rbcodes.MultispecView").summary_renderer == "multispec-thumb"


# --- the viewer node ---------------------------------------------------------------------------


def test_view_stacks_the_panels_and_labels_them(three: SpectrumCollection) -> None:
    absorbers, lines, view = MS.view(three, z=MGII_Z)

    assert isinstance(view, MultispecView) and len(view) == 3
    assert view.labels == ["sdss1.fits", "sdss2.fits", "spec-0398-51789-0282.fits"]
    assert view.z == MGII_Z and view.linelist == "LLS"
    assert absorbers.n_rows == 0 and lines.n_rows == 0
    assert list(absorbers.columns) == ["Zabs", "LineList", "Color", "Visible", "Label"]
    assert list(lines.columns) == ["Name", "Wave_obs", "Zabs", "Wave_rest", "Spectrum"]
    assert view.meta["source"] == "rbcodes.multispec.view"
    window = view.wave_range()
    assert window is not None and window[0] < window[1]


def test_view_needs_a_spectrum() -> None:
    with pytest.raises(ValueError, match="at least one spectrum"):
        MS.view(SpectrumCollection(items=[]))


def test_view_crops_and_smooths_the_panels(three: SpectrumCollection) -> None:
    display = MS.MultispecDisplay(wave_min=4000.0, wave_max=5000.0, smooth_pixels=5)
    _absorbers, _lines, view = MS.view(three, display=display)

    for panel in view.spectra:
        assert panel.wave[0] >= 4000.0 and panel.wave[-1] <= 5000.0
    raw = three.items[0]
    inside = np.count_nonzero((raw.wave >= 4000.0) & (raw.wave <= 5000.0))
    assert len(view.spectra[0]) == inside
    # Smoothing lowers the pixel-to-pixel scatter without moving the mean.
    cropped = raw.flux[(raw.wave >= 4000.0) & (raw.wave <= 5000.0)]
    assert np.std(np.diff(view.spectra[0].flux)) < np.std(np.diff(cropped))
    assert view.meta["display"]["smooth_pixels"] == 5


def test_an_empty_display_window_is_an_error(three: SpectrumCollection) -> None:
    with pytest.raises(ValueError, match="excludes every pixel"):
        MS.view(three, display=MS.MultispecDisplay(wave_min=1.0, wave_max=2.0))


def test_view_seeds_from_the_input_tables_and_the_edits_win(three: SpectrumCollection) -> None:
    seed = MS.absorbers_table([AbsorberSystem(zabs=0.5, linelist="DLA", color="orange")])
    line_seed = MS.identified_table(
        [IdentifiedLine(name="HI 1215", wave_obs=4000.0, zabs=2.29, spectrum="sdss1.fits")]
    )
    absorbers, lines, view = MS.view(three, absorber_seed=seed, line_seed=line_seed)
    assert absorbers.columns["Zabs"].tolist() == [0.5]
    assert lines.columns["Name"].tolist() == ["HI 1215"]
    assert lines.columns["Wave_rest"][0] == pytest.approx(4000.0 / 3.29)

    edited, edited_lines, _view = MS.view(
        three,
        absorber_seed=seed,
        line_seed=line_seed,
        catalog=[AbsorberSystem(zabs=MGII_Z, linelist="LLS", color="sky_blue")],
        identifications=[IdentifiedLine(name="MgII 2796", wave_obs=6670.7, zabs=MGII_Z)],
    )
    assert edited.columns["Zabs"].tolist() == [MGII_Z]
    assert edited_lines.columns["Name"].tolist() == ["MgII 2796"]
    assert view.absorbers[0].linelist == "DLA"


def test_a_connected_redshift_overrides_the_parameter(three: SpectrumCollection) -> None:
    _absorbers, _lines, view = MS.view(
        three, redshift=Redshift(z=MGII_Z, method="rank", source="test"), z=0.0
    )
    assert view.z == MGII_Z


def test_extra_line_lists_are_recorded(three: SpectrumCollection) -> None:
    _a, _l, view = MS.view(
        three, extra_lines=line_list(name="DLA"), extra_lines_2=Z.curated_linelist(name="zfind_qso")
    )
    assert view.meta["extra_linelists"] == ["DLA", "zfind_qso"]


def test_view_summary_decimates_the_panels(three: SpectrumCollection) -> None:
    _a, _l, view = MS.view(
        three,
        z=MGII_Z,
        catalog=[AbsorberSystem(zabs=MGII_Z)],
        identifications=[IdentifiedLine(name="MgII 2796", wave_obs=6670.7, zabs=MGII_Z)],
    )
    summary = view.summary({"n_out": 128, "max_panels": 2})
    assert summary["type"] == "rbcodes.MultispecView"
    assert summary["count"] == 3 and len(summary["panels"]) == 2
    assert all(len(panel["wave"]) <= 128 for panel in summary["panels"])
    assert summary["absorbers"] == [
        {"zabs": MGII_Z, "linelist": "LLS", "color": "sky_blue", "visible": True, "label": ""}
    ]
    assert summary["identified"][0]["name"] == "MgII 2796"
    assert summary["identified"][0]["wave_rest"] == pytest.approx(6670.7 / (1 + MGII_Z))
    assert summary["range"] is not None
    assert json.dumps(summary)  # JSON-safe: no NaN tokens


def test_labels_match_the_panels() -> None:
    with pytest.raises(ValueError, match="labels must match"):
        MultispecView(spectra=[], labels=["only one"])


# --- the absorber adapter ------------------------------------------------------------------------


def test_absorber_catalog_normalises_the_zfind_shape() -> None:
    result = AbsorberResult(
        z_array=np.linspace(0.0, 2.0, 8),
        significance_curve=np.zeros(8),
        candidates=[
            AbsorberCandidate(z=MGII_Z, significance=7.5, n_lines=4, linelist_name="zfind_igm"),
            AbsorberCandidate(z=0.9, significance=5.0, n_lines=3, linelist_name="zfind_igm"),
        ],
    )
    zfind_catalog = Z.absorbers_to_catalog(result)
    assert list(zfind_catalog.columns) == [
        "zabs",
        "name",
        "label",
        "significance",
        "n_lines",
        "lines_matched",
    ]

    catalog = MS.absorber_catalog(zfind_catalog, linelist="LLS")
    assert catalog.columns["Zabs"].tolist() == [MGII_Z, 0.9]
    # 'zfind_igm' is not one of rb_multispec's options, so the fallback list is used.
    assert catalog.columns["LineList"].tolist() == ["LLS", "LLS"]
    assert catalog.columns["Color"].tolist() == list(M.ABSORBER_COLORS[:2])
    assert catalog.columns["Visible"].tolist() == [True, True]
    assert catalog.columns["Label"][0] == f"z={MGII_Z:.4f} (zfind_igm)"


def test_absorber_catalog_keeps_a_known_line_list() -> None:
    table = Table(
        columns={
            "Zabs": np.array([0.5]),
            "LineList": np.array(["DLA"], dtype=np.str_),
            "Color": np.array(["cyan"], dtype=np.str_),
        }
    )
    catalog = MS.absorber_catalog(table, linelist="LLS", visible=False)
    assert catalog.columns["LineList"].tolist() == ["DLA"]
    assert catalog.columns["Color"].tolist() == ["cyan"]
    assert catalog.columns["Visible"].tolist() == [False]


def test_the_viewer_consumes_the_zfind_catalog_directly(three: SpectrumCollection) -> None:
    result = AbsorberResult(
        z_array=np.linspace(0.0, 2.0, 8),
        significance_curve=np.zeros(8),
        candidates=[
            AbsorberCandidate(z=MGII_Z, significance=7.5, n_lines=4, linelist_name="zfind_igm")
        ],
    )
    absorbers, _lines, view = MS.view(three, absorber_seed=Z.absorbers_to_catalog(result))
    assert absorbers.columns["Zabs"].tolist() == [MGII_Z]
    assert view.absorbers[0].label == f"z={MGII_Z:.4f} (zfind_igm)"


def test_a_catalogue_without_a_redshift_column_is_refused() -> None:
    table = Table(columns={"name": np.array(["x"], dtype=np.str_)})
    with pytest.raises(ValueError, match="needs a 'Zabs' column"):
        MS.absorbers_from_table(table)


def test_a_line_table_without_the_required_columns_is_refused() -> None:
    table = Table(columns={"Name": np.array(["x"], dtype=np.str_)})
    with pytest.raises(ValueError, match="needs 'Name', 'Wave_obs' and 'Zabs'"):
        MS.identified_from_table(table)


def test_empty_tables_convert_to_empty_lists() -> None:
    assert MS.absorbers_from_table(None) == [] and MS.identified_from_table(None) == []
    empty = MS.identified_table([])
    assert MS.identified_from_table(empty) == []


# --- the velocity stack ---------------------------------------------------------------------------


def test_vstack_makes_one_velocity_panel_per_transition(sdss1: Spectrum1D) -> None:
    stack = MS.vstack(sdss1, line_list(name="LLS"), z=MGII_Z, vmin=-800.0, vmax=800.0)

    assert len(stack) > 5 and len(stack.labels) == len(stack)
    first = stack.items[0]
    assert first.frame == "velocity" and first.wave_unit == "km / s"
    assert first.z == MGII_Z and first.v0_wrest is not None
    assert first.wave.min() >= -800.0 and first.wave.max() <= 800.0
    assert stack.labels[0].startswith(first.meta["transition"])
    # Panels are ordered by rest wavelength.
    rest = [item.v0_wrest for item in stack.items]
    assert rest == sorted(rest)
    # The observed centre of each panel really is inside the spectrum.
    for item in stack.items:
        centre = (item.v0_wrest or 0.0) * (1 + MGII_Z)
        assert sdss1.wave.min() < centre < sdss1.wave.max()


def test_vstack_honours_max_panels(sdss1: Spectrum1D) -> None:
    stack = MS.vstack(sdss1, line_list(name="LLS"), z=MGII_Z, max_panels=3)
    assert len(stack) == 3


def test_vstack_uses_a_connected_redshift(sdss1: Spectrum1D) -> None:
    stack = MS.vstack(
        sdss1,
        line_list(name="LLS"),
        redshift=Redshift(z=MGII_Z, method="rank", source="test"),
        z=0.0,
    )
    assert stack.items[0].z == MGII_Z


def test_vstack_errors(sdss1: Spectrum1D) -> None:
    with pytest.raises(ValueError, match="vmin must be smaller"):
        MS.vstack(sdss1, line_list(name="LLS"), vmin=100.0, vmax=-100.0)
    with pytest.raises(ValueError, match="no transition"):
        MS.vstack(
            sdss1, LineList(wrest=np.array([10.0]), name=np.array(["X"]), fval=np.array([1.0]))
        )
    velocity = Spectrum1D(
        wave=np.linspace(-500.0, 500.0, 64), flux=np.ones(64), frame="velocity", v0_wrest=1215.67
    )
    with pytest.raises(ValueError, match="not a velocity slice"):
        MS.vstack(velocity, line_list(name="LLS"))


# --- the template ---------------------------------------------------------------------------------


def test_template_compiles_and_runs_headless(tmp_path: Path) -> None:
    doc = WorkflowDoc.model_validate_json(TEMPLATE.read_text(encoding="utf-8"))
    graph = compile_workflow(doc, discover().registry)
    assert not isinstance(graph, dict), graph

    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = Settings(
        workspace=workspace, config_dir=workspace / "config", process_pool=False, auth=False
    )
    summary = asyncio.run(run_headless(settings, TEMPLATE, None))
    assert summary["status"] == "done", summary
    states = {node: info["state"] for node, info in summary["nodes"].items()}
    assert all(state == "done" for state in states.values()), states
    written = workspace / "outputs" / "multispec-lines.json"
    assert written.is_file()
    document = json.loads(written.read_text(encoding="utf-8"))
    assert document["metadata"]["application_name"] == "MultispecViewer"
    assert len(document["line_list"]) >= 2 and len(document["absorbers"]) >= 1
