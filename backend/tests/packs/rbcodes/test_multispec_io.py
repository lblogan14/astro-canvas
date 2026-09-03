"""rb_multispec's three line-list formats: round trips, reconciliation and upstream interop.

The interop test is the phase-07 acceptance item: files written by
``rbcodes.multispec.export_linelist`` must open in ``rbcodes.GUIs.multispecviewer.io_manager``.
``IOManager`` is a singleton whose ``show_message`` prints when no Qt message box is attached, so
the test monkeypatches the two message methods instead of building a widget.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from astro_canvas_core.types import Table
from astro_canvas_rbcodes.kernels import multispec_io as M
from astro_canvas_rbcodes.nodes import multispec as MS
from astro_canvas_rbcodes.types import AbsorberSystem, IdentifiedLine

from astro_canvas.sdk import NullContext
from tests.packs.rbcodes.conftest import requires_rbcodes

LINES = [
    IdentifiedLine(name="MgII 2796", wave_obs=6670.7025, zabs=1.3855, spectrum="sdss1.fits"),
    IdentifiedLine(name="MgII 2803", wave_obs=6687.8232, zabs=1.3855, spectrum="sdss1.fits"),
    IdentifiedLine(name="CIV 1548", wave_obs=6216.5, zabs=3.0148, spectrum="sdss2.fits"),
]
SYSTEMS = [
    AbsorberSystem(zabs=1.3855, linelist="LLS", color="sky_blue"),
    AbsorberSystem(zabs=3.0148, linelist="DLA", color="orange", visible=False),
]


@pytest.fixture
def lines_table() -> Table:
    return MS.identified_table(LINES)


@pytest.fixture
def absorbers_table() -> Table:
    return MS.absorbers_table(SYSTEMS)


# --- formats -------------------------------------------------------------------------------------


def test_txt_is_the_fixed_width_multispec_table(lines_table: Table) -> None:
    text = M.format_line_list(MS.line_rows(lines_table), "txt")
    header, rule, first, *_ = text.splitlines()
    assert header.startswith("Name") and header[31:39] == "Wave_obs"
    assert rule == "-" * 55
    assert first.startswith("MgII 2796") and first[31:41].strip() == "6670.7025"
    assert first.split()[-1] == "1.385500"


def test_csv_keeps_the_extra_columns(lines_table: Table) -> None:
    text = M.format_line_list(MS.line_rows(lines_table), "csv")
    header = text.splitlines()[0].split(",")
    assert header[:3] == ["Name", "Wave_obs", "Zabs"]
    assert set(header) == {"Name", "Wave_obs", "Zabs", "Wave_rest", "Spectrum"}


def test_json_is_the_multispecviewer_document(lines_table: Table, absorbers_table: Table) -> None:
    document = json.loads(
        M.format_line_list(
            MS.line_rows(lines_table),
            "json",
            absorbers=MS.absorber_rows(absorbers_table),
            spectrum_files=["sdss1.fits", "sdss2.fits"],
            user_comment="phase 07",
        )
    )
    assert set(document) == {"line_list", "absorbers", "spectrum_files", "metadata"}
    assert document["metadata"]["application_name"] == "MultispecViewer"
    assert document["metadata"]["version"] == M.FORMAT_VERSION
    assert document["metadata"]["user_comment"] == "phase 07"
    assert set(document["metadata"]["system_info"]) == {"platform", "python_version", "username"}
    assert [row["Name"] for row in document["line_list"]] == [line.name for line in LINES]
    assert document["absorbers"][0] == {
        "Zabs": 1.3855,
        "LineList": "LLS",
        "Color": "sky_blue",
        "Visible": True,
    }


def test_unknown_format_is_refused(lines_table: Table) -> None:
    with pytest.raises(ValueError, match="unknown line-list format"):
        M.format_line_list(MS.line_rows(lines_table), "fits")  # type: ignore[arg-type]


@pytest.mark.parametrize("fmt", ["txt", "csv", "json"])
def test_export_import_round_trip(
    lines_table: Table, absorbers_table: Table, tmp_path: Path, fmt: str
) -> None:
    ctx = NullContext(workspace=tmp_path)
    written = MS.export_linelist(
        lines_table, absorbers_table, path=f"out/lines.{fmt}", format=fmt, ctx=ctx
    )
    assert (tmp_path / written.path).is_file() and written.size > 0
    back, systems = MS.import_linelist(path=f"out/lines.{fmt}", ctx=ctx)
    assert list(back.columns["Name"]) == [line.name for line in LINES]
    assert back.columns["Wave_obs"] == pytest.approx([line.wave_obs for line in LINES], abs=1e-4)
    assert back.columns["Zabs"] == pytest.approx([line.zabs for line in LINES], abs=1e-6)
    # Only the combined JSON carries the absorber systems.
    assert systems.n_rows == (2 if fmt == "json" else 0)


def test_import_needs_a_path() -> None:
    with pytest.raises(ValueError, match="choose a file"):
        MS.import_linelist(path="")


def test_legacy_absorber_columns_are_mapped(tmp_path: Path) -> None:
    target = tmp_path / "legacy.csv"
    target.write_text("Zabs,list,color\n1.3855,LLS,sky_blue\n", encoding="utf-8")
    assert M.load_absorbers(target) == [{"Zabs": 1.3855, "LineList": "LLS", "Color": "sky_blue"}]


def test_wide_column_text_fallback() -> None:
    text = "Name  Wave_obs  Zabs\n---\nMg II  2796  1.0\n"
    assert M.parse_line_list_txt(text) == [{"Name": "Mg II", "Wave_obs": 2796.0, "Zabs": 1.0}]


def test_unsupported_extension() -> None:
    with pytest.raises(ValueError, match="Unsupported file extension"):
        M.load_line_list(Path("lines.fits"))


# --- reconciliation ------------------------------------------------------------------------------


def _write(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text(M.format_line_list_txt(rows), encoding="utf-8")
    return path


def test_reconcile_merges_lines_within_the_velocity_threshold(tmp_path: Path) -> None:
    # 6670.7025 and 6670.9 are 8.5 km/s apart in the rest frame; 6690 is a different transition.
    a = _write(
        tmp_path / "a.txt",
        [
            {"Name": "MgII 2796", "Wave_obs": 6670.7025, "Zabs": 1.3855},
            {"Name": "MgII 2803", "Wave_obs": 6687.8232, "Zabs": 1.3855},
        ],
    )
    b = _write(
        tmp_path / "b.txt",
        [
            {"Name": "MgII 2796[b]", "Wave_obs": 6670.9000, "Zabs": 1.3855},
            {"Name": "CIV 1548", "Wave_obs": 6216.5000, "Zabs": 3.0148},
        ],
    )
    lines, absorbers, info = M.reconcile_linelists([a, b], velocity_threshold=20.0)

    by_name = {row["Name"]: row for row in lines}
    assert set(by_name) == {"MgII 2796", "MgII 2803", "CIV 1548"}
    assert by_name["MgII 2796"]["MergedCount"] == 2
    assert by_name["MgII 2796"]["Wave_obs"] == pytest.approx(6670.80, abs=0.01)
    assert "MergedCount" not in by_name["CIV 1548"]
    assert info["original_line_count"] == 4 and info["reconciled_line_count"] == 3
    assert [round(a["Zabs"], 4) for a in absorbers] == [1.3855, 3.0148]
    assert [a["Color"] for a in absorbers] == list(M.ABSORBER_COLORS[:2])
    assert all(a["LineList"] == "LLS" and a["Visible"] is False for a in absorbers)


def test_reconcile_keeps_lines_further_apart_than_the_threshold(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.txt", [{"Name": "MgII 2796", "Wave_obs": 6670.70, "Zabs": 1.3855}])
    b = _write(tmp_path / "b.txt", [{"Name": "MgII 2796", "Wave_obs": 6673.50, "Zabs": 1.3855}])
    lines, _absorbers, _info = M.reconcile_linelists([a, b], velocity_threshold=20.0)
    assert len(lines) == 2 and all("MergedCount" not in row for row in lines)


def test_reconcile_skips_missing_and_unreadable_files(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    good = _write(tmp_path / "a.txt", [{"Name": "HI 1215", "Wave_obs": 4000.0, "Zabs": 2.29}])
    lines, absorbers, info = M.reconcile_linelists(
        [tmp_path / "missing.txt", broken, good], velocity_threshold=20.0
    )
    assert info["input_files"] == ["a.txt"] and len(lines) == 1 and len(absorbers) == 1


def test_reconcile_without_input_returns_nothing(tmp_path: Path) -> None:
    lines, absorbers, info = M.reconcile_linelists([tmp_path / "nope.txt"])
    assert lines == [] and absorbers == [] and info["original_line_count"] == 0


def test_reconcile_takes_the_line_list_from_an_absorber_csv(tmp_path: Path) -> None:
    lines_file = _write(tmp_path / "a.txt", [{"Name": "HI 1215", "Wave_obs": 4000.0, "Zabs": 2.29}])
    catalog = tmp_path / "abs.csv"
    catalog.write_text("Zabs,LineList,Color\n2.29,DLA,orange\n", encoding="utf-8")
    _lines, absorbers, _info = M.reconcile_linelists([lines_file, catalog])
    assert absorbers[0]["LineList"] == "DLA"


def test_reconcile_node_merges_two_exports(tmp_path: Path) -> None:
    ctx = NullContext(workspace=tmp_path)
    first = MS.export_linelist(MS.identified_table(LINES[:2]), path="a.txt", format="txt", ctx=ctx)
    second = MS.export_linelist(MS.identified_table(LINES), path="b.json", format="json", ctx=ctx)
    lines, absorbers = MS.reconcile_linelists(file=first, file_2=second, ctx=ctx)
    assert sorted(lines.columns["Name"]) == ["CIV 1548", "MgII 2796", "MgII 2803"]
    assert sorted(lines.columns["MergedCount"].tolist()) == [1, 2, 2]
    assert absorbers.n_rows == 2
    assert lines.meta["reconciliation"]["input_files"] == ["a.txt", "b.json"]


def test_reconcile_node_needs_a_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="connect a line-list file"):
        MS.reconcile_linelists(ctx=NullContext(workspace=tmp_path))


def test_paths_fingerprint_tracks_every_file(tmp_path: Path) -> None:
    target = _write(tmp_path / "a.txt", [{"Name": "HI", "Wave_obs": 4000.0, "Zabs": 2.29}])
    before = MS.paths_fingerprint(["a.txt", "b.txt"], workspace=tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8") + "HI 1025 3400.0 2.31\n", encoding="utf-8"
    )
    after = MS.paths_fingerprint(["a.txt", "b.txt"], workspace=tmp_path)
    assert before != after and after.endswith("|missing")
    assert MS.paths_fingerprint([], workspace=tmp_path) == ""


# --- upstream interop -----------------------------------------------------------------------------


@requires_rbcodes
@pytest.mark.parametrize("fmt", ["txt", "csv", "json"])
def test_exported_files_open_in_multispec_io_manager(
    lines_table: Table, absorbers_table: Table, tmp_path: Path, fmt: str
) -> None:
    """Acceptance: rb_multispec's own reader accepts what ``Export Line List`` writes."""
    from rbcodes.GUIs.multispecviewer.io_manager import IOManager  # noqa: PLC0415

    ctx = NullContext(workspace=tmp_path)
    written = MS.export_linelist(
        lines_table, absorbers_table, path=f"lines.{fmt}", format=fmt, ctx=ctx
    )
    target = tmp_path / written.path

    manager = IOManager()
    # The singleton prints through show_message when no Qt message box is attached.
    manager.show_message = lambda *_a, **_k: None  # type: ignore[method-assign]
    manager.append_message = lambda *_a, **_k: None  # type: ignore[method-assign]

    frame, error = manager.load_line_list(str(target))
    assert error is None and frame is not None
    assert list(frame["Name"]) == [line.name for line in LINES]
    assert frame["Wave_obs"].astype(float).tolist() == pytest.approx(
        [line.wave_obs for line in LINES], abs=1e-4
    )
    assert frame["Zabs"].astype(float).tolist() == pytest.approx(
        [line.zabs for line in LINES], abs=1e-6
    )

    if fmt == "json":
        lines, absorbers, files, metadata = manager.load_combined_data(str(target))
        assert len(lines) == 3 and len(absorbers) == 2
        assert files == ["sdss1.fits", "sdss2.fits"]
        assert metadata["application_name"] == "MultispecViewer"
        assert list(absorbers["LineList"]) == ["LLS", "DLA"]


