"""The vendored zfind kernels recover known redshifts (ports of rbcodes' ``test_zfind_engine_*``).

Tolerances are the ones rbcodes' own tests use: 0.002 in z for emission line search over a
2000-step grid, 0.005/0.01 for absorbers, 0.01 for the picket fence self-test.
"""

from __future__ import annotations

import numpy as np
import pytest
from astro_canvas_rbcodes.kernels import zfind as Z
from astro_canvas_rbcodes.kernels.picket_fence import PicketFenceZ, to_fwhm_pix, validate_ivar
from astro_canvas_rbcodes.kernels.zfind_linelists import CURATED_NAMES, LineTable, curated

from tests.packs.rbcodes._zfind_synthetic import (
    CIVA,
    GAL_EM,
    MGII,
    abs_spectrum,
    em_spectrum,
    gaussian_lines,
    line_table,
)


def _prep(arrays: tuple, *, fit_continuum: bool = False, airvac: str = "vac") -> Z.Prepared:
    wave, flux, error, continuum = arrays
    return Z.preprocess(wave, flux, error, continuum, fit_continuum=fit_continuum, airvac=airvac)


# --- curated line lists ------------------------------------------------------------------------


def test_curated_presets_match_rbcodes_tables() -> None:
    assert CURATED_NAMES == ("zfind_em", "zfind_stellar", "zfind_igm", "zfind_galaxy", "zfind_qso")
    em = curated("zfind_em")
    assert len(em) == 10 and em.label == "zfind_em"
    assert set(em.kind.tolist()) == {"emission"}
    assert em.weight[em.name == "Halpha"][0] == 3.0
    igm = curated("zfind_igm")
    assert igm.wave[igm.name == "SiII 1260"][0] == 1260.42
    assert igm.weight[igm.name == "SiII 1260"][0] == 1.007
    galaxy = curated("zfind_galaxy")
    assert sorted(set(galaxy.kind.tolist())) == ["absorption", "emission"] and len(galaxy) == 14
    assert len(curated("zfind_stellar")) == 8 and len(curated("zfind_qso")) == 8
    with pytest.raises(KeyError, match="not a curated preset"):
        curated("nope")
    built = LineTable.build([1.0, 2.0], ["a", "b"])
    assert built.weight.tolist() == [1.0, 1.0] and built.kind.tolist() == ["emission"] * 2
    with pytest.raises(ValueError, match="same length"):
        LineTable(
            wave=np.zeros(2), name=np.array(["a"]), weight=np.zeros(2), kind=np.array(["e", "e"])
        )


# --- preprocessing -----------------------------------------------------------------------------


def test_preprocess_ivar_fallbacks_and_air_to_vacuum() -> None:
    wave, flux, error, cont = em_spectrum(0.5, GAL_EM)
    prep = Z.preprocess(wave, flux, error, cont, fit_continuum=False)
    assert prep.warnings == [] and np.allclose(prep.ivar, 1.0 / error**2)
    no_err = Z.preprocess(wave, flux, None, cont, fit_continuum=False)
    assert any("MAD" in w for w in no_err.warnings) and np.all(no_err.ivar == no_err.ivar[0])
    air = Z.preprocess(wave, flux, error, cont, fit_continuum=False, airvac="air")
    assert any("vacuum" in w.lower() for w in air.warnings)
    assert np.all(air.wave > wave) and np.allclose(air.wave / wave, 1.0003, atol=2e-4)
    assert np.array_equal(Z.air_to_vacuum(np.array([1500.0])), np.array([1500.0]))
    flux_nan = flux.copy()
    flux_nan[10] = np.nan
    cleaned = Z.preprocess(wave, flux_nan, error, cont, fit_continuum=False)
    assert cleaned.ivar[10] == 0.0 and cleaned.flux[10] == 0.0
    fitted = Z.preprocess(wave, flux, error, None, fit_continuum=True)
    assert fitted.warnings == [] and abs(float(np.median(fitted.continuum)) - 1.0) < 0.05
    zero = Z.preprocess(wave, flux, error, None, fit_continuum=False)
    assert np.all(zero.continuum == 0.0)


# --- line search: emission ---------------------------------------------------------------------


