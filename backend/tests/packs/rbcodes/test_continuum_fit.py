"""``rbcodes.continuum.fit`` and ``full_spectrum``: masks, methods, weights, progress."""

from __future__ import annotations

import numpy as np
import pytest
from astro_canvas_core.types import RangeMask, Spectrum1D
from astro_canvas_rbcodes.nodes import absorption as A
from astro_canvas_rbcodes.nodes import continuum as C

from astro_canvas.sdk import NullContext


@pytest.fixture(scope="module")
def mgii_slice(sdss1: Spectrum1D) -> Spectrum1D:
    rest = A.set_redshift(sdss1, z=1.3855)
    tr = A.set_transition(rest, wrest=2796.35)
    return A.slice_spectrum(rest, tr, vmin=-1500, vmax=1500)


def _synthetic(n: int = 400, seed: int = 1) -> Spectrum1D:
    rng = np.random.default_rng(seed)
    v = np.linspace(-1500, 1500, n)
    cont = 3.0 + 0.0004 * v + 1e-7 * v**2
    line = 1 - 0.7 * np.exp(-0.5 * (v / 80) ** 2)
    error = np.full(n, 0.05)
    flux = cont * line + rng.normal(0, 0.05, n)
    return Spectrum1D(
        wave=v, flux=flux, error=error, frame="velocity", wave_unit="km / s", v0_wrest=2796.352
    )


def test_masks_exclude_the_line_and_the_bic_scan_picks_an_order(mgii_slice: Spectrum1D) -> None:
    cont, norm = C.fit(mgii_slice, masks=[(-300, 250), (500, 1000)], optimize_order=True)
    assert cont.method == "polynomial" and cont.order == 1 and cont.bic is not None
    table = cont.params["bic_results"]
    assert [row[0] for row in table] == list(range(0, 8))
    assert min(row[1] for row in table) == pytest.approx(cont.bic)
    assert cont.masks == [(-300.0, 250.0), (500.0, 1000.0)] and cont.params["n_masked"] > 0
    assert norm.flux_unit == "normalized" and norm.error is not None
    assert np.allclose(norm.flux * cont.cont, mgii_slice.flux)
    assert norm.meta["rb_spec"]["continuum_masks"] == [-300.0, 250.0, 500.0, 1000.0]
    assert norm.meta["rb_spec"]["continuum_fit_params"]["legendre_order"] == 1
    # The absorption trough is well below the fitted continuum, the wings sit at unity.
    core = norm.flux[np.abs(norm.wave) < 60]
    wings = norm.flux[(norm.wave > 1100) | (norm.wave < -1100)]
    assert core.min() < 0.3 and abs(np.median(wings) - 1.0) < 0.1
    # Masks change the fit; the same masks through the RangeMask port give the same answer.
    unmasked, _ = C.fit(mgii_slice, masks=[], optimize_order=True)
    assert not np.allclose(unmasked.cont, cont.cont)
    via_port, _ = C.fit(
        mgii_slice,
        masks=[],
        extra_masks=RangeMask(ranges=[(-300, 250), (500, 1000)], frame="velocity", unit="km / s"),
        optimize_order=True,
    )
    np.testing.assert_allclose(via_port.cont, cont.cont)


def test_fixed_order_legendre_alias_flat_spline_and_ransac() -> None:
    spec = _synthetic()
    masks = [(-250.0, 250.0)]
    fixed, _ = C.fit(spec, order=2, optimize_order=False, masks=masks)
    legendre, _ = C.fit(spec, method="legendre", order=2, optimize_order=False, masks=masks)
    assert fixed.order == 2 and "bic_results" not in fixed.params and fixed.bic is None
    np.testing.assert_allclose(legendre.cont, fixed.cont)
    truth = 3.0 + 0.0004 * spec.wave + 1e-7 * spec.wave**2
    assert np.max(np.abs(fixed.cont - truth) / truth) < 0.03
    flat, flat_norm = C.fit(spec, method="flat", masks=masks)
    assert flat.order == 0 and np.all(flat.cont == flat.cont[0]) and flat_norm.error is not None
    spline, _ = C.fit(spec, method="spline", masks=masks, knot_spacing=500.0)
    assert spline.cont.shape == spec.wave.shape and np.all(np.isfinite(spline.cont))
    assert np.max(np.abs(spline.cont - truth) / truth) < 0.05
    ransac, _ = C.fit(spec, method="ransac", order=2, masks=masks)
    assert ransac.order == 2 and np.max(np.abs(ransac.cont - truth) / truth) < 0.05
    no_clip, _ = C.fit(spec, order=2, optimize_order=False, masks=masks, sigma_clip=False)
    assert no_clip.params["sigma_clip"] is False and no_clip.cont.shape == spec.wave.shape


def test_use_weights_propagates_the_continuum_uncertainty(mgii_slice: Spectrum1D) -> None:
    masks = [(-300, 250), (500, 1000)]
    _, plain = C.fit(mgii_slice, masks=masks, use_weights=False)
    cont, weighted = C.fit(mgii_slice, masks=masks, use_weights=True)
    assert cont.params["use_weights"] is True
    assert plain.error is not None and weighted.error is not None
    assert np.all(weighted.error >= plain.error - 1e-12) and np.any(weighted.error > plain.error)
    assert weighted.meta["rb_spec"]["cont_err"] > 0


def test_fit_rejects_hopeless_inputs(mgii_slice: Spectrum1D) -> None:
    with pytest.raises(ValueError, match="error array"):
        C.fit(mgii_slice.model_copy(update={"error": None}))
    with pytest.raises(ValueError, match="not enough unmasked"):
        C.fit(mgii_slice, masks=[(-2000, 2000)])


def test_full_spectrum_continuum_reports_progress_and_covers_the_range(sdss1: Spectrum1D) -> None:
    ctx = NullContext()
    cont = C.full_spectrum(
        sdss1,
        window_size=400.0,
        min_order=1,
        max_order=3,
        use_weights=False,
        wmin=5000.0,
        wmax=7000.0,
        ctx=ctx,
    )
    assert cont.method == "full_spectrum" and cont.params["chunking"] == "uniform"
    inside = (sdss1.wave >= 5000.0) & (sdss1.wave <= 7000.0)
    assert np.all(np.isfinite(cont.cont[inside])) and np.all(np.isnan(cont.cont[~inside]))
    assert len(cont.params["chunks"]) >= 3 and all(
        1 <= c["best_order"] <= 3 for c in cont.params["chunks"]
    )
    fractions = [f for f, _ in ctx.progress_events]
    assert fractions[0] < fractions[-1] == 1.0
    ratio = sdss1.flux[inside] / cont.cont[inside]
    assert 0.8 < np.nanmedian(ratio) < 1.2
    features = C.full_spectrum(
        sdss1,
        window_size=400.0,
        chunking="features",
        min_order=1,
        max_order=2,
        use_weights=False,
        wmin=5000.0,
        wmax=7000.0,
    )
    assert features.params["chunking"] == "features" and np.all(np.isfinite(features.cont[inside]))
    cancelled = NullContext(cancelled=True)
    with pytest.raises(InterruptedError):
        C.full_spectrum(sdss1, window_size=400.0, ctx=cancelled)
    with pytest.raises(ValueError, match="wavelength axis"):
        C.full_spectrum(
            A.slice_spectrum(A.set_redshift(sdss1, z=1.3855), A.set_transition(wrest=2796.35))
        )
