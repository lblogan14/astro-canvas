"""Ports of ``rbcodes.GUIs.ifuviewer.processing`` — cube collapses, apertures, moment maps.

Line-by-line ports of ``cube_collapse.build_whitelight`` / ``build_continuum_sub``,
``aperture_extract.{extract_with_method, extract_aperture, extract_variance_weighted,
subtract_background}`` and ``moment_maps.{velocity_array, moment0, moment1, moment2, sky_stats,
compute_snr_map, subtract_linear_continuum}`` without their GUI. Everything takes and returns plain
numpy, and every reduction is NaN-aware exactly as upstream is.

The mask builders here work on the ``astro.Region2D`` shapes rather than upstream's
``(cx, cy, radius)`` triples; ``rbcodes``' own ``make_circular_mask`` / ``make_annulus_mask``
convention (a pixel is inside when its centre is within the radius) is preserved, so masks match
element for element.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Sequence
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

C_KMS = 2.998e5
"""Speed of light in km/s, as ``moment_maps.C_KMS`` defines it (not the CODATA value)."""

CollapseMethod = Literal["mean", "sum", "median"]
ExtractMethod = Literal["sum", "mean", "median", "variance_weighted"]
BackgroundMethod = Literal["mean", "median"]

Float2D = npt.NDArray[np.float64]
Bool2D = npt.NDArray[np.bool_]

_REDUCERS: dict[str, Callable[..., Any]] = {
    "mean": np.nanmean,
    "sum": np.nansum,
    "median": np.nanmedian,
}
"""The three NaN-aware reductions every collapse and extraction in rb_ifuview offers."""


def _band(wave: npt.NDArray[np.float64], wmin: float | None, wmax: float | None) -> Bool2D:
    mask = np.ones(len(wave), dtype=bool)
    if wmin is not None:
        mask &= wave >= wmin
    if wmax is not None:
        mask &= wave <= wmax
    return mask


# --- collapses ---------------------------------------------------------------------------------


def build_whitelight(
    flux: npt.ArrayLike,
    wave: npt.ArrayLike,
    wmin: float | None = None,
    wmax: float | None = None,
    method: CollapseMethod = "mean",
) -> Float2D:
    """Collapse ``flux[nz, ny, nx]`` along the spectral axis over ``[wmin, wmax]``.

    Args:
        flux: The cube.
        wave: Wavelength axis, same length as ``flux.shape[0]``.
        wmin: Lower wavelength limit (``None``: no limit).
        wmax: Upper wavelength limit (``None``: no limit).
        method: ``mean``, ``sum`` or ``median``, all NaN-aware.

    Returns:
        The collapsed ``[ny, nx]`` image.
    """
    cube = np.asarray(flux)
    axis = np.asarray(wave, dtype=np.float64)
    mask = _band(axis, wmin, wmax)
    if not mask.any():
        raise ValueError(f"no wavelength channels in [{wmin}, {wmax}]")
    reducer = _REDUCERS.get(method)
    if reducer is None:
        raise ValueError(f"unknown method {method!r}; use 'mean', 'sum' or 'median'")
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.asarray(reducer(cube[mask, :, :], axis=0), dtype=np.float64)


def build_continuum_sub(
    flux: npt.ArrayLike,
    wave: npt.ArrayLike,
    wmin: float,
    wmax: float,
    c1min: float,
    c1max: float,
    c2min: float | None = None,
    c2max: float | None = None,
    method: CollapseMethod = "mean",
) -> Float2D:
    """On-band image minus the mean of one or two continuum windows (upstream Phase 8)."""
    nb = build_whitelight(flux, wave, wmin, wmax, method)
    cont = build_whitelight(flux, wave, c1min, c1max, method)
    if c2min is not None and c2max is not None:
        cont = (cont + build_whitelight(flux, wave, c2min, c2max, method)) / 2.0
    return nb - cont


def subtract_linear_continuum(
    flux: npt.ArrayLike,
    wave: npt.ArrayLike,
    bcont_min: float,
    bcont_max: float,
    rcont_min: float,
    rcont_max: float,
) -> npt.NDArray[np.float64]:
    """Per-spaxel linear baseline anchored on the blue and red continuum windows."""
    cube = np.asarray(flux, dtype=np.float64)
    axis = np.asarray(wave, dtype=np.float64)
    bmask = _band(axis, bcont_min, bcont_max)
    rmask = _band(axis, rcont_min, rcont_max)
    if not bmask.any():
        raise ValueError(f"blue continuum window [{bcont_min}, {bcont_max}] has no channels")
    if not rmask.any():
        raise ValueError(f"red continuum window [{rcont_min}, {rcont_max}] has no channels")
    lambda_b = float(axis[bmask].mean())
    lambda_r = float(axis[rmask].mean())
    if lambda_b >= lambda_r:
        raise ValueError("the blue continuum window must sit blueward of the red one")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        flux_b = np.nanmean(cube[bmask], axis=0)
        flux_r = np.nanmean(cube[rmask], axis=0)
    slope = (flux_r - flux_b) / (lambda_r - lambda_b)
    intercept = flux_b - slope * lambda_b
    continuum = slope[np.newaxis] * axis[:, np.newaxis, np.newaxis] + intercept[np.newaxis]
    return np.asarray(cube - continuum, dtype=np.float64)


# --- masks -------------------------------------------------------------------------------------


def circle_mask(ny: int, nx: int, cx: float, cy: float, radius: float) -> Bool2D:
    """Pixels whose centre lies within ``radius`` of ``(cx, cy)`` (``make_circular_mask``)."""
    y, x = np.mgrid[0:ny, 0:nx]
    return np.asarray((x - cx) ** 2 + (y - cy) ** 2 <= radius**2)


def annulus_mask(ny: int, nx: int, cx: float, cy: float, inner: float, outer: float) -> Bool2D:
    """Pixels in the annulus ``[inner, outer]`` around ``(cx, cy)`` (``make_annulus_mask``)."""
    y, x = np.mgrid[0:ny, 0:nx]
    r2 = (x - cx) ** 2 + (y - cy) ** 2
    return np.asarray((r2 >= inner**2) & (r2 <= outer**2))


def box_mask(
    ny: int, nx: int, cx: float, cy: float, width: float, height: float, angle: float = 0.0
) -> Bool2D:
    """Pixels inside a ``width`` x ``height`` box centred on ``(cx, cy)``, rotated by ``angle``.

    ``angle`` is degrees counter-clockwise, matching ds9's ``box(...)`` fifth argument and
    ``spatial_mask._mask_box``.
    """
    radians = np.deg2rad(angle)
    ca, sa = np.cos(radians), np.sin(radians)
    y, x = np.mgrid[0:ny, 0:nx]
    dx, dy = x - cx, y - cy
    xr = dx * ca + dy * sa
    yr = -dx * sa + dy * ca
    return np.asarray((np.abs(xr) <= width / 2) & (np.abs(yr) <= height / 2))


def polygon_mask(ny: int, nx: int, vertices: Sequence[tuple[float, float]]) -> Bool2D:
    """Pixels inside the closed polygon through ``vertices`` (``spatial_mask._mask_polygon``).

    Upstream rasterizes with ``matplotlib.path.Path.contains_points``; matplotlib is an rbcodes
    dependency, not one of this pack's, so it is used when importable and a vectorized even-odd
    ray cast (PNPOLY) takes over otherwise. The two agree everywhere except, in principle, on
    pixel centres that fall exactly on an edge.
    """
    if len(vertices) < 3:
        return np.zeros((ny, nx), dtype=bool)
    y, x = np.mgrid[0:ny, 0:nx]
    try:
        from matplotlib.path import Path  # noqa: PLC0415 - optional, see the docstring
    except ImportError:
        return _pnpoly(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64), vertices)
    path = Path([*vertices, vertices[0]], closed=True)
    points = np.column_stack([x.ravel().astype(float), y.ravel().astype(float)])
    return np.asarray(path.contains_points(points).reshape(ny, nx))


def _pnpoly(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    vertices: Sequence[tuple[float, float]],
) -> Bool2D:
    """Even-odd point-in-polygon test over a grid (the classic PNPOLY crossing count)."""
    inside = np.zeros(x.shape, dtype=bool)
    n = len(vertices)
    for i in range(n):
        x0, y0 = vertices[i]
        x1, y1 = vertices[(i + 1) % n]
        if y0 == y1:
            continue
        straddles = (y0 > y) != (y1 > y)
        with np.errstate(all="ignore"):
            crossing = (x1 - x0) * (y - y0) / (y1 - y0) + x0
        inside ^= straddles & (x < crossing)
    return inside


# --- extraction --------------------------------------------------------------------------------


def extract_with_method(
    flux: npt.ArrayLike, mask: npt.ArrayLike, method: CollapseMethod = "sum"
) -> npt.NDArray[np.float64]:
    """Collapse the spaxels under ``mask`` into one spectrum (``sum``/``mean``/``median``)."""
    cube = np.asarray(flux)
    picked = cube[:, np.asarray(mask, dtype=bool)]
    reducer = _REDUCERS.get(method)
    if reducer is None:
        raise ValueError(f"unknown method {method!r}; use 'sum', 'mean' or 'median'")
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.asarray(reducer(picked, axis=1), dtype=np.float64)


def extract_aperture(
    flux: npt.ArrayLike, var: npt.ArrayLike | None, mask: npt.ArrayLike
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64] | None]:
    """Summed extraction over a spatial mask; the error is ``sqrt`` of the summed variance."""
    cube = np.asarray(flux)
    picked = np.asarray(mask, dtype=bool)
    with np.errstate(all="ignore"):
        spec = np.asarray(np.nansum(cube[:, picked], axis=1), dtype=np.float64)
        if var is None:
            return spec, None
        err = np.sqrt(np.nansum(np.asarray(var)[:, picked], axis=1))
    return spec, np.asarray(err, dtype=np.float64)


def extract_variance_weighted(
    flux: npt.ArrayLike, var: npt.ArrayLike | None, mask: npt.ArrayLike
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Quasi-optimal extraction: each spaxel weighted by ``1 / variance`` per channel."""
    if var is None:
        raise ValueError("variance-weighted extraction needs a variance cube")
    picked = np.asarray(mask, dtype=bool)
    f = np.asarray(flux)[:, picked]
    v = np.asarray(var)[:, picked]
    with np.errstate(all="ignore"):
        w = np.where(v > 0, 1.0 / v, 0.0)
        w_sum = np.nansum(w, axis=1)
        spec = np.where(w_sum > 0, np.nansum(f * w, axis=1) / w_sum, np.nan)
        err = np.where(w_sum > 0, 1.0 / np.sqrt(w_sum), np.nan)
    return np.asarray(spec, dtype=np.float64), np.asarray(err, dtype=np.float64)