class TestLineSearchEmission:
    def test_structure(self) -> None:
        arrays = em_spectrum(0.5, GAL_EM)
        result = Z.line_search(
            _prep(arrays), line_table(GAL_EM, "TestEM"), z_min=0.3, z_max=0.7, n_steps=2000
        )
        assert isinstance(result, Z.ZFindResult)
        assert len(result.z_array) == 2000
        assert result.z_array[0] == pytest.approx(0.3) and result.z_array[-1] == pytest.approx(0.7)
        assert len(result.chi2_curves) == 1 and "TestEM" in result.chi2_curves[0]["label"]
        assert len(result.chi2_curves[0]["chi2"]) == 2000
        assert result.solutions and all(isinstance(s, Z.ZSolution) for s in result.solutions)
        assert result.warnings == []
        best = result.best()
        assert best is not None and "TestEM" in best.method
        assert all(best.chi2_dof <= s.chi2_dof for s in result.solutions)
        assert 1 <= best.n_features <= len(GAL_EM)
        assert np.isfinite(best.z_err)

    @pytest.mark.parametrize(
        ("true_z", "names", "z_min", "z_max", "tol"),
        [
            (0.5, ("Halpha", "Hbeta", "[OIII]5007"), 0.3, 0.7, 0.002),
            (0.2, tuple(GAL_EM), 0.0, 0.4, 0.002),
            (0.4, ("Halpha",), 0.2, 0.6, 0.002),
        ],
    )
    def test_recovers_known_z(
        self, true_z: float, names: tuple[str, ...], z_min: float, z_max: float, tol: float
    ) -> None:
        lines = {k: GAL_EM[k] for k in names}
        result = Z.line_search(
            _prep(em_spectrum(true_z, lines)),
            line_table(lines),
            z_min=z_min,
            z_max=z_max,
            n_steps=2000,
        )
        assert isinstance(result, Z.ZFindResult)
        best = result.best()
        assert best is not None and abs(best.z - true_z) < tol

    def test_high_redshift_and_strong_lines_have_small_z_err(self) -> None:
        optical = {"Halpha": 6562.80, "Hbeta": 4861.33, "[OIII]5007": 5006.84}
        hi = Z.line_search(
            _prep(em_spectrum(1.5, optical, n_pix=4000)),
            line_table(optical, "OptHiZ"),
            z_min=1.3,
            z_max=1.7,
            n_steps=2000,
        )
        assert isinstance(hi, Z.ZFindResult) and hi.best() is not None
        assert abs(hi.best().z - 1.5) < 0.005
        strong = Z.line_search(
            _prep(em_spectrum(0.5, GAL_EM, snr=500.0)),
            line_table(GAL_EM),
            z_min=0.3,
            z_max=0.7,
            n_steps=4000,
        )
        assert isinstance(strong, Z.ZFindResult) and strong.best() is not None
        assert strong.best().z_err < 0.001

    def test_mad_fallback_still_finds_z_and_warns(self) -> None:
        lines = {k: GAL_EM[k] for k in ("Halpha", "Hbeta", "[OIII]5007")}
        prep = _prep(em_spectrum(0.5, lines, provide_error=False))
        result = Z.line_search(prep, line_table(lines), z_min=0.3, z_max=0.7, n_steps=2000)
        assert isinstance(result, Z.ZFindResult)
        assert any("MAD" in w for w in result.warnings)
        assert result.best() is not None and abs(result.best().z - 0.5) < 0.002

    def test_all_lines_out_of_range_gives_nan_curve_and_no_solution(self) -> None:
        wave = np.linspace(3000, 5000, 500)
        flux = np.ones(500)
        prep = Z.preprocess(wave, flux, None, flux, fit_continuum=False)
        result = Z.line_search(
            prep, line_table({"Halpha": 6562.8}, "Halpha"), z_min=0.0, z_max=0.1, n_steps=100
        )
        assert isinstance(result, Z.ZFindResult)
        assert np.all(np.isnan(result.chi2_curves[0]["chi2"])) and result.best() is None

    def test_n_steps_progress_and_cancel(self) -> None:
        prep = _prep(em_spectrum(0.5, {"Halpha": 6562.8}))
        lines = line_table({"Halpha": 6562.8})
        for n in (500, 1000):
            result = Z.line_search(prep, lines, z_min=0.3, z_max=0.7, n_steps=n)
            assert len(result.z_array) == n and len(result.chi2_curves[0]["chi2"]) == n
        fractions: list[float] = []
        Z.line_search(
            prep,
            lines,
            z_min=0.3,
            z_max=0.7,
            n_steps=500,
            progress=lambda f, _m: fractions.append(f),
        )
        assert fractions[0] == 0.0 and fractions[-1] == 1.0 and fractions == sorted(fractions)
        with pytest.raises(InterruptedError):
            Z.line_search(prep, lines, z_min=0.3, z_max=0.7, n_steps=500, cancelled=lambda: True)

    def test_data_norm_modes(self) -> None:
        arrays = em_spectrum(0.5, GAL_EM)
        prep = _prep(arrays)
        for norm in ("subtract", "normalize", "raw"):
            result = Z.line_search(
                prep, line_table(GAL_EM), z_min=0.3, z_max=0.7, n_steps=1000, data_norm=norm
            )
            assert isinstance(result, Z.ZFindResult) and result.best() is not None
            assert abs(result.best().z - 0.5) < 0.005, norm
        masked = Z.line_search(
            prep,
            line_table(GAL_EM),
            z_min=0.3,
            z_max=0.7,
            n_steps=1000,
            wave_min=6000.0,
            wave_max=8000.0,
        )
        assert isinstance(masked, Z.ZFindResult) and masked.best() is not None


