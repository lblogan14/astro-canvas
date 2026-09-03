"""Viewport-aware summaries added in phase 05: ``Continuum`` and ``LineList``."""

from __future__ import annotations

import numpy as np
from astro_canvas_core.types import Continuum, LineList


def test_continuum_summary_is_whole_when_small_and_strided_when_large() -> None:
    cont = Continuum(
        cont=np.linspace(1.0, 2.0, 50),
        masks=[(-100.0, 50.0), (400.0, 900.0)],
        method="polynomial",
        order=3,
        params={
            "bic_results": [(1, np.float64(10.5)), (2, 9.0)],
            "fit_error": np.float64(0.1),
            "nan": float("nan"),
        },
        bic=9.0,
    )
    small = cont.summary()
    assert small["n"] == 50 and small["index"] == list(range(50))
    assert small["cont"][0] == 1.0 and small["cont"][-1] == 2.0
    assert small["masks"] == [[-100.0, 50.0], [400.0, 900.0]]
    assert small["order"] == 3 and small["bic"] == 9.0 and small["method"] == "polynomial"
    assert small["params"] == {"bic_results": [[1, 10.5], [2, 9.0]], "fit_error": 0.1, "nan": None}
    large = Continuum(cont=np.arange(100_000, dtype=float)).summary({"n_out": 1000})
    assert large["n"] == 100_000 and len(large["cont"]) <= 1000
    assert len(large["index"]) == len(large["cont"]) and large["index"][-1] == 99_999
    assert large["cont"][7] == float(large["index"][7])


def test_linelist_summary_lists_transitions_up_to_rows() -> None:
    lines = LineList(
        wrest=np.array([1215.67, 1548.2, 2796.35]),
        name=np.array(["HI 1215", "CIV 1548", "MgII 2796"]),
        fval=np.array([0.4164, 0.19, 0.6155]),
        gamma=np.array([6.265e8, 2.65e8, 2.6e8]),
        source="atom",
    )
    summary = lines.summary()
    assert summary["n"] == 3 and summary["source"] == "atom"
    assert summary["name"] == ["HI 1215", "CIV 1548", "MgII 2796"]
    assert summary["wrest"][2] == 2796.35 and summary["gamma"][0] == 6.265e8
    head = lines.summary({"rows": 2})
    assert len(head["wrest"]) == 2 and head["n"] == 3
