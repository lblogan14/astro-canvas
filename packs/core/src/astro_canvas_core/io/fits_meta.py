"""FITS header helpers: JSON-safe header dicts, plain-dict WCS, spectral axes, kind sniffing."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
from astropy.io import fits

Kind = Literal["spectrum", "image", "cube", "table", "unknown"]

SPECTRAL_CTYPES = {"WAVE", "AWAV", "FREQ", "VELO", "VRAD", "VOPT", "LINEAR", "WAVE-LOG", "LAMBDA"}
SPECTRAL_COLUMNS = {"wave", "wavelength", "loglam", "lambda", "wave_slice", "wavelen", "lam"}
FLUX_COLUMNS = {"flux", "spec", "flux_slice", "fluxes", "counts"}
_WCS_KEY = re.compile(
    r"^(CTYPE|CRVAL|CRPIX|CDELT|CUNIT|CROTA|NAXIS)(\d)$|^(CD|PC)(\d)_(\d)$|^PV(\d)_(\d+)$"
)
_WCS_SCALARS = ("RADESYS", "RADECSYS", "EQUINOX", "LONPOLE", "LATPOLE", "WCSAXES", "SPECSYS")


def _json_value(value: Any) -> Any:
    if isinstance(value, fits.card.Undefined):
        return None
    if isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.generic):
        return _json_value(value.item())
    return str(value)


def header_to_dict(header: fits.Header) -> dict[str, Any]:
    """A JSON-safe copy of a header; repeated ``COMMENT``/``HISTORY`` cards become lists."""
    out: dict[str, Any] = {}
    for key, value in header.items():
        if not key:
            continue
        if key in ("COMMENT", "HISTORY"):
            out.setdefault(key, []).append(str(value))
            continue
        out[key] = _json_value(value)
    return out


def wcs_dict(header: fits.Header, naxis: int | None = None) -> dict[str, Any] | None:
    """The WCS keywords of ``header`` as a small plain dict (``None`` when there is no CTYPE).

    Layout: ``{naxis, shape, ctype[], crval[], crpix[], cdelt[], cunit[], cd[[]] | pc[[]],
    crota2?, radesys?, equinox?, lonpole?, latpole?, pv{}}``. Axes are 1-based in FITS; arrays here
    are 0-based (``ctype[0]`` is axis 1). Matrices are ``cd[i][j]`` for ``CDi_j``.
    """
    n = int(naxis or header.get("WCSAXES") or header.get("NAXIS") or 0)
    if n <= 0 or not any(f"CTYPE{i}" in header for i in range(1, n + 1)):
        return None
    axes = range(1, n + 1)

    def vec(prefix: str, default: Any) -> list[Any]:
        return [_json_value(header.get(f"{prefix}{i}", default)) for i in axes]

    out: dict[str, Any] = {
        "naxis": n,
        "shape": [int(header.get(f"NAXIS{i}", 0)) for i in axes],
        "ctype": [str(v or "") for v in vec("CTYPE", "")],
        "crval": [float(v or 0.0) for v in vec("CRVAL", 0.0)],
        "crpix": [float(v if v is not None else 1.0) for v in vec("CRPIX", 1.0)],
        "cdelt": [float(v if v is not None else 1.0) for v in vec("CDELT", 1.0)],
        "cunit": [str(v or "") for v in vec("CUNIT", "")],
    }
    cd = [[header.get(f"CD{i}_{j}") for j in axes] for i in axes]
    pc = [[header.get(f"PC{i}_{j}") for j in axes] for i in axes]
    if any(v is not None for row in cd for v in row):
        out["cd"] = [[float(v) if v is not None else 0.0 for v in row] for row in cd]
    elif any(v is not None for row in pc for v in row):
        out["pc"] = [
            [float(v) if v is not None else (1.0 if i == j else 0.0) for j, v in enumerate(row)]
            for i, row in enumerate(pc)
        ]
    if "CROTA2" in header:
        out["crota2"] = float(header["CROTA2"])
    for key in _WCS_SCALARS:
        if key in header:
            out[key.lower()] = _json_value(header[key])
    pv: dict[str, float] = {}
    for key, value in header.items():
        match = _WCS_KEY.match(key)
        if match and match.group(6) is not None and isinstance(value, int | float):
            pv[f"{match.group(6)}_{match.group(7)}"] = float(value)
    if pv:
        out["pv"] = pv
    return out


def spectral_axis(header: fits.Header, npix: int | None = None, axis: int = 1) -> npt.NDArray[Any]:
    """World coordinates of a 1-d spectral axis from ``CRVAL/CDELT|CD/CRPIX`` (log when flagged).

    Mirrors rbcodes ``_rb_setwave``: ``DC-FLAG = 1``, ``CTYPE = *-LOG`` or a tiny step (< 1e-4)
    mean the axis is ``log10(wavelength)``.
    """
    n = int(npix if npix is not None else header.get(f"NAXIS{axis}", 0))
    if n <= 0:
        raise ValueError(f"NAXIS{axis} is missing or zero")
    if f"CRVAL{axis}" not in header:
        raise ValueError(f"CRVAL{axis} keyword not found in header")
    crval = float(header[f"CRVAL{axis}"])
    crpix = float(header.get(f"CRPIX{axis}", 1.0))
    if f"CDELT{axis}" in header:
        step = float(header[f"CDELT{axis}"])
    elif f"CD{axis}_{axis}" in header:
        step = float(header[f"CD{axis}_{axis}"])
    else:
        raise ValueError(f"no CDELT{axis} or CD{axis}_{axis} in header")
    ctype = str(header.get(f"CTYPE{axis}", "")).upper()
    log_scale = int(header.get("DC-FLAG", 0) or 0) == 1 or ctype.endswith("-LOG")
    if not log_scale and 0 < abs(step) < 1e-4 and abs(crval) < 10:
        log_scale = True
    world = crval + step * (np.arange(n, dtype=np.float64) + 1.0 - crpix)
    return np.asarray(10.0**world if log_scale else world, dtype=np.float64)


def _has_spectrum_columns(names: list[str]) -> bool:
    lowered = {n.lower() for n in names}
    return bool(lowered & SPECTRAL_COLUMNS) and bool(lowered & FLUX_COLUMNS)


def primary_shape_and_tables(path: Path) -> tuple[Kind, str]:  # noqa: PLR0911 - a classifier
    """Classify a FITS file from its headers only (no data is read)."""
    with fits.open(path, memmap=True, lazy_load_hdus=True) as hdul:
        primary = hdul[0].header
        naxis = int(primary.get("NAXIS", 0))
        if naxis == 3:
            return "cube", "primary HDU is a 3-d array"
        if naxis == 1:
            return "spectrum", "primary HDU is a 1-d array"
        if naxis == 2:
            ctype1 = str(primary.get("CTYPE1", "")).upper()
            rows = int(primary.get("NAXIS2", 0))
            spectral = ctype1 in SPECTRAL_CTYPES or "DC-FLAG" in primary or "COEFF0" in primary
            if rows <= 8 and spectral:
                return "spectrum", "2-d array with a spectral axis (SDSS spSpec style)"
            return "image", "primary HDU is a 2-d array"
        if len(hdul) > 1:
            first = hdul[1]
            if isinstance(first, fits.BinTableHDU | fits.TableHDU):
                names = list(first.columns.names)
                if _has_spectrum_columns(names):
                    return "spectrum", f"table with columns {names[:4]}"
                return "table", f"table with {len(names)} columns"
            ext_naxis = int(first.header.get("NAXIS", 0))
            if ext_naxis == 3:
                return "cube", f"extension {first.name or 1} is a 3-d array"
            if ext_naxis == 2:
                return "image", f"extension {first.name or 1} is a 2-d array"
            if ext_naxis == 1:
                return "spectrum", f"extension {first.name or 1} is a 1-d array"
        return "unknown", "no data in the first two HDUs"


__all__ = [
    "FLUX_COLUMNS",
    "SPECTRAL_COLUMNS",
    "SPECTRAL_CTYPES",
    "Kind",
    "header_to_dict",
    "primary_shape_and_tables",
    "spectral_axis",
    "wcs_dict",
]