# --- line search: absorption -------------------------------------------------------------------


class TestLineSearchAbsorption:
    def test_structure(self) -> None:
        prep = _prep(abs_spectrum([{"z": 0.5, "lines": MGII}]))
        result = Z.line_search(
            prep, line_table(MGII, "TestAbs"), z_min=0.0, z_max=2.0, n_steps=3000, mode="absorption"
        )
        assert isinstance(result, Z.AbsorberResult)
        assert len(result.z_array) == 3000 == len(result.significance_curve)
        assert result.z_array[0] == pytest.approx(0.0) and result.z_array[-1] == pytest.approx(2.0)
        assert np.any(np.isfinite(result.significance_curve))
        assert all(isinstance(c, Z.AbsorberCandidate) for c in result.candidates)
        assert result.warnings == []

    @pytest.mark.parametrize(
        ("true_z", "z_min", "z_max"), [(0.5, 0.3, 0.8), (0.8, 0.5, 1.1), (1.2, 0.9, 1.5)]
    )
    def test_doublet_found_at_known_z(self, true_z: float, z_min: float, z_max: float) -> None:
        prep = _prep(abs_spectrum([{"z": true_z, "lines": MGII}]))
        result = Z.line_search(
            prep, line_table(MGII), z_min=z_min, z_max=z_max, n_steps=3000, mode="absorption"
        )
        assert isinstance(result, Z.AbsorberResult) and result.candidates
        assert abs(result.candidates[0].z - true_z) < 0.005

    def test_single_line_and_civ(self) -> None:
        single = {"MgII2796": 2796.35}
        prep = _prep(abs_spectrum([{"z": 0.8, "lines": single}]))
        result = Z.line_search(
            prep,
            line_table(single, "MgII_single"),
            z_min=0.5,
            z_max=1.1,
            n_steps=3000,
            mode="absorption",
        )
        assert isinstance(result, Z.AbsorberResult)
        assert abs(result.candidates[0].z - 0.8) < 0.005
        civ = Z.line_search(
            _prep(abs_spectrum([{"z": 1.5, "lines": CIVA}])),
            line_table(CIVA, "CIV"),
            z_min=1.2,
            z_max=1.8,
            n_steps=3000,
            mode="absorption",
        )
        assert isinstance(civ, Z.AbsorberResult)
        assert abs(civ.candidates[0].z - 1.5) < 0.01 and civ.candidates[0].linelist_name == "CIV"

    def test_multiple_absorbers_recovered_and_ranked(self) -> None:
        true_zs = [0.5, 1.2]
        prep = _prep(abs_spectrum([{"z": z, "lines": MGII} for z in true_zs]))
        result = Z.line_search(
            prep, line_table(MGII), z_min=0.0, z_max=2.0, n_steps=5000, mode="absorption"
        )
        assert isinstance(result, Z.AbsorberResult)
        recovered = [c.z for c in result.candidates]
        for true_z in true_zs:
            assert any(abs(rz - true_z) < 0.01 for rz in recovered), true_z
        assert all(c.significance > 5.0 for c in result.candidates[:2])
        sigs = [c.significance for c in result.candidates]
        assert sigs == sorted(sigs, reverse=True)
        three = Z.line_search(
            _prep(
                abs_spectrum(
                    [{"z": z, "lines": MGII, "depth": 4.0} for z in (0.4, 0.9, 1.5)],
                    wave_max=15000,
                    n_pix=6000,
                )
            ),
            line_table(MGII),
            z_min=0.0,
            z_max=2.0,
            n_steps=5000,
            mode="absorption",
        )
        assert isinstance(three, Z.AbsorberResult)
        for true_z in (0.4, 0.9, 1.5):
            assert any(abs(c.z - true_z) < 0.01 for c in three.candidates), true_z

    def test_candidate_properties_and_significance_peak(self) -> None:
        prep = _prep(abs_spectrum([{"z": 0.5, "lines": MGII}]))
        result = Z.line_search(
            prep, line_table(MGII, "TestAbs"), z_min=0.3, z_max=0.8, n_steps=3000, mode="absorption"
        )
        assert isinstance(result, Z.AbsorberResult)
        best = result.candidates[0]
        assert best.n_lines == 2 and set(best.lines_matched) == {"MgII2796", "MgII2803"}
        assert (
            best.significance > 0 and best.linelist_name == "TestAbs" and best.is_doublet is False
        )
        noise = [c.significance for c in result.candidates[2:]]
        if noise:
            assert best.significance > max(noise) * 2
        peak_z = result.z_array[np.nanargmax(result.significance_curve)]
        assert abs(peak_z - 0.5) < 0.01
        true_idx = int(np.argmin(np.abs(result.z_array - 0.5)))
        assert result.significance_curve[true_idx] > 0

    def test_mad_fallback_air_warning_and_empty_range(self) -> None:
        prep = _prep(abs_spectrum([{"z": 0.5, "lines": MGII}], provide_error=False))
        result = Z.line_search(
            prep, line_table(MGII), z_min=0.3, z_max=0.8, n_steps=2000, mode="absorption"
        )
        assert isinstance(result, Z.AbsorberResult)
        assert any("MAD" in w for w in result.warnings)
        assert abs(result.candidates[0].z - 0.5) < 0.01
        air = Z.line_search(
            _prep(abs_spectrum([{"z": 0.5, "lines": MGII}]), airvac="air"),
            line_table(MGII),
            z_min=0.3,
            z_max=0.8,
            n_steps=1000,
            mode="absorption",
        )
        assert any("vacuum" in w.lower() for w in air.warnings)
        wave = np.linspace(1200, 2000, 500)
        flux = 5.0 * np.ones(500)
        empty = Z.line_search(
            Z.preprocess(wave, flux, None, flux, fit_continuum=False),
            line_table(MGII),
            z_min=0.0,
            z_max=0.1,
            n_steps=100,
            mode="absorption",
        )
        assert isinstance(empty, Z.AbsorberResult)
        assert empty.candidates == [] and np.all(empty.significance_curve == 0.0)
        assert Z.absorbers_to_multispec(empty, [0]) == []
        adapted = Z.absorbers_to_multispec(result, [0])
        assert adapted == [
            {
                "zabs": result.candidates[0].z,
                "name": "Test",
                "label": f"z={result.candidates[0].z:.4f} (Test)",
            }
        ]


