"""rbcodes-first dispatch for the IFU cube processing.

``GUIs.ifuviewer.processing.{cube_collapse, aperture_extract, moment_maps}`` and
``GUIs.ifuviewer.io.auto_cube`` import cleanly headless (numpy, astropy and ``matplotlib.path``
only, no Qt), so the nodes call the installed rbcodes directly and fall back to the vendored
``kernels.ifu`` ports otherwise. Both return plain numpy, so node code never branches on the
backend; ``_rb.provenance()`` records which one produced the numbers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from astro_canvas_rbcodes import _rb
from astro_canvas_rbcodes.kernels import ifu as K

Float2D = npt.NDArray[np.float64]


def _processing(name: str) -> Any | None:
    return _rb.import_rbcodes(f"GUIs.ifuviewer.processing.{name}")


def build_whitelight(
    flux: npt.ArrayLike,
    wave: npt.ArrayLike,
    wmin: float | None,
    wmax: float | None,
    method: K.CollapseMethod,
) -> Float2D:
    """``cube_collapse.build_whitelight`` (rbcodes) or the vendored port."""
    module = _processing("cube_collapse")
    if module is not None:
        return np.asarray(
            module.build_whitelight(np.asarray(flux), np.asarray(wave), wmin, wmax, method),
            dtype=np.float64,
        )
    return K.build_whitelight(flux, wave, wmin, wmax, method)


def build_continuum_sub(
    flux: npt.ArrayLike,
    wave: npt.ArrayLike,
    wmin: float,
    wmax: float,
    c1min: float,
    c1max: float,
    c2min: float | None,
    c2max: float | None,
    method: K.CollapseMethod,
) -> Float2D:
    """``cube_collapse.build_continuum_sub`` (rbcodes) or the vendored port."""
    module = _processing("cube_collapse")
    if module is not None:
        return np.asarray(
            module.build_continuum_sub(
                np.asarray(flux),
                np.asarray(wave),
                wmin,
                wmax,
                c1min,
                c1max,
                c2min,
                c2max,
                method,
            ),
            dtype=np.float64,
        )
    return K.build_continuum_sub(flux, wave, wmin, wmax, c1min, c1max, c2min, c2max, method)


def extract(
    flux: npt.ArrayLike,
    var: npt.ArrayLike | None,
    mask: npt.ArrayLike,
    method: K.ExtractMethod,
) -> tuple[Float2D, Float2D | None]:
    """One spectrum from the spaxels under ``mask`` plus its error, ``aperture_extract``-style.

    ``sum`` uses ``extract_aperture`` (which propagates the variance), ``variance_weighted`` uses
    ``extract_variance_weighted``, and ``mean``/``median`` use ``extract_with_method`` (no error).
    """
    module = _processing("aperture_extract")
    picked = np.asarray(mask, dtype=bool)
    if method == "variance_weighted":
        if module is not None:
            spec, err = module.extract_variance_weighted(np.asarray(flux), _var(var), picked)
            return np.asarray(spec, dtype=np.float64), np.asarray(err, dtype=np.float64)
        return K.extract_variance_weighted(flux, var, picked)
    if method == "sum":
        if module is not None:
            spec, err = module.extract_aperture(
                np.asarray(flux), None if var is None else np.asarray(var), picked
            )
            return (
                np.asarray(spec, dtype=np.float64),
                None if err is None else np.asarray(err, dtype=np.float64),
            )
        return K.extract_aperture(flux, var, picked)
    if module is not None:
        spec = module.extract_with_method(np.asarray(flux), picked, method)
        return np.asarray(spec, dtype=np.float64), None
    return K.extract_with_method(flux, picked, method), None


def _var(var: npt.ArrayLike | None) -> npt.NDArray[np.float64]:
    if var is None:
        raise ValueError("variance-weighted extraction needs a cube with a variance array")
    return np.asarray(var)


def subtract_background(
    spec: npt.ArrayLike,
    flux: npt.ArrayLike,
    bg_mask: npt.ArrayLike,
    method: K.BackgroundMethod,
) -> Float2D:
    """``aperture_extract.subtract_background`` (rbcodes) or the vendored port."""
    module = _processing("aperture_extract")
    if module is not None:
        return np.asarray(
            module.subtract_background(
                np.asarray(spec, dtype=np.float64),
                np.asarray(flux),
                np.asarray(bg_mask, dtype=bool),
                method,
            ),
            dtype=np.float64,
        )
    return K.subtract_background(spec, flux, bg_mask, method)


def moment(
    flux: npt.ArrayLike,
    wave: npt.ArrayLike,
    wmin: float,
    wmax: float,
    order: int,
    lambda_rest: float | None,
) -> Float2D:
    """``moment_maps.moment_map`` (rbcodes) or the vendored port."""
    module = _processing("moment_maps")
    if module is not None:
        return np.asarray(
            module.moment_map(np.asarray(flux), np.asarray(wave), wmin, wmax, order, lambda_rest),
            dtype=np.float64,
        )
    return K.moment_map(flux, wave, wmin, wmax, order, lambda_rest)


def snr_map(
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
    """``moment_maps.compute_snr_map`` (rbcodes) or the vendored port; ``None`` without noise."""
    module = _processing("moment_maps")
    if module is not None:
        result = module.compute_snr_map(
            np.asarray(m0, dtype=np.float64),
            np.asarray(flux),
            np.asarray(wave),
            wmin,
            wmax,
            var=None if var is None else np.asarray(var),
            sky_mask=None if sky_mask is None else np.asarray(sky_mask, dtype=bool),
            cont1=cont1,
            cont2=cont2,
        )
        return None if result is None else np.asarray(result, dtype=np.float64)
    return K.compute_snr_map(m0, flux, wave, wmin, wmax, var, sky_mask, cont1, cont2)


def subtract_linear_continuum(
    flux: npt.ArrayLike,
    wave: npt.ArrayLike,
    bcont_min: float,
    bcont_max: float,
    rcont_min: float,
    rcont_max: float,
) -> npt.NDArray[np.float64]:
    """``moment_maps.subtract_linear_continuum`` (rbcodes) or the vendored port."""
    module = _processing("moment_maps")
    if module is not None:
        return np.asarray(
            module.subtract_linear_continuum(
                np.asarray(flux, dtype=np.float64),
                np.asarray(wave),
                bcont_min,
                bcont_max,
                rcont_min,
                rcont_max,
            ),
            dtype=np.float64,
        )
    return K.subtract_linear_continuum(flux, wave, bcont_min, bcont_max, rcont_min, rcont_max)


def load_cube_via_rbcodes(path: Path, var_path: Path | None = None) -> dict[str, Any] | None:
    """``io.auto_cube.load_fits`` as a plain dict, or ``None`` when rbcodes is not installed.

    The loader dispatches on ``INSTRUME`` (``KCWICube``, ``MUSECube``, else ``GenericCube``) and
    returns an object with ``flux``/``var``/``wave``/``header``/``wcs``; a file with no 3-d
    extension comes back as a ``FITSImage``, which is not a cube and is reported as such.
    """
    module = _rb.import_rbcodes("GUIs.ifuviewer.io.auto_cube")
    if module is None:
        return None
    cube = module.load_fits(str(path), var=None if var_path is None else str(var_path))
    flux = getattr(cube, "flux", None)
    if flux is None or np.ndim(flux) != 3:
        raise ValueError(f"{path.name} has no 3-d extension: rbcodes read it as a 2-d image")
    return {
        "flux": np.asarray(flux, dtype=np.float32),
        "var": None if cube.var is None else np.asarray(cube.var, dtype=np.float32),
        "wave": np.asarray(cube.wave, dtype=np.float64),
        "header": cube.header,
        "loader": type(cube).__name__,
    }


__all__ = [
    "build_continuum_sub",
    "build_whitelight",
    "extract",
    "load_cube_via_rbcodes",
    "moment",
    "snr_map",
    "subtract_background",
    "subtract_linear_continuum",
]
