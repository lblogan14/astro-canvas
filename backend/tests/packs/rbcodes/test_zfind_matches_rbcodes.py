"""The vendored zfind kernels reproduce ``rbcodes.GUIs.zfind`` (runs only where rbcodes imports)."""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pytest
from astro_canvas_core.nodes.io import load_spectrum
from astro_canvas_core.types import Spectrum1D
from astro_canvas_rbcodes.kernels import zfind as Z
from astro_canvas_rbcodes.kernels.picket_fence import PicketFenceZ
from astro_canvas_rbcodes.kernels.zfind_linelists import CURATED_NAMES, LineTable, curated

from astro_canvas.sdk import NullContext
from tests.packs.rbcodes._zfind_synthetic import GAL_EM, MGII, abs_spectrum, em_spectrum, line_table
from tests.packs.rbcodes.conftest import SAMPLES, requires_rbcodes

pytestmark = requires_rbcodes

RTOL = 1e-9


def _rb_spectrum(
    wave: np.ndarray, flux: np.ndarray, error: np.ndarray | None, cont: np.ndarray | None
) -> Any:
    import astropy.units as u
    from rbcodes.utils.rb_spectrum import rb_spectrum

    return rb_spectrum(
        wave * u.AA,
        flux * u.dimensionless_unscaled,
        error=error * u.dimensionless_unscaled if error is not None else None,
        continuum=cont * u.dimensionless_unscaled if cont is not None else None,
        meta={"airvac": "vac"},
    )


def _df(lines: LineTable) -> Any:
    import pandas as pd

    df = pd.DataFrame(
        {"wave": lines.wave, "name": lines.name, "weight": lines.weight, "type": lines.kind}
    )
    df.attrs["name"] = lines.label
    return df


def _same_solutions(ours: list[Z.ZSolution], theirs: list[Any]) -> None:
    assert len(ours) == len(theirs)
    for a, b in zip(ours, theirs, strict=True):
        assert a.z == pytest.approx(b.z, rel=RTOL)
        assert a.chi2_dof == pytest.approx(b.chi2_dof, rel=RTOL)
        assert (np.isnan(a.z_err) and np.isnan(b.z_err)) or a.z_err == pytest.approx(
            b.z_err, rel=1e-6
        )
        assert a.method == b.method and a.template_type == b.template_type
        assert a.n_features == b.n_features


def _same_curve(ours: np.ndarray, theirs: np.ndarray) -> None:
    np.testing.assert_allclose(ours, theirs, rtol=RTOL, atol=1e-12, equal_nan=True)


@pytest.fixture(scope="module")
def galaxy() -> Spectrum1D:
    return load_spectrum(path="spec-0398-51789-0282.fits", ctx=NullContext(workspace=SAMPLES))


def test_curated_lists_match_rbcodes() -> None:
    from rbcodes.GUIs.zfind.linelists import CURATED_NAMES as THEIR_NAMES
    from rbcodes.GUIs.zfind.linelists import get_curated_df

    assert list(CURATED_NAMES) == list(THEIR_NAMES)
    for name in CURATED_NAMES:
        ours, theirs = curated(name), get_curated_df(name)
        assert theirs.attrs["name"] == ours.label
        np.testing.assert_array_equal(ours.wave, theirs["wave"].to_numpy(dtype=float))
        np.testing.assert_array_equal(ours.weight, theirs["weight"].to_numpy(dtype=float))
        assert ours.name.tolist() == theirs["name"].tolist()
        assert ours.kind.tolist() == theirs["type"].tolist()