@requires_rbcodes
def test_io_manager_files_are_read_by_the_kernel(tmp_path: Path) -> None:
    """The other direction: what ``IOManager`` writes, ``multispec_io`` reads."""
    import pandas as pd  # noqa: PLC0415
    from rbcodes.GUIs.multispecviewer.io_manager import IOManager  # noqa: PLC0415

    manager = IOManager()
    manager.show_message = lambda *_a, **_k: None  # type: ignore[method-assign]
    manager.append_message = lambda *_a, **_k: None  # type: ignore[method-assign]
    frame = pd.DataFrame(
        [{"Name": line.name, "Wave_obs": line.wave_obs, "Zabs": line.zabs} for line in LINES]
    )
    for fmt in ("txt", "csv"):
        target = tmp_path / f"upstream.{fmt}"
        ok, error = manager.save_line_list(frame, str(target), fmt)
        assert ok and error is None
        rows = M.load_line_list(target)
        assert [row["Name"] for row in rows] == [line.name for line in LINES]
        assert [row["Zabs"] for row in rows] == pytest.approx([line.zabs for line in LINES])


@requires_rbcodes
def test_reconcile_matches_upstream(tmp_path: Path) -> None:
    """The vendored reconciliation agrees with ``multispecviewer.utils`` line for line."""
    from rbcodes.GUIs.multispecviewer import utils  # noqa: PLC0415

    a = _write(
        tmp_path / "a.txt",
        [
            {"Name": "MgII 2796", "Wave_obs": 6670.7025, "Zabs": 1.3855},
            {"Name": "MgII 2803", "Wave_obs": 6687.8232, "Zabs": 1.3855},
            {"Name": "CIV 1548", "Wave_obs": 6216.5000, "Zabs": 3.0148},
        ],
    )
    b = _write(
        tmp_path / "b.txt",
        [
            {"Name": "MgII 2796[b]", "Wave_obs": 6670.9000, "Zabs": 1.3855},
            {"Name": "MgII 2803", "Wave_obs": 6687.9000, "Zabs": 1.3855},
        ],
    )
    mine, my_absorbers, _info = M.reconcile_linelists([a, b], velocity_threshold=20.0)
    theirs, their_absorbers = utils.reconcile_linelists(
        [str(a), str(b)], velocity_threshold=20, output_file=None, create_absorber_df=True
    )

    assert [row["Name"] for row in mine] == list(theirs["Name"])
    assert [row["Wave_obs"] for row in mine] == pytest.approx(
        theirs["Wave_obs"].astype(float).tolist(), abs=1e-4
    )
    assert [row["Zabs"] for row in mine] == pytest.approx(
        theirs["Zabs"].astype(float).tolist(), abs=1e-6
    )
    upstream_counts = theirs.get("MergedCount", [])
    assert [row.get("MergedCount") for row in mine] == [
        None if math.isnan(v) else int(v) for v in upstream_counts
    ]
    assert [row["Zabs"] for row in my_absorbers] == pytest.approx(
        their_absorbers["Zabs"].astype(float).tolist(), abs=1e-6
    )
    assert [row["Color"] for row in my_absorbers] == list(their_absorbers["Color"])