def subtract_background(
    spec: npt.ArrayLike,
    flux: npt.ArrayLike,
    bg_mask: npt.ArrayLike,
    method: BackgroundMethod = "mean",
) -> npt.NDArray[np.float64]:
    """Subtract the per-pixel background level of ``bg_mask`` from an extracted spectrum."""
    picked = np.asarray(flux)[:, np.asarray(bg_mask, dtype=bool)]
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        level = np.nanmedian(picked, axis=1) if method == "median" else np.nanmean(picked, axis=1)
    return np.asarray(np.asarray(spec, dtype=np.float64) - level, dtype=np.float64)


# --- moment maps -------------------------------------------------------------------------------


def velocity_array(wave: npt.ArrayLike, lambda_rest: float) -> npt.NDArray[np.float64]:
    """Wavelengths as velocities in km/s relative to ``lambda_rest`` (same units as ``wave``)."""
    axis = np.asarray(wave, dtype=np.float64)
    return np.asarray(C_KMS * (axis - lambda_rest) / lambda_rest)


def moment0(flux: npt.ArrayLike, wave: npt.ArrayLike, wmin: float, wmax: float) -> Float2D:
    """Integrated flux over ``[wmin, wmax]`` (flux times wavelength)."""
    cube, axis, mask = _window(flux, wave, wmin, wmax)
    dw = np.gradient(axis[mask])
    with np.errstate(all="ignore"):
        return np.asarray(np.nansum(cube[mask] * dw[:, None, None], axis=0), dtype=np.float64)