# --- picket fence ------------------------------------------------------------------------------


def _picket_case(
    z: float, lines: LineTable, sign: float, level: float, noise: float, seed: int = 42
):
    rng = np.random.default_rng(seed)
    wave = np.linspace(3800.0, 10000.0, 6200)
    flux = gaussian_lines(
        wave, np.full_like(wave, level), lines, z, amp_scale=2.0 if sign > 0 else 3.0, sign=sign
    )
    flux = flux + rng.normal(0.0, noise, size=len(wave))
    ivar = np.full_like(flux, 1.0 / noise**2)
    return wave, flux - level, ivar


class TestPicketFence:
    def test_emission_absorption_and_mixed_self_tests(self) -> None:
        em = curated("zfind_galaxy")
        em = LineTable(
            wave=em.wave[em.kind == "emission"],
            name=em.name[em.kind == "emission"],
            weight=em.weight[em.kind == "emission"],
            kind=em.kind[em.kind == "emission"],
            label="em",
        )
        wave, flux, ivar = _picket_case(0.35, em, +1, 1.0, 0.15)
        pf = PicketFenceZ(
            wave,
            flux,
            ivar,
            em,
            smooth_fwhm_pix=2.0,
            window_fwhm=1.5,
            use_error=True,
            resolution={"fwhm_ang": 4.0},
        )
        assert (
            pf.fwhm_pix == pytest.approx(4.0 / np.median(np.diff(wave))) and pf.window_pixels == 6
        )
        z_grid = np.linspace(0.0, 1.0, 10000)
        score = pf.run(z_grid)
        assert abs(float(z_grid[np.nanargmin(score)]) - 0.35) < 0.01
        cands = pf.match_peaks()
        assert cands and abs(cands[0]["z"] - 0.35) < 0.05 and cands[0]["n_matches"] >= 3

        igm = curated("zfind_igm")
        wave, flux, ivar = _picket_case(0.72, igm, -1, 5.0, 0.2)
        pf_abs = PicketFenceZ(
            wave, flux, ivar, igm, smooth_fwhm_pix=2.0, use_error=True, resolution={"fwhm_ang": 4.0}
        )
        z_grid = np.linspace(0.0, 2.0, 10000)
        score = pf_abs.run(z_grid)
        assert abs(float(z_grid[np.nanargmin(score)]) - 0.72) < 0.01

        mix = curated("zfind_galaxy")
        rng = np.random.default_rng(42)
        wave = np.linspace(3800.0, 10000.0, 6200)
        em_part = LineTable(
            *(getattr(mix, f)[mix.kind == "emission"] for f in ("wave", "name", "weight", "kind"))
        )
        ab_part = LineTable(
            *(getattr(mix, f)[mix.kind == "absorption"] for f in ("wave", "name", "weight", "kind"))
        )
        flux = gaussian_lines(wave, np.ones_like(wave), em_part, 0.18, 2.0, +1)
        flux = gaussian_lines(wave, flux, ab_part, 0.18, 2.0, -1) + rng.normal(0.0, 0.1, len(wave))
        pf_mix = PicketFenceZ(
            wave,
            flux - 1.0,
            np.full_like(flux, 100.0),
            mix,
            smooth_fwhm_pix=2.0,
            use_error=True,
            resolution={"fwhm_ang": 4.0},
        )
        z_grid = np.linspace(0.0, 0.6, 10000)
        assert abs(float(z_grid[np.nanargmin(pf_mix.run(z_grid))]) - 0.18) < 0.01

    def test_ivar_validation_and_resolution_helpers(self) -> None:
        wave = np.linspace(4000.0, 5000.0, 1001)
        assert to_fwhm_pix(wave, None) is None
        assert to_fwhm_pix(wave, {"fwhm_pix": 2.5}) == 2.5
        assert to_fwhm_pix(wave, {"fwhm_ang": 3.0}) == pytest.approx(3.0)
        assert to_fwhm_pix(wave, {"R": 4500.0}) == pytest.approx(1.0)
        assert to_fwhm_pix(wave, {"fwhm_kms": 299792.458 / 4500.0}) == pytest.approx(1.0)
        with pytest.raises(ValueError, match="Unrecognised resolution"):
            to_fwhm_pix(wave, {"bogus": 1.0})
        assert validate_ivar(np.ones(100)) is False
        assert validate_ivar(np.zeros(100)) is False
        assert validate_ivar(np.linspace(1.0, 2.0, 100)) is True
        flux = np.random.default_rng(1).normal(0, 0.1, 1001)
        lines = curated("zfind_em")
        placeholder = PicketFenceZ(wave, flux, np.ones_like(flux), lines)
        assert any("validation" in w for w in placeholder.warnings)
        forced = PicketFenceZ(wave, flux, np.ones_like(flux), lines, use_error=False)
        assert any("use_error=False" in w for w in forced.warnings)
        trusted = PicketFenceZ(
            wave, flux, np.ones_like(flux), lines, use_error=True, window_pixels=1
        )
        assert trusted.warnings == [] and trusted.window_pixels == 2
        assert set(trusted.detect_peaks()) == {"emission", "absorption"}

    def test_picket_fence_search_modes(self) -> None:
        arrays = em_spectrum(0.5, GAL_EM)
        prep = _prep(arrays)
        lines = line_table(GAL_EM, "TestEM")
        direct = Z.picket_fence_search(
            prep, lines, z_min=0.3, z_max=0.7, n_steps=2000, smooth_fwhm_pix=2.0
        )
        assert direct.best() is not None and abs(direct.best().z - 0.5) < 0.002
        assert (
            direct.chi2_curves[0]["label"] == "PicketFence:TestEM" and direct.best().n_features == 5
        )
        assert any("validation" in w for w in direct.warnings)
        mode_b = Z.picket_fence_search(
            prep, lines, z_min=0.3, z_max=0.7, n_steps=2000, pf_mode="detect_match", fwhm_ang=6.0
        )
        assert mode_b.best() is not None and mode_b.best().method.endswith(":ModeB")
        assert abs(mode_b.best().z - 0.5) < 0.02
        assert any(w.startswith("Mode B:") for w in mode_b.warnings)
        fractions: list[float] = []
        Z.picket_fence_search(
            prep,
            lines,
            z_min=0.3,
            z_max=0.7,
            n_steps=500,
            progress=lambda f, _m: fractions.append(f),
        )
        assert fractions and fractions[-1] == 1.0
        with pytest.raises(InterruptedError):
            Z.picket_fence_search(
                prep, lines, z_min=0.3, z_max=0.7, n_steps=500, cancelled=lambda: True
            )


