"""The vendored kernels agree with rbcodes itself (runs only where rbcodes is importable)."""

from __future__ import annotations

import warnings

import numpy as np
import pytest
from astro_canvas_core.types import Spectrum1D
from astro_canvas_rbcodes.kernels import contfit, ew, setline, snr
from astro_canvas_rbcodes.nodes import absorption as A

from tests.packs.rbcodes.conftest import requires_rbcodes

pytestmark = requires_rbcodes


@pytest.fixture(scope="module")
def slice_arrays(sdss1: Spectrum1D) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rest = A.set_redshift(sdss1, z=1.3855)
    tr = A.set_transition(rest, wrest=2796.35)
    sl = A.slice_spectrum(rest, tr, vmin=-1500, vmax=1500)
    assert sl.error is not None
    wave_rest = tr.wrest * (1.0 + sl.wave / 2.9979e5)
    return sl.wave, wave_rest, sl.flux, sl.error


def test_line_lists_match_rbcodes_row_for_row() -> None:
    from rbcodes.IGM import rb_setline as rb

    for label in setline.LINE_LISTS:
        ours = setline.read_line_list(label)
        theirs = rb.read_line_list(label)
        assert len(ours) == len(theirs), label
        for a, b in zip(ours, theirs, strict=True):
            assert a["wrest"] == pytest.approx(float(b["wrest"])), label
            assert str(a["ion"]) == str(b["ion"]), label
            assert a["fval"] == pytest.approx(float(b["fval"])), label
    for lam in (1215.67, 2796.3, 1548.2, 5000.0):
        ours_closest = setline.rb_setline(lam, "closest")
        theirs_closest = rb.rb_setline(lam, "closest")
        assert ours_closest["name"] == theirs_closest["name"]
        assert float(ours_closest["wave"]) == float(theirs_closest["wave"])


