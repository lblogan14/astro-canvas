"""Port of ``rbcodes.GUIs.zfind.picket_fence``: the weighted picket-fence redshift scanner.

Mode A (``PicketFenceZ.run``) accumulates a weighted matched-filter SNR at the predicted line
positions for every trial redshift (minima = best z). Mode B (``match_peaks``) detects peaks in
the smoothed flux and pairs them with the line list. Pure numpy/scipy, no GUI; takes the
``LineTable`` of :mod:`astro_canvas_rbcodes.kernels.zfind_linelists` instead of a DataFrame.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.ndimage import gaussian_filter1d
from scipy.stats import median_abs_deviation

from astro_canvas_rbcodes.kernels.zfind_linelists import LineTable

FloatArray = npt.NDArray[np.float64]
C_KMS = 299792.458
"""Speed of light used by ``_to_fwhm_pix`` (rbcodes' picket fence, not the 2.9979e5 of rb_spec)."""


def to_fwhm_pix(wave: FloatArray, resolution: Mapping[str, float] | None) -> float | None:
    """Convert a resolution specification to FWHM in pixels (``_to_fwhm_pix``).

    ``resolution`` holds exactly one of ``R``, ``fwhm_ang``, ``fwhm_pix``, ``fwhm_kms``; ``None``
    or an empty mapping means no resolution was given.
    """
    if not resolution:
        return None
    dwave = float(np.median(np.diff(wave)))
    lam_c = float(np.median(wave))
    if "fwhm_pix" in resolution:
        return float(resolution["fwhm_pix"])
    if "fwhm_ang" in resolution:
        return float(resolution["fwhm_ang"]) / dwave
    if "R" in resolution:
        return (lam_c / float(resolution["R"])) / dwave
    if "fwhm_kms" in resolution:
        return (float(resolution["fwhm_kms"]) / C_KMS * lam_c) / dwave
    raise ValueError(
        f"Unrecognised resolution keyword(s): {list(resolution)}. "
        "Use one of: R, fwhm_ang, fwhm_pix, fwhm_kms."
    )


def validate_ivar(ivar: FloatArray) -> bool:
    """True when ``ivar`` looks like a genuine error spectrum (``_validate_ivar``)."""
    good = ivar[np.isfinite(ivar) & (ivar > 0)]
    if len(good) < 10:
        return False
    return not np.std(good) / (np.median(good) + 1e-30) < 0.01


def mad_ivar(flux_smooth: FloatArray) -> FloatArray:
    """Uniform ivar from the MAD-STD of the smoothed flux (``_mad_ivar``)."""
    sigma = 1.4826 * float(median_abs_deviation(flux_smooth, nan_policy="omit"))
    if sigma == 0.0:
        finite = flux_smooth[np.isfinite(flux_smooth)]
        sigma = float(np.std(finite)) if len(finite) > 0 else 1.0
    sigma = max(sigma, 1e-30)
    return np.full_like(flux_smooth, 1.0 / sigma**2)


def _sigma_noise(flux_smooth: FloatArray) -> float:
    sigma = 1.4826 * float(median_abs_deviation(flux_smooth, nan_policy="omit"))
    if sigma == 0.0:
        finite = flux_smooth[np.isfinite(flux_smooth)]
        sigma = float(np.std(finite)) if len(finite) > 0 else 1.0
    return sigma


def detect_peaks_simple(
    wave: npt.ArrayLike,
    flux: npt.ArrayLike,
    *,
    smooth_fwhm_pix: float | None = 3.0,
    prominence_sigma: float = 3.0,
    width_scale_factor: float = 1.5,
) -> dict[str, Any]:
    """Emission/absorption peak windows without a line list (``detect_peaks_simple``)."""
    from scipy.signal import find_peaks  # noqa: PLC0415 - scipy.signal is slow to import

    w = np.asarray(wave, dtype=np.float64)
    flux_clean = np.nan_to_num(np.asarray(flux, dtype=np.float64), nan=0.0)
    if smooth_fwhm_pix is not None and smooth_fwhm_pix > 0:
        flux_smooth = gaussian_filter1d(flux_clean, sigma=float(smooth_fwhm_pix) / 2.355)
    else:
        flux_smooth = flux_clean.copy()
    prominence = prominence_sigma * _sigma_noise(flux_smooth)
    n = len(w)

    def windows(indices: npt.NDArray[np.intp], props: dict[str, Any]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for k, idx in enumerate(indices):
            half_w = (props["right_ips"][k] - props["left_ips"][k]) / 2.0 * width_scale_factor
            left = max(0, int(np.floor(idx - half_w)))
            right = min(n - 1, int(np.ceil(idx + half_w)))
            out.append((float(w[left]), float(w[right])))
        return out

    em_idx, em_props = find_peaks(flux_smooth, prominence=prominence, width=1)
    abs_idx, abs_props = find_peaks(-flux_smooth, prominence=prominence, width=1)
    return {
        "emission": windows(em_idx, em_props),
        "absorption": windows(abs_idx, abs_props),
        "peaks": {
            "emission": w[em_idx] if len(em_idx) > 0 else np.array([]),
            "absorption": w[abs_idx] if len(abs_idx) > 0 else np.array([]),
        },
    }


class PicketFenceZ:
    """Weighted picket-fence redshift scanner (``PicketFenceZ``).

    Args:
        wave: Observed wavelengths (Angstrom, increasing).
        flux: Continuum-subtracted or normalised flux.
        ivar: Inverse variance (0 for bad pixels).
        lines: The line list (weights default to 1, kinds to ``emission``).
        smooth_fwhm_pix: Gaussian pre-smoothing FWHM in pixels; ``None``/0 = off.
        window_fwhm: Window half-width in units of ``fwhm_pix`` when a resolution is given.
        window_pixels: Fallback half-window in pixels.
        use_error: ``True`` (use ``ivar``), ``False`` (MAD-STD ivar) or ``"auto"`` (validate).
        prominence_sigma: Mode B peak threshold in units of the MAD noise.
        resolution: One of ``R``, ``fwhm_ang``, ``fwhm_pix``, ``fwhm_kms`` (optional).
    """

    def __init__(
        self,
        wave: npt.ArrayLike,
        flux: npt.ArrayLike,
        ivar: npt.ArrayLike,
        lines: LineTable,
        *,
        smooth_fwhm_pix: float | None = None,
        window_fwhm: float = 1.5,
        window_pixels: int = 5,
        use_error: bool | str = "auto",
        prominence_sigma: float = 3.0,
        resolution: Mapping[str, float] | None = None,
    ) -> None:
        self.wave = np.asarray(wave, dtype=np.float64)
        flux_arr = np.asarray(flux, dtype=np.float64)
        ivar_arr = np.asarray(ivar, dtype=np.float64)
        self.warnings: list[str] = []

        self._rest = lines.wave.astype(np.float64)
        self._names = lines.name
        self._wts = lines.weight.astype(np.float64)
        self._types = lines.kind

        self.fwhm_pix = to_fwhm_pix(self.wave, resolution)
        if self.fwhm_pix is not None and self.fwhm_pix > 0:
            self._wp = max(2, int(round(window_fwhm * self.fwhm_pix)))
        else:
            self._wp = max(2, int(window_pixels))
        self._dwave = float(np.median(np.diff(self.wave)))

        flux_clean = np.nan_to_num(flux_arr, nan=0.0)
        if smooth_fwhm_pix is not None and smooth_fwhm_pix > 0:
            self.flux_smooth = gaussian_filter1d(flux_clean, sigma=float(smooth_fwhm_pix) / 2.355)
        else:
            self.flux_smooth = flux_clean.copy()

        ivar_clean = ivar_arr.copy()
        ivar_clean[~np.isfinite(flux_arr)] = 0.0
        if use_error is True:
            self.ivar = ivar_clean
        elif use_error is False:
            self.ivar = mad_ivar(self.flux_smooth)
            self.warnings.append("use_error=False: using MAD-STD uniform ivar.")
        elif validate_ivar(ivar_clean):
            self.ivar = ivar_clean
        else:
            self.ivar = mad_ivar(self.flux_smooth)
            self.warnings.append(
                "ivar failed validation (may be placeholder) — using MAD-STD uniform ivar."
            )

        self._sigma_noise = _sigma_noise(self.flux_smooth)
        self._prominence = prominence_sigma * self._sigma_noise

    @property
    def window_pixels(self) -> int:
        return self._wp

    def run(
        self,
        z_array: npt.ArrayLike,
        *,
        progress: Callable[[float, str | None], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> FloatArray:
        """Mode A: the direct scan (negative score, minima = best z; NaN with no line in range)."""
        z = np.asarray(z_array, dtype=np.float64)
        wave, flux_s, ivar = self.wave, self.flux_smooth, self.ivar
        rest, weights, types, wp = self._rest, self._wts, self._types, self._wp
        wmin = wave[0] + wp * self._dwave
        wmax = wave[-1] - wp * self._dwave
        score = np.full(len(z), np.nan)
        n = len(z)
        report_every = max(1, n // 50)
        for i, zi in enumerate(z):
            if i % report_every == 0:
                if cancelled is not None and cancelled():
                    raise InterruptedError("picket-fence scan cancelled")
                if progress is not None:
                    progress(i / n, None)
            obs_waves = rest * (1.0 + zi)
            in_range = (obs_waves > wmin) & (obs_waves < wmax)
            if not np.any(in_range):
                continue
            accum = 0.0
            w_total = 0.0
            w_used = 0.0
            for obs_w, wt, ltype in zip(
                obs_waves[in_range], weights[in_range], types[in_range], strict=True
            ):
                w_total += wt
                pix = int(np.searchsorted(wave, obs_w))
                pix = min(max(pix, wp), len(wave) - wp - 1)
                fw = flux_s[pix - wp : pix + wp + 1]
                iv = ivar[pix - wp : pix + wp + 1]
                iv_pos = iv[iv > 0]
                if len(iv_pos) < 2:
                    continue
                iv_sum = float(np.sum(iv_pos))
                s = float(np.sum(fw * iv))
                if ltype == "emission" and s <= 0.0:
                    continue
                if ltype == "absorption" and s >= 0.0:
                    continue
                accum -= wt * abs(s) / np.sqrt(iv_sum)
                w_used += wt
            if w_used > 0.0:
                score[i] = accum / np.sqrt(w_total)
        if progress is not None:
            progress(1.0, None)
        return score

    def detect_peaks(self) -> dict[str, FloatArray]:
        """Emission peaks and absorption troughs in the smoothed flux (``detect_peaks``)."""
        from scipy.signal import find_peaks  # noqa: PLC0415 - scipy.signal is slow to import

        em_idx, _ = find_peaks(self.flux_smooth, prominence=self._prominence)
        abs_idx, _ = find_peaks(-self.flux_smooth, prominence=self._prominence)
        return {
            "emission": self.wave[em_idx] if len(em_idx) > 0 else np.array([]),
            "absorption": self.wave[abs_idx] if len(abs_idx) > 0 else np.array([]),
        }

    def match_peaks(self, z_tol: float = 0.005) -> list[dict[str, Any]]:
        """Mode B: pair detected peaks with the line list and rank the z candidates."""
        peaks = self.detect_peaks()
        em_peaks, abs_peaks = peaks["emission"], peaks["absorption"]
        wave = self.wave
        tol = 2.0 * self._dwave

        z_pool: list[float] = []
        for pk_arr, ltype in ((em_peaks, "emission"), (abs_peaks, "absorption")):
            mask = self._types == ltype
            if not np.any(mask) or len(pk_arr) == 0:
                continue
            for obs_w in pk_arr:
                for rw in self._rest[mask]:
                    zc = float(obs_w) / float(rw) - 1.0
                    if zc >= 0.0:
                        z_pool.append(zc)
        if not z_pool:
            return []

        results: list[dict[str, Any]] = []
        seen: set[float] = set()
        for zc in z_pool:
            key = round(zc, 3)
            if key in seen:
                continue
            seen.add(key)
            matched: list[dict[str, Any]] = []
            score = 0.0
            for rw, nm, wt, lt in zip(self._rest, self._names, self._wts, self._types, strict=True):
                obs_w = rw * (1.0 + zc)
                if obs_w < wave[0] or obs_w > wave[-1]:
                    continue
                pk_arr = em_peaks if lt == "emission" else abs_peaks
                if len(pk_arr) == 0:
                    continue
                if float(np.min(np.abs(pk_arr - obs_w))) <= tol:
                    matched.append({"name": str(nm), "wave_obs": float(obs_w)})
                    score += float(wt)
            if matched:
                results.append(
                    {"z": zc, "n_matches": len(matched), "score": score, "lines": matched}
                )

        results.sort(key=lambda r: r["score"], reverse=True)
        deduped: list[dict[str, Any]] = []
        for r in results:
            if not any(abs(r["z"] - d["z"]) < z_tol for d in deduped):
                deduped.append(r)
        return deduped


__all__ = [
    "C_KMS",
    "PicketFenceZ",
    "detect_peaks_simple",
    "mad_ivar",
    "to_fwhm_pix",
    "validate_ivar",
]