# --- templates and PCA -------------------------------------------------------------------------


def test_template_loaders_and_ranges() -> None:
    assert Z.TEMPLATE_NAMES == ("EarlyType", "Intermediate", "LateTypeEmission", "Composite", "QSO")
    for name in Z.TEMPLATE_NAMES:
        wave, flux, pseudo = Z.load_template(name)
        assert (
            wave.ndim == 1
            and wave.shape == flux.shape == pseudo.shape
            and np.all(np.diff(wave) > 0)
        )
        assert np.all(np.abs(pseudo) > 0)
    with pytest.raises(ValueError, match="Unknown template"):
        Z.load_template("nope")
    assert Z.PCA_NAMES == ("galaxy", "qso_loz", "qso_hiz")
    for name in Z.PCA_NAMES:
        wave, vecs = Z.load_pca(name)
        assert vecs.ndim == 2 and vecs.shape[1] == wave.shape[0] <= 10858
    gal_wave, gal = Z.load_pca("galaxy")
    assert gal.shape == (10, 10858) and gal_wave[0] == pytest.approx(1228.07, abs=0.01)
    assert gal_wave[1] - gal_wave[0] == pytest.approx(0.9)
    with pytest.raises(ValueError, match="Unknown PCA"):
        Z.load_pca("nope")