def test_compute_ew_matches_rbcodes(
    slice_arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    from rbcodes.IGM.compute_EW import compute_EW

    velo, wave_rest, flux, error = slice_arrays
    cont = np.median(flux)
    fnorm, enorm = flux / cont, error / cont
    for kwargs in (
        {"f0": 0.6123},
        {"f0": 0.6123, "sat_limit": None},
        {"f0": 0.6123, "sat_limit": 0.2},
        {"f0": None},
        {"f0": 0.6123, "SNR": True, "_binsize": 3},
        {"f0": 0.6123, "normalization": "median"},
    ):
        theirs = compute_EW(
            wave_rest, fnorm.copy(), 2796.352, [-200.0, 200.0], enorm.copy(), plot=False, **kwargs
        )
        ours = ew.compute_ew(
            wave_rest,
            fnorm,
            2796.352,
            [-200.0, 200.0],
            enorm,
            f0=kwargs.get("f0"),
            sat_limit=kwargs.get("sat_limit", "auto"),
            normalization=kwargs.get("normalization", "none"),
            snr=kwargs.get("SNR", False),
            binsize=kwargs.get("_binsize", 1),
        )
        assert set(ours) == set(theirs), kwargs
        for key, value in theirs.items():
            if key == "Tau_a":
                np.testing.assert_allclose(ours[key], value, rtol=1e-12, atol=1e-12)
            else:
                assert ours[key] == pytest.approx(value, rel=1e-12, abs=1e-12), (key, kwargs)


def test_continuum_fitters_match_rbcodes(
    slice_arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    from rbcodes.IGM.rb_iter_contfit import fit_optimal_polynomial, rb_iter_contfit

    velo, _, flux, error = slice_arrays
    keep = ~(((velo >= -300) & (velo <= 250)) | ((velo >= 500) & (velo <= 1000)))
    x, f, e = velo[keep], flux[keep], error[keep]
    for use_weights in (False, True):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            theirs = rb_iter_contfit(
                x,
                f.copy(),
                error=e.copy(),
                order=3,
                sigma=3.0,
                use_weights=use_weights,
                return_model=True,
                silent=True,
            )
        ours = contfit.rb_iter_contfit(x, f, e, order=3, sigma=3.0, use_weights=use_weights)
        np.testing.assert_allclose(ours["continuum"], theirs["continuum"], rtol=1e-9, atol=1e-12)
        assert ours["fit_error"] == pytest.approx(theirs["fit_error"], rel=1e-9)
        np.testing.assert_allclose(ours["model"](velo), theirs["model"](velo), rtol=1e-9)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            theirs_opt = fit_optimal_polynomial(
                x,
                f.copy(),
                error=e.copy(),
                min_order=0,
                max_order=7,
                maxiter=25,
                sigma=3.0,
                use_weights=use_weights,
                plot=False,
                silent=True,
                include_model=True,
            )
        ours_opt = contfit.fit_optimal_polynomial(
            x, f, e, min_order=0, max_order=7, maxiter=25, sigma=3.0, use_weights=use_weights
        )
        assert ours_opt["best_order"] == theirs_opt["best_order"]
        for (o1, b1), (o2, b2) in zip(
            ours_opt["bic_results"], theirs_opt["bic_results"], strict=True
        ):
            assert o1 == o2 and b1 == pytest.approx(b2, rel=1e-9)
        np.testing.assert_allclose(ours_opt["continuum"], theirs_opt["continuum"], rtol=1e-9)
    theirs_noerr = rb_iter_contfit(x, f.copy(), order=2, silent=True, return_model=True)
    ours_noerr = contfit.rb_iter_contfit(x, f, None, order=2)
    np.testing.assert_allclose(ours_noerr["continuum"], theirs_noerr["continuum"], rtol=1e-9)


def test_specbin_and_snr_match_rbcodes(
    slice_arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    from rbcodes.IGM.rb_specbin import rb_specbin
    from rbcodes.utils.compute_SNR_1d import estimate_snr

    _, wave_rest, flux, error = slice_arrays
    for nbin in (1, 3, 5, 7):
        theirs = rb_specbin(flux, nbin, wave=wave_rest, var=error**2)
        ours = snr.rb_specbin(flux, nbin, wave=wave_rest, var=error**2)
        for key in ("flux", "error", "wave"):
            np.testing.assert_allclose(ours[key], theirs[key], rtol=1e-12)
    theirs_snr = estimate_snr(
        wave_rest,
        flux,
        error,
        binsize=3,
        verbose=False,
        robust_median=True,
        sigma_clip_threshold=2.0,
    )
    ours_snr = snr.estimate_snr(
        wave_rest, flux, error, binsize=3, robust_median=True, sigma_clip_threshold=2.0
    )
    assert ours_snr["robust_snr"] == pytest.approx(theirs_snr["robust_snr"], rel=1e-12)
    assert ours_snr["median_snr"] == pytest.approx(theirs_snr["median_snr"], rel=1e-12)


def test_full_spectrum_fitter_matches_rbcodes(sdss1: Spectrum1D) -> None:
    from astro_canvas_rbcodes.kernels.fullspec import fit_quasar_continuum as ours_fit
    from rbcodes.IGM.fit_continuum_full_spec import fit_quasar_continuum

    assert sdss1.error is not None
    keep = (sdss1.wave > 6000) & (sdss1.wave < 7000)
    wave, flux, error = sdss1.wave[keep], sdss1.flux[keep], sdss1.error[keep]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        theirs = fit_quasar_continuum(
            (wave, flux, error),
            chunk_params={"window_size": 200, "overlap_fraction": 0.3},
            fitting_params={"min_order": 2, "max_order": 4, "sigma": 3.0, "use_weights": False},
            save_output=False,
            plot=False,
        )
    ours = ours_fit(
        wave,
        flux,
        error,
        window_size=200,
        overlap_fraction=0.3,
        min_order=2,
        max_order=4,
        sigma=3.0,
        use_weights=False,
    )
    assert theirs is not None
    assert len(ours["chunk_results"]) == len(theirs["chunk_results"])
    for a, b in zip(ours["chunk_results"], theirs["chunk_results"], strict=True):
        assert a["best_order"] == b["best_order"] and a["indices"] == tuple(b["indices"])
    # rbcodes fills zero-weight pixels (the outermost pixel on each side, where every cosine taper
    # is exactly 0) by interpolating the *weighted sum* instead of the blended continuum; the port
    # blends them properly, so only the interior is compared bit for bit.
    np.testing.assert_allclose(ours["continuum"][1:-1], theirs["continuum"][1:-1], rtol=1e-9)
    assert np.all(np.isfinite(ours["continuum"]))