def moment1(
    flux: npt.ArrayLike, wave: npt.ArrayLike, wmin: float, wmax: float, lambda_rest: float
) -> Float2D:
    """Flux-weighted velocity centroid in km/s; spaxels with ``M0 <= 0`` become NaN."""
    cube, axis, mask = _window(flux, wave, wmin, wmax)
    vel = velocity_array(axis[mask], lambda_rest)
    dw = np.gradient(axis[mask])
    with np.errstate(all="ignore"):
        m0 = np.nansum(cube[mask] * dw[:, None, None], axis=0)
        m1 = np.nansum(cube[mask] * vel[:, None, None] * dw[:, None, None], axis=0)
        return np.asarray(np.where(m0 > 0, m1 / m0, np.nan), dtype=np.float64)


def moment2(
    flux: npt.ArrayLike, wave: npt.ArrayLike, wmin: float, wmax: float, lambda_rest: float
) -> Float2D:
    """Flux-weighted velocity dispersion in km/s; spaxels with ``M0 <= 0`` become NaN."""
    cube, axis, mask = _window(flux, wave, wmin, wmax)
    vel = velocity_array(axis[mask], lambda_rest)
    dw = np.gradient(axis[mask])
    with np.errstate(all="ignore"):
        m0 = np.nansum(cube[mask] * dw[:, None, None], axis=0)
        m1 = moment1(cube, axis, wmin, wmax, lambda_rest)
        dv2 = (vel[:, None, None] - m1[None]) ** 2
        m2 = np.nansum(cube[mask] * dv2 * dw[:, None, None], axis=0)
        return np.asarray(np.where(m0 > 0, np.sqrt(np.abs(m2 / m0)), np.nan), dtype=np.float64)


