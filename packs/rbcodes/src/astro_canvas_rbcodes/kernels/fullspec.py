"""Port of ``rbcodes.IGM.fit_continuum_full_spec`` (chunked, BIC-optimised, blended continuum).

``fit_quasar_continuum`` takes arrays instead of a file, reports progress through an optional
callback instead of printing, and never writes FITS or figures. Everything else follows the
upstream code, including the chunk layout, the cosine tapers and the gap interpolation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import numpy.typing as npt

from astro_canvas_rbcodes.kernels.contfit import fit_optimal_polynomial

FloatArray = npt.NDArray[np.float64]
Chunk = tuple[FloatArray, FloatArray, FloatArray, int, int]


def _expand_short(start_idx: int, end_idx: int, lo: int, hi: int) -> tuple[int, int]:
    while end_idx - start_idx < 10 and (start_idx > lo or end_idx < hi):
        if start_idx > lo:
            start_idx -= 1
        if end_idx < hi:
            end_idx += 1
    return start_idx, end_idx


def generate_full_coverage_chunks(
    wave: FloatArray,
    flux: FloatArray,
    error: FloatArray,
    window_size: float = 100,
    overlap: float = 30,
    method: str = "uniform",
    wmin: float | None = None,
    wmax: float | None = None,
) -> list[Chunk]:
    """Overlapping chunks ``(wave, flux, error, start_idx, end_idx)`` covering ``[wmin, wmax]``."""
    if wmin is None:
        wmin = float(np.min(wave))
    if wmax is None:
        wmax = float(np.max(wave))
    wmin = max(wmin, float(np.min(wave)))
    wmax = min(wmax, float(np.max(wave)))
    range_indices = np.where((wave >= wmin) & (wave <= wmax))[0]
    if len(range_indices) == 0:
        raise ValueError(f"No data points found in wavelength range {wmin}-{wmax}")
    range_wave = wave[range_indices]
    range_flux = flux[range_indices]
    wave_min = float(np.min(range_wave))
    wave_max = float(np.max(range_wave))
    full_range = wave_max - wave_min
    effective_window = window_size - overlap
    n_chunks = int(np.ceil(full_range / effective_window)) if effective_window > 0 else 1
    min_chunks = min(3, max(1, int(full_range / 20)))
    n_chunks = max(min_chunks, n_chunks)
    lo, hi = int(range_indices[0]), int(range_indices[-1])
    chunks: list[Chunk] = []

    def add(start_idx: int, end_idx: int) -> None:
        chunks.append(
            (
                wave[start_idx : end_idx + 1],
                flux[start_idx : end_idx + 1],
                error[start_idx : end_idx + 1],
                start_idx,
                end_idx,
            )
        )

    if method == "uniform":
        if n_chunks > 1:
            effective_range = full_range - window_size
            step = effective_range / (n_chunks - 1) if effective_range > 0 else 0
            chunk_starts = [wave_min + i * step for i in range(n_chunks)]
        else:
            chunk_starts = [wave_min]
        for i, start_wave in enumerate(chunk_starts):
            end_wave = wave_max if i == n_chunks - 1 else start_wave + window_size
            start_idx = int(max(lo, int(np.argmin(np.abs(wave - start_wave)))))
            end_idx = int(min(hi, int(np.argmin(np.abs(wave - end_wave)))))
            if end_idx - start_idx < 10:
                start_idx, end_idx = _expand_short(start_idx, end_idx, lo, hi)
            add(start_idx, end_idx)
    elif method == "features":
        window = max(21, int(len(range_wave) / 50))
        window = window + 1 if window % 2 == 0 else window
        padded = np.pad(range_flux, (window // 2, window // 2), mode="edge")
        std_array = np.zeros_like(range_flux)
        for i in range(len(range_flux)):
            std_array[i] = np.std(padded[i : i + window])
        smooth_window = int(window / 2)
        if smooth_window > 1:
            kernel = np.ones(smooth_window) / smooth_window
            std_array = np.convolve(std_array, kernel, mode="same")
        feature_indices = np.where(std_array > np.median(std_array) * 1.5)[0]
        if len(feature_indices) < n_chunks:
            return generate_full_coverage_chunks(
                wave, flux, error, window_size, overlap, method="uniform", wmin=wmin, wmax=wmax
            )
        step = len(feature_indices) / n_chunks
        centers = [int(feature_indices[int(i * step)]) for i in range(n_chunks)]
        if 0 not in centers:
            centers = [0, *centers]
        if len(range_wave) - 1 not in centers:
            centers.append(len(range_wave) - 1)
        centers.sort()
        for center_idx in centers:
            center_wave = range_wave[center_idx]
            start_wave = max(wave_min, center_wave - window_size / 2)
            end_wave = min(wave_max, center_wave + window_size / 2)
            start_idx = max(lo, int(np.argmin(np.abs(wave - start_wave))))
            end_idx = min(hi, int(np.argmin(np.abs(wave - end_wave))))
            if end_idx - start_idx < 10:
                start_idx, end_idx = _expand_short(start_idx, end_idx, lo, hi)
            add(start_idx, end_idx)
    else:
        raise ValueError(f"Unknown chunk selection method: {method}")

    coverage = np.zeros_like(range_wave, dtype=bool)
    for _, _, _, start_idx, end_idx in chunks:
        a = max(0, start_idx - lo)
        b = min(len(range_wave) - 1, end_idx - lo)
        if a <= b:
            coverage[a : b + 1] = True
    while not np.all(coverage):
        gap_starts: list[int] = []
        gap_ends: list[int] = []
        in_gap = False
        for i, covered in enumerate(coverage):
            if not covered and not in_gap:
                gap_starts.append(i)
                in_gap = True
            elif covered and in_gap:
                gap_ends.append(i - 1)
                in_gap = False
        if in_gap:
            gap_ends.append(len(coverage) - 1)
        lengths = [gap_ends[i] - gap_starts[i] + 1 for i in range(len(gap_starts))]
        largest = int(np.argmax(lengths))
        start_idx = lo + gap_starts[largest]
        end_idx = lo + gap_ends[largest]
        overlap_points = int(min(20, lengths[largest] * 0.2))
        start_idx = max(lo, start_idx - overlap_points)
        end_idx = min(hi, end_idx + overlap_points)
        add(start_idx, end_idx)
        coverage[max(0, start_idx - lo) : min(len(range_wave) - 1, end_idx - lo) + 1] = True
    return chunks


def create_cosine_taper_weights(length: int) -> FloatArray:
    """Weights that fall to zero over the outer 15 % of a chunk on each side."""
    taper_length = int(length * 0.3 / 2)
    weights = np.ones(length)
    if length > 4 and taper_length > 1:
        for i in range(taper_length):
            weights[i] = 0.5 * (1 - np.cos(np.pi * i / taper_length))
            weights[-(i + 1)] = 0.5 * (1 - np.cos(np.pi * i / taper_length))
    return weights


def fit_quasar_continuum(
    wave: npt.ArrayLike,
    flux: npt.ArrayLike,
    error: npt.ArrayLike | None = None,
    *,
    window_size: float = 100.0,
    overlap_fraction: float = 0.3,
    method: str = "uniform",
    wmin: float | None = None,
    wmax: float | None = None,
    min_order: int = 2,
    max_order: int = 6,
    maxiter: int = 25,
    sigma: float = 3.0,
    use_weights: bool = True,
    progress: Callable[[float, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Continuum of a whole spectrum from blended per-chunk BIC-optimal polynomial fits.

    Returns ``wave``, ``flux``, ``error``, ``continuum``, ``normalized_flux`` and
    ``chunk_results`` (``chunk_id``, ``wavelength_range``, ``best_order``, ``bic_results``,
    ``std_error``, ``indices``). Pixels outside ``[wmin, wmax]`` keep a NaN continuum.
    """
    wave_arr = np.asarray(wave, dtype=np.float64)
    flux_arr = np.asarray(flux, dtype=np.float64)
    if wave_arr.size != flux_arr.size:
        raise ValueError("Wavelength and flux arrays must have the same length")
    if error is None:
        error_arr = np.ones_like(flux_arr) * 0.1 * float(np.median(flux_arr))
    else:
        error_arr = np.asarray(error, dtype=np.float64)
        if error_arr.size != flux_arr.size:
            raise ValueError("Error array must have the same length as flux array")

    lo = float(np.min(wave_arr)) if wmin is None else max(wmin, float(np.min(wave_arr)))
    hi = float(np.max(wave_arr)) if wmax is None else min(wmax, float(np.max(wave_arr)))
    chunks = generate_full_coverage_chunks(
        wave_arr,
        flux_arr,
        error_arr,
        window_size=window_size,
        overlap=window_size * overlap_fraction,
        method=method,
        wmin=lo,
        wmax=hi,
    )
    full_continuum = np.zeros_like(flux_arr)
    weights = np.zeros_like(flux_arr)
    chunk_results: list[dict[str, Any]] = []
    for i, (wave_chunk, flux_chunk, error_chunk, start_idx, end_idx) in enumerate(chunks):
        if cancelled is not None and cancelled():
            raise InterruptedError("continuum fit cancelled")
        if progress is not None:
            progress(i / len(chunks), f"chunk {i + 1}/{len(chunks)}")
        result = fit_optimal_polynomial(
            wave_chunk,
            flux_chunk,
            error=error_chunk,
            min_order=min_order,
            max_order=max_order,
            maxiter=maxiter,
            sigma=sigma,
            use_weights=use_weights,
        )
        best_fit = result["continuum"]
        chunk_results.append(
            {
                "chunk_id": i + 1,
                "wavelength_range": (float(wave_chunk[0]), float(wave_chunk[-1])),
                "best_order": result["best_order"],
                "bic_results": result["bic_results"],
                "std_error": result["fit_error"],
                "indices": (start_idx, end_idx),
            }
        )
        taper = create_cosine_taper_weights(len(wave_chunk))
        full_continuum[start_idx : end_idx + 1] += best_fit * taper
        weights[start_idx : end_idx + 1] += taper

    in_range = (wave_arr >= lo) & (wave_arr <= hi)
    zero = np.where((weights == 0) & in_range)[0]
    if zero.size:
        from scipy.interpolate import interp1d  # noqa: PLC0415 - lazy: heavy import

        valid = np.where(weights > 0)[0]
        interp = interp1d(
            wave_arr[valid],
            full_continuum[valid] / weights[valid],
            bounds_error=False,
            fill_value="extrapolate",
        )
        full_continuum[zero] = interp(wave_arr[zero])
        weights[zero] = 1.0
    with np.errstate(all="ignore"):
        continuum = np.where(weights > 0, full_continuum / weights, np.nan)
        normalized = flux_arr / continuum
    if progress is not None:
        progress(1.0, "done")
    return {
        "wave": wave_arr,
        "flux": flux_arr,
        "error": error_arr,
        "continuum": continuum,
        "normalized_flux": normalized,
        "chunk_results": chunk_results,
    }


__all__ = ["create_cosine_taper_weights", "fit_quasar_continuum", "generate_full_coverage_chunks"]
