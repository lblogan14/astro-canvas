"""``rbcodes.ZFindResult`` / ``AbsorberResult`` / ``ZCandidates``: blobs, summaries, validators."""

from __future__ import annotations

import json

import numpy as np
import pytest
from astro_canvas_core.types import Spectrum1D
from astro_canvas_rbcodes.types import (
    AbsorberCandidate,
    AbsorberResult,
    ZCandidateRow,
    ZCandidates,
    ZCurve,
    ZFindResult,
    ZSolution,
    json_floats,
)

from astro_canvas.sdk import arrays_equal


def _spectrum(n: int = 300) -> Spectrum1D:
    wave = np.linspace(3800.0, 9200.0, n)
    error = np.full(n, 0.1)
    error[5] = np.nan  # an SDSS ivar = 0 pixel
    return Spectrum1D(wave=wave, flux=np.ones(n), error=error, continuum=np.ones(n))


def _result(n: int = 5000) -> ZFindResult:
    z = np.linspace(0.0, 1.0, n)
    chi2 = (z - 0.3) ** 2
    chi2[:10] = np.nan
    other = np.cos(z * 20)
    return ZFindResult(
        z_array=z,
        curves=[
            ZCurve(label="PicketFence:zfind_galaxy", values=chi2),
            ZCurve(label="b", values=other),
        ],
        solutions=[
            ZSolution(
                z=0.3, z_err=1e-4, chi2_dof=0.0, method="PicketFence:zfind_galaxy", n_features=5
            ),
            ZSolution(z=0.7, z_err=None, chi2_dof=0.16, method="PicketFence:zfind_galaxy"),
        ],
        input_spec=_spectrum(),
        warnings=["No error array — using MAD-STD IVAR (sigma=0.01)."],
        statistic="score",
        linelist="zfind_galaxy",
        meta={"rbcodes": {"backend": "vendored"}},
    )


def test_zfind_result_roundtrips_through_a_blob() -> None:
    result = _result()
    blob = result.to_blob()
    assert blob.manifest["type"] == "rbcodes.ZFindResult" and "arrays.npz" in blob.parts
    back = ZFindResult.from_blob(blob)
    assert arrays_equal(back.z_array, result.z_array)
    assert [c.label for c in back.curves] == ["PicketFence:zfind_galaxy", "b"]
    assert arrays_equal(back.curves[0].values, result.curves[0].values)
    assert back.solutions == result.solutions and back.statistic == "score"
    assert back.input_spec is not None and arrays_equal(back.input_spec.wave, _spectrum().wave)
    assert back.warnings == result.warnings and back.linelist == "zfind_galaxy"
    assert back.best() is not None and back.best().z == 0.3
    assert ZFindResult(z_array=np.zeros(3), curves=[]).best() is None


def test_zfind_result_summary_is_decimated_aligned_and_json_safe() -> None:
    result = _result()
    summary = result.summary({"n_out": 500})
    assert summary["type"] == "rbcodes.ZFindResult" and summary["statistic"] == "score"
    assert summary["n"] == 5000 and summary["z_range"] == [0.0, 1.0]
    assert 4 < len(summary["z"]) <= 500
    assert all(len(c["values"]) == len(summary["z"]) for c in summary["curves"])
    assert summary["curves"][0]["values"][0] is None  # the NaN head of the curve
    assert summary["solutions"][1]["z_err"] is None and summary["solutions"][0]["n_features"] == 5
    assert summary["spectrum"] is not None and summary["spectrum"]["frame"] == "observed"
    assert None in summary["spectrum"]["error"]  # NaN error -> null, not NaN
    json.dumps(summary, allow_nan=False)
    whole = result.summary({"n_out": 20000})
    assert len(whole["z"]) == 5000
    assert len(result.summary({"n_out": "bogus"})["z"]) <= 2000
    # An all-NaN curve still decimates (even stride) and stays JSON-safe.
    empty = ZFindResult(
        z_array=np.linspace(0, 1, 3000),
        curves=[ZCurve(label="x", values=np.full(3000, np.nan))],
    )
    s = empty.summary({"n_out": 100})
    assert 50 <= len(s["z"]) <= 100 and set(s["curves"][0]["values"]) == {None}
    assert s["spectrum"] is None and s["solutions"] == []
    json.dumps(s, allow_nan=False)
    assert json_floats(np.array([1.0, np.nan, np.inf])) == [1.0, None, None]


def test_zfind_result_validators() -> None:
    with pytest.raises(ValueError, match="points, z has"):
        ZFindResult(z_array=np.zeros(3), curves=[ZCurve(label="a", values=np.zeros(4))])
    chip = ZSolution(z=1.0, z_err=float("nan"), chi2_dof=2.0, method="m").summary()
    assert chip == {
        "type": "rbcodes.ZSolution",
        "data": {
            "z": 1.0,
            "z_err": None,
            "chi2_dof": 2.0,
            "method": "m",
            "template_type": "Unknown",
            "n_features": 0,
        },
    }


def test_absorber_result_roundtrip_and_summary() -> None:
    z = np.linspace(0.5, 2.5, 4000)
    sig = np.exp(-(((z - 1.1377) / 0.002) ** 2)) * 6.0
    result = AbsorberResult(
        z_array=z,
        significance_curve=sig,
        candidates=[
            AbsorberCandidate(
                z=1.1377,
                significance=6.4,
                n_lines=2,
                linelist_name="zfind_igm",
                lines_matched=["MgII 2796", "MgII 2803"],
            ),
            AbsorberCandidate(z=0.67, significance=3.2, n_lines=2, linelist_name="zfind_igm"),
        ],
        input_spec=_spectrum(),
        linelist="zfind_igm",
    )
    back = AbsorberResult.from_blob(result.to_blob())
    assert arrays_equal(back.significance_curve, sig) and back.candidates == result.candidates
    summary = result.summary({"n_out": 400})
    assert summary["statistic"] == "significance" and summary["curves"][0]["label"] == "zfind_igm"
    assert len(summary["z"]) <= 400 and len(summary["curves"]) == 1
    assert summary["candidates"][0]["lines_matched"] == ["MgII 2796", "MgII 2803"]
    assert summary["candidates"][1]["is_doublet"] is False
    json.dumps(summary, allow_nan=False)
    with pytest.raises(ValueError, match="same length"):
        AbsorberResult(z_array=np.zeros(3), significance_curve=np.zeros(2))


def test_zcandidates_roundtrip_and_summary() -> None:
    rows = [
        ZCandidateRow(
            index=0, source=0, rank=0, z=0.3, z_err=1e-4, score=-74.0, method="PicketFence:x"
        ),
        ZCandidateRow(
            index=1,
            source=1,
            rank=0,
            z=0.31,
            z_err=None,
            score=0.01,
            method="Template:QSO",
            template_type="QSO",
            n_features=3813,
        ),
    ]
    cands = ZCandidates(rows=rows, accepted=1, statistics=["score", "chi2"])
    back = ZCandidates.from_blob(cands.to_blob())
    assert back == cands and len(back) == 2
    summary = cands.summary()
    assert summary["type"] == "rbcodes.ZCandidates" and summary["accepted"] == 1
    assert summary["statistics"] == ["score", "chi2"]
    assert summary["rows"][1] == {
        "index": 1,
        "source": 1,
        "rank": 0,
        "z": 0.31,
        "z_err": None,
        "score": 0.01,
        "method": "Template:QSO",
        "template_type": "QSO",
        "n_features": 3813,
    }
    json.dumps(summary, allow_nan=False)