def moment_map(
    flux: npt.ArrayLike,
    wave: npt.ArrayLike,
    wmin: float,
    wmax: float,
    order: int,
    lambda_rest: float | None = None,
) -> Float2D:
    """Moment of the given ``order`` (0, 1 or 2); orders 1 and 2 need ``lambda_rest``."""
    if order == 0:
        return moment0(flux, wave, wmin, wmax)
    if order in (1, 2):
        if lambda_rest is None:
            raise ValueError("lambda_rest is required for moment order 1 and 2")
        if order == 1:
            return moment1(flux, wave, wmin, wmax, lambda_rest)
        return moment2(flux, wave, wmin, wmax, lambda_rest)
    raise ValueError(f"unsupported moment order {order}; use 0, 1 or 2")


def sky_stats(
    flux: npt.ArrayLike,
    wave: npt.ArrayLike,
    sky_mask: npt.ArrayLike,
    wmin: float | None = None,
    wmax: float | None = None,
) -> dict[str, Any] | None:
    """Background statistics over the sky spaxels (``None`` when the mask is empty)."""
    picked = np.asarray(sky_mask, dtype=bool)
    n_spaxels = int(picked.sum())
    if n_spaxels == 0:
        return None
    cube = np.asarray(flux)
    axis = np.asarray(wave, dtype=np.float64)
    sky = cube[:, picked]
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        result: dict[str, Any] = {
            "n_spaxels": n_spaxels,
            "mean": float(np.nanmean(sky)),
            "median": float(np.nanmedian(sky)),
            "sigma": float(np.nanmedian(np.nanstd(sky, axis=1))),
        }
        if wmin is not None and wmax is not None:
            channels = _band(axis, wmin, wmax)
            if channels.any():
                dw = np.gradient(axis[channels])
                rms = np.nanstd(cube[channels][:, picked], axis=1)
                result["sigma_m0"] = float(np.sqrt(np.nansum((rms * dw) ** 2)))
                result["n_channels"] = int(channels.sum())
    return result