def test_template_search_recovers_a_redshifted_template() -> None:
    # Build a "galaxy" from the LateTypeEmission template itself at z = 0.42 on an SDSS-like grid.
    t_wave, t_flux, _ = Z.load_template("LateTypeEmission")
    z_true = 0.42
    wave = np.linspace(3800.0, 9200.0, 3000)
    flux = np.interp(wave, t_wave * (1 + z_true), t_flux)
    rng = np.random.default_rng(7)
    noise = 0.02 * float(np.median(flux))
    flux = flux + rng.normal(0, noise, flux.size)
    prep = Z.preprocess(wave, flux, np.full_like(flux, noise), None, fit_continuum=True)
    result = Z.template_search(prep, "LateTypeEmission", z_min=0.2, z_max=0.7, n_steps=1000)
    assert result.best() is not None and abs(result.best().z - z_true) < 0.002
    assert result.best().method == "Template:LateTypeEmission" and result.best().n_features > 1000
    default_range = Z.template_search(prep, "EarlyType", n_steps=50)
    assert default_range.z_array[0] == 0.0 and default_range.z_array[-1] == 1.5
    multi = Z.multi_template_search(
        prep,
        ["LateTypeEmission", "EarlyType"],
        z_min=0.2,
        z_max=0.7,
        n_steps=400,
        template_res_kwargs={"fwhm_ang": 3.0},
    )
    assert [c["label"] for c in multi.chi2_curves] == ["LateTypeEmission", "EarlyType"]
    assert multi.best() is not None and abs(multi.best().z - z_true) < 0.005
    with pytest.raises(RuntimeError, match="All templates failed"):
        Z.multi_template_search(prep, ["nope"], n_steps=10)
    fractions: list[float] = []
    Z.multi_template_search(
        prep,
        ["QSO", "Composite"],
        z_min=0.2,
        z_max=0.4,
        n_steps=60,
        progress=lambda f, _m: fractions.append(f),
    )
    assert fractions and fractions[-1] == 1.0 and fractions == sorted(fractions)
    with pytest.raises(InterruptedError):
        Z.template_search(prep, "QSO", n_steps=100, cancelled=lambda: True)
    for norm in ("subtract", "raw"):
        r = Z.template_search(
            prep,
            "LateTypeEmission",
            z_min=0.3,
            z_max=0.5,
            n_steps=100,
            data_norm=norm,
            model_norm=norm,
            smooth_pixels=3,
        )
        assert isinstance(r, Z.ZFindResult)


