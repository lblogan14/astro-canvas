"""Batch results tables over real core port types: flattening and the ``astro.Table`` build."""

from __future__ import annotations

import math

import numpy as np
from astro_canvas_core import types as T

from astro_canvas.engine.batch import (
    ERROR_COLUMN,
    STATUS_COLUMN,
    TIMESTAMP_COLUMN,
    BatchResults,
    flatten_value,
)
from astro_canvas.sdk import NodeRegistry

EW = T.EWMeasurement(
    W=2.07,
    W_e=0.04,
    N=9.8e13,
    N_e=1.1e12,
    logN=13.99,
    logN_e=0.05,
    vel_centroid=-12.5,
    vel_disp=88.0,
    SNR=21.3,
    saturated=False,
    flag=0,
    vmin=-200.0,
    vmax=200.0,
    transition=T.Transition(wrest=2796.35, name="MgII 2796", fval=0.6155),
)


def test_an_ew_measurement_flattens_to_the_specgui_result_columns() -> None:
    columns = flatten_value(EW)
    for name in ("W", "W_e", "N", "N_e", "logN", "logN_e", "vel_centroid", "vel_disp", "SNR"):
        assert name in columns
    assert columns["W"] == 2.07 and columns["logN"] == 13.99
    assert columns["saturated"] is False and columns["flag"] == 0
    # Nested models are walked with dotted names.
    assert columns["transition.wrest"] == 2796.35
    assert columns["transition.name"] == "MgII 2796"


def test_flattening_skips_arrays_and_honours_a_prefix() -> None:
    spectrum = T.Spectrum1D(wave=np.linspace(1.0, 2.0, 8), flux=np.ones(8), z=0.5)
    columns = flatten_value(spectrum, "spec.")
    assert columns["spec.z"] == 0.5 and columns["spec.wave_unit"] == "Angstrom"
    assert "spec.wave" not in columns and "spec.flux" not in columns


def test_missing_cells_keep_a_numeric_column_numeric(registry: NodeRegistry) -> None:
    results = BatchResults(
        columns=["path", "W", "n", "ok", STATUS_COLUMN, ERROR_COLUMN, TIMESTAMP_COLUMN],
        rows=[
            {
                "path": "a.fits",
                "W": 2.07,
                "n": 3,
                "ok": True,
                STATUS_COLUMN: "done",
                ERROR_COLUMN: "",
                TIMESTAMP_COLUMN: "2026-09-03T00:00:00+00:00",
            },
            {
                "path": "b.fits",
                "W": None,
                "n": None,
                "ok": False,
                STATUS_COLUMN: "error",
                ERROR_COLUMN: "boom",
                TIMESTAMP_COLUMN: "",
            },
        ],
    )
    table = results.to_table(registry)
    assert table.n_rows == 2
    assert table.columns["W"].dtype == np.float64 and math.isnan(table.columns["W"][1])
    assert table.columns["n"].dtype == np.float64  # a gap widens int to float
    assert table.columns["ok"].dtype == np.bool_
    assert list(table.columns["status"]) == ["done", "error"]


def test_a_results_table_round_trips_through_arrow(registry: NodeRegistry) -> None:
    results = BatchResults(
        columns=["path", "W", STATUS_COLUMN],
        rows=[{"path": "a.fits", "W": 1.5, STATUS_COLUMN: "done"}],
    )
    table = results.to_table(registry)
    restored = type(table).from_blob(table.to_blob())
    assert list(restored.columns) == ["path", "W", "status"]
    assert restored.columns["W"][0] == 1.5