def compute_snr_map(
    m0: npt.ArrayLike,
    flux: npt.ArrayLike,
    wave: npt.ArrayLike,
    wmin: float,
    wmax: float,
    var: npt.ArrayLike | None = None,
    sky_mask: npt.ArrayLike | None = None,
    cont1: tuple[float, float] | None = None,
    cont2: tuple[float, float] | None = None,
) -> Float2D | None:
    """Per-spaxel SNR of a moment-0 map, from the variance cube, a sky region or the continuum.

    Returns ``None`` when none of the three noise estimates is available (upstream behaviour).
    """
    cube = np.asarray(flux)
    axis = np.asarray(wave, dtype=np.float64)
    line = _band(axis, wmin, wmax)
    if not line.any():
        return None
    dw = np.gradient(axis[line])
    n_channels = int(line.sum())

    if var is not None:
        with np.errstate(all="ignore"):
            sigma = np.sqrt(np.nansum(np.asarray(var)[line] * dw[:, None, None] ** 2, axis=0))
    elif sky_mask is not None and np.asarray(sky_mask, dtype=bool).any():
        picked = np.asarray(sky_mask, dtype=bool)
        with np.errstate(all="ignore"):
            rms = np.nanstd(cube[line][:, picked], axis=1)
            sigma = np.sqrt(
                np.nansum((rms[:, None, None] * dw[:, None, None]) ** 2, axis=0),
            )
    elif cont1 is not None:
        cmask = _band(axis, cont1[0], cont1[1])
        if cont2 is not None:
            cmask |= _band(axis, cont2[0], cont2[1])
        if not cmask.any():
            return None
        with np.errstate(all="ignore"):
            rms = np.nanstd(cube[cmask], axis=0)
            sigma = rms * np.sqrt(n_channels) * float(np.mean(np.abs(dw)))
    else:
        return None

    with np.errstate(all="ignore"):
        return np.asarray(
            np.where(sigma > 0, np.asarray(m0, dtype=np.float64) / sigma, np.nan), dtype=np.float64
        )


def _window(
    flux: npt.ArrayLike, wave: npt.ArrayLike, wmin: float, wmax: float
) -> tuple[npt.NDArray[Any], npt.NDArray[np.float64], npt.NDArray[np.bool_]]:
    cube = np.asarray(flux)
    axis = np.asarray(wave, dtype=np.float64)
    mask = (axis >= wmin) & (axis <= wmax)
    if not mask.any():
        raise ValueError(f"no channels in the wavelength window [{wmin:.1f}, {wmax:.1f}]")
    return cube, axis, mask


__all__ = [
    "C_KMS",
    "BackgroundMethod",
    "CollapseMethod",
    "ExtractMethod",
    "annulus_mask",
    "box_mask",
    "build_continuum_sub",
    "build_whitelight",
    "circle_mask",
    "compute_snr_map",
    "extract_aperture",
    "extract_variance_weighted",
    "extract_with_method",
    "moment0",
    "moment1",
    "moment2",
    "moment_map",
    "polygon_mask",
    "sky_stats",
    "subtract_background",
    "subtract_linear_continuum",
    "velocity_array",
]