def test_pca_search_recovers_an_eigenvector_mixture_and_reports_progress() -> None:
    p_wave, vecs = Z.load_pca("galaxy")
    z_true = 0.31
    wave = np.linspace(3800.0, 9200.0, 3000)
    model = 3.0 * vecs[0] + 0.5 * vecs[1] - 0.2 * vecs[2]
    flux = np.interp(wave, p_wave * (1 + z_true), model)
    scale = float(np.median(np.abs(flux)))
    rng = np.random.default_rng(3)
    flux = flux + rng.normal(0, 0.02 * scale, flux.size)
    prep = Z.preprocess(wave, flux, np.full_like(flux, 0.02 * scale), None, fit_continuum=True)
    fractions: list[float] = []
    result = Z.pca_search(
        prep,
        "galaxy",
        z_min=0.1,
        z_max=0.5,
        n_steps=400,
        progress=lambda f, _m: fractions.append(f),
    )
    assert result.best() is not None and abs(result.best().z - z_true) < 0.003
    assert result.best().method == "PCA:galaxy" and result.best().n_features == 10
    assert fractions[0] == 0.0 and fractions[-1] == 1.0 and len(fractions) > 10
    with pytest.raises(InterruptedError):
        Z.pca_search(prep, "galaxy", n_steps=100, cancelled=lambda: True)
    default_range = Z.pca_search(prep, "qso_hiz", n_steps=20)
    assert default_range.z_array[0] == 1.0 and default_range.z_array[-1] == 6.0
    multi = Z.multi_pca_search(
        prep, ["galaxy", "qso_loz"], n_steps=200, model_norm="subtract", pca_res_kwargs={"R": 2000}
    )
    assert [c["label"] for c in multi.chi2_curves] == ["PCA:galaxy", "PCA:qso_loz"]
    assert multi.z_array[0] == 0.0 and multi.z_array[-1] == 2.5
    # curves are interpolated onto the union grid: galaxy is NaN beyond z = 1.6
    galaxy_curve = multi.chi2_curves[0]["chi2"]
    assert np.isnan(galaxy_curve[-1]) and np.isfinite(galaxy_curve[0])
    with pytest.raises(RuntimeError, match="All PCA template sets failed"):
        Z.multi_pca_search(prep, ["nope"], n_steps=10)


def test_minima_and_curvature_helpers() -> None:
    z = np.linspace(0.0, 1.0, 101)
    chi2 = (z - 0.3) ** 2 * 100
    chi2[70] = -5.0
    top = Z.find_top_minima(z, chi2, n=3, min_dz=0.05)
    assert top[0] == 70 and abs(z[top[1]] - 0.3) < 0.011 and len(top) == 3
    assert Z.find_top_minima(z, np.full_like(z, np.nan)) == []
    assert Z.z_err_from_curvature(z, chi2, 30) == pytest.approx(np.sqrt(1.0 / 200.0), rel=0.05)
    assert np.isnan(Z.z_err_from_curvature(z, np.zeros_like(z), 30))