def test_line_search_matches_rbcodes_in_both_modes() -> None:
    from rbcodes.GUIs.zfind.engine import line_search

    wave, flux, error, cont = em_spectrum(0.5, GAL_EM)
    lines = line_table(GAL_EM, "TestEM")
    for kwargs in (
        {"fit_continuum": False},
        {"fit_continuum": False, "data_norm": "normalize", "smooth_pixels": 1},
        {"fit_continuum": False, "data_norm": "raw", "window_pixels": 3, "wave_min": 5000.0},
    ):
        ours = Z.line_search(
            Z.preprocess(wave, flux, error, cont, fit_continuum=False),
            lines,
            z_min=0.3,
            z_max=0.7,
            n_steps=1500,
            mode="emission",
            **{k: v for k, v in kwargs.items() if k != "fit_continuum"},
        )
        theirs = line_search(
            _rb_spectrum(wave, flux, error, cont),
            _df(lines),
            z_min=0.3,
            z_max=0.7,
            n_steps=1500,
            mode="emission",
            **kwargs,
        )
        assert isinstance(ours, Z.ZFindResult)
        _same_curve(ours.chi2_curves[0]["chi2"], theirs.chi2_curves[0]["chi2"])
        assert ours.chi2_curves[0]["label"] == theirs.chi2_curves[0]["label"]
        _same_solutions(ours.solutions, theirs.solutions)
        assert ours.warnings == theirs.warnings

    # No error, no continuum: MAD ivar and the BIC continuum fit on both sides.
    ours_fit = Z.line_search(
        Z.preprocess(wave, flux, None, None, fit_continuum=True),
        lines,
        z_min=0.3,
        z_max=0.7,
        n_steps=800,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        theirs_fit = line_search(
            _rb_spectrum(wave, flux, None, None), _df(lines), z_min=0.3, z_max=0.7, n_steps=800
        )
    assert isinstance(ours_fit, Z.ZFindResult)
    _same_curve(ours_fit.chi2_curves[0]["chi2"], theirs_fit.chi2_curves[0]["chi2"])
    assert ours_fit.warnings == theirs_fit.warnings

    a_wave, a_flux, a_err, a_cont = abs_spectrum(
        [{"z": 0.5, "lines": MGII}, {"z": 1.2, "lines": MGII}]
    )
    abs_lines = line_table(MGII, "TestAbs")
    ours_abs = Z.line_search(
        Z.preprocess(a_wave, a_flux, a_err, a_cont, fit_continuum=False),
        abs_lines,
        z_min=0.0,
        z_max=2.0,
        n_steps=3000,
        mode="absorption",
    )
    theirs_abs = line_search(
        _rb_spectrum(a_wave, a_flux, a_err, a_cont),
        _df(abs_lines),
        z_min=0.0,
        z_max=2.0,
        n_steps=3000,
        mode="absorption",
        fit_continuum=False,
    )
    assert isinstance(ours_abs, Z.AbsorberResult)
    _same_curve(ours_abs.significance_curve, theirs_abs.significance_curve)
    assert len(ours_abs.candidates) == len(theirs_abs.candidates)
    for a, b in zip(ours_abs.candidates, theirs_abs.candidates, strict=True):
        assert a.z == pytest.approx(b.z, rel=RTOL) and a.significance == pytest.approx(
            b.significance, rel=RTOL
        )
        assert a.n_lines == b.n_lines and a.lines_matched == list(b.lines_matched)
        assert a.linelist_name == b.linelist_name and a.is_doublet == b.is_doublet
    from rbcodes.GUIs.zfind.adapters import absorbers_to_multispec

    assert Z.absorbers_to_multispec(ours_abs, [0, 1]) == absorbers_to_multispec(theirs_abs, [0, 1])


def test_picket_fence_matches_rbcodes(galaxy: Spectrum1D) -> None:
    from rbcodes.GUIs.zfind.engine import picket_fence_search
    from rbcodes.GUIs.zfind.picket_fence import PicketFenceZ as TheirPF

    assert galaxy.error is not None
    lines = curated("zfind_galaxy")
    prep = Z.preprocess(galaxy.wave, galaxy.flux, galaxy.error, None, fit_continuum=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        spec = _rb_spectrum(galaxy.wave, galaxy.flux, galaxy.error, None)
        for kwargs in (
            {"smooth_fwhm_pix": 2.0, "fwhm_ang": 3.0},
            {"pf_mode": "detect_match", "prominence_sigma": 4.0, "window_pixels": 4},
            {"use_error": False, "data_norm": "normalize", "wave_max": 8000.0},
            {"res_kwargs": {"R": 1800}, "window_fwhm": 2.0},
        ):
            ours_kwargs = dict(kwargs)
            if "res_kwargs" in ours_kwargs:
                ours_kwargs["resolution"] = ours_kwargs.pop("res_kwargs")
            ours = Z.picket_fence_search(
                prep, lines, z_min=0.0, z_max=0.3, n_steps=1200, **ours_kwargs
            )
            theirs = picket_fence_search(
                spec, _df(lines), z_min=0.0, z_max=0.3, n_steps=1200, **kwargs
            )
        _same_curve(ours.chi2_curves[0]["chi2"], theirs.chi2_curves[0]["chi2"])
        _same_solutions(ours.solutions, theirs.solutions)
        assert ours.warnings == theirs.warnings
        assert ours.best() is not None and abs(ours.best().z - 0.00586) < 0.002

    # Mode B candidates and peak detection through the class itself.
    flux_work = prep.flux - prep.continuum
    ours_pf = PicketFenceZ(
        prep.wave, flux_work, prep.ivar, lines, smooth_fwhm_pix=2.0, resolution={"fwhm_ang": 3.0}
    )
    theirs_pf = TheirPF(
        prep.wave, flux_work, prep.ivar, _df(lines), smooth_fwhm_pix=2.0, fwhm_ang=3.0
    )
    assert ours_pf.fwhm_pix == theirs_pf.fwhm_pix and ours_pf.window_pixels == theirs_pf._wp
    _same_curve(ours_pf.flux_smooth, theirs_pf.flux_smooth)
    for key in ("emission", "absorption"):
        np.testing.assert_array_equal(ours_pf.detect_peaks()[key], theirs_pf.detect_peaks()[key])
    ours_c, theirs_c = ours_pf.match_peaks(), theirs_pf.match_peaks()
    assert len(ours_c) == len(theirs_c)
    for a, b in zip(ours_c, theirs_c, strict=True):
        assert a["z"] == pytest.approx(b["z"], rel=RTOL) and a["score"] == pytest.approx(b["score"])
        assert a["n_matches"] == b["n_matches"]
        assert [ln["name"] for ln in a["lines"]] == [str(ln["name"]) for ln in b["lines"]]


def test_template_and_pca_search_match_rbcodes(galaxy: Spectrum1D) -> None:
    from rbcodes.GUIs.zfind.engine import (
        multi_pca_search,
        multi_template_search,
        pca_search,
        template_search,
    )

    assert galaxy.error is not None
    prep = Z.preprocess(galaxy.wave, galaxy.flux, galaxy.error, None, fit_continuum=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        spec = _rb_spectrum(galaxy.wave, galaxy.flux, galaxy.error, None)
        ours_t = Z.template_search(prep, "LateTypeEmission", z_min=0.0, z_max=0.2, n_steps=300)
        theirs_t = template_search(spec, "LateTypeEmission", z_min=0.0, z_max=0.2, n_steps=300)
        _same_curve(ours_t.chi2_curves[0]["chi2"], theirs_t.chi2_curves[0]["chi2"])
        _same_solutions(ours_t.solutions, theirs_t.solutions)
        ours_t2 = Z.template_search(
            prep,
            "EarlyType",
            z_min=0.0,
            z_max=0.1,
            n_steps=100,
            data_norm="subtract",
            model_norm="subtract",
            smooth_pixels=3,
            template_res_kwargs={"fwhm_ang": 3.0},
        )
        theirs_t2 = template_search(
            spec,
            "EarlyType",
            z_min=0.0,
            z_max=0.1,
            n_steps=100,
            data_norm="subtract",
            model_norm="subtract",
            smooth_pixels=3,
            template_res_kwargs={"fwhm_ang": 3.0},
        )
        _same_curve(ours_t2.chi2_curves[0]["chi2"], theirs_t2.chi2_curves[0]["chi2"])
        ours_m = Z.multi_template_search(
            prep, ["Composite", "QSO"], z_min=0.0, z_max=0.1, n_steps=60
        )
        theirs_m = multi_template_search(
            spec, ["Composite", "QSO"], z_min=0.0, z_max=0.1, n_steps=60
        )
        assert [c["label"] for c in ours_m.chi2_curves] == [
            c["label"] for c in theirs_m.chi2_curves
        ]
        for a, b in zip(ours_m.chi2_curves, theirs_m.chi2_curves, strict=True):
            _same_curve(a["chi2"], b["chi2"])
        _same_solutions(ours_m.solutions, theirs_m.solutions)

        ours_p = Z.pca_search(prep, "galaxy", z_min=0.0, z_max=0.1, n_steps=120)
        theirs_p = pca_search(spec, "galaxy", z_min=0.0, z_max=0.1, n_steps=120)
        _same_curve(ours_p.chi2_curves[0]["chi2"], theirs_p.chi2_curves[0]["chi2"])
        _same_solutions(ours_p.solutions, theirs_p.solutions)
        assert ours_p.best() is not None and abs(ours_p.best().z - 0.00586) < 0.002
        ours_mp = Z.multi_pca_search(
            prep,
            ["qso_loz", "qso_hiz"],
            n_steps=80,
            model_norm="subtract",
            pca_res_kwargs={"R": 2000},
        )
        theirs_mp = multi_pca_search(
            spec,
            ["qso_loz", "qso_hiz"],
            n_steps=80,
            model_norm="subtract",
            pca_res_kwargs={"R": 2000},
        )
        _same_curve(ours_mp.z_array, theirs_mp.z_array)
        for a, b in zip(ours_mp.chi2_curves, theirs_mp.chi2_curves, strict=True):
            assert a["label"] == b["label"]
            _same_curve(a["chi2"], b["chi2"])
