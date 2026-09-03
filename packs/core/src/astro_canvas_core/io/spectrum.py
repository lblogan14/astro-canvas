"""Spectrum readers: astropy-native parsers for FITS/ASCII/ECSV/SDSS/DESI/HSLA/rbspec JSON.

The dispatch mirrors rbcodes' ``rb_spectrum`` (``_rb_read_fits`` and friends) so both paths
produce the same arrays. When the ``rbcodes`` distribution is importable and ``use_rbcodes`` is
set, its ``rb_read_spectrum`` is tried first and this module is the fallback.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
from astropy.io import fits
from astropy.table import Table as AstroTable

from astro_canvas_core.io.fits_meta import header_to_dict, spectral_axis
from astro_canvas_core.types import Spectrum1D

SpectrumFormat = Literal["auto", "fits", "ascii", "ecsv", "sdss", "desi", "hsla", "rbspec_json"]
SPECTRUM_FORMATS: tuple[str, ...] = (
    "auto",
    "fits",
    "ascii",
    "ecsv",
    "sdss",
    "desi",
    "hsla",
    "rbspec_json",
)

WAVE_NAMES = ("wave", "wavelength", "lambda", "wavelen", "lam", "wave_slice", "loglam")
FLUX_NAMES = ("flux", "spec", "flux_slice", "fluxes", "counts", "fnorm")
ERROR_NAMES = (
    "error",
    "err",
    "sigma",
    "sig",
    "flux_error",
    "flux_err",
    "fluxerr",
    "stddev",
    "uncertainty",
    "error_slice",
    "ivar",
    "flux_ivar",
)
CONT_NAMES = ("continuum", "cont", "model")
HEADER_KEYS = (
    "OBJECT",
    "TELESCOP",
    "INSTRUME",
    "RA",
    "DEC",
    "PLUG_RA",
    "PLUG_DEC",
    "PLATE",
    "MJD",
    "FIBERID",
    "EXPTIME",
    "DATE-OBS",
    "BUNIT",
    "TARGNAME",
    "DETECTOR",
    "GRATING",
    "FILTER",
)
_WAVE_UNIT_ALIASES = {
    "angstrom": 1.0,
    "angstroms": 1.0,
    "aa": 1.0,
    "a": 1.0,
    "ang": 1.0,
    "0.1 nm": 1.0,
    "nm": 10.0,
    "nanometer": 10.0,
    "nanometers": 10.0,
    "um": 1e4,
    "micron": 1e4,
    "microns": 1e4,
    "micrometer": 1e4,
    "micrometers": 1e4,
    "m": 1e10,
    "meter": 1e10,
    "meters": 1e10,
}
_SIDECAR_SUFFIXES = ("e.fits", "E.fits", "_err.fits", ".err.fits", "_error.fits", "_sig.fits")


class SpectrumReadError(ValueError):
    """The file could not be interpreted as a 1-d spectrum."""


@dataclass
class RawSpectrum:
    """Arrays and metadata collected by a parser before validation into ``Spectrum1D``."""

    wave: npt.NDArray[Any]
    flux: npt.NDArray[Any]
    error: npt.NDArray[Any] | None = None
    continuum: npt.NDArray[Any] | None = None
    wave_unit: str = "Angstrom"
    flux_unit: str = "erg / (s cm2 Angstrom)"
    format: str = "fits"
    meta: dict[str, Any] = field(default_factory=dict)


def _lower_map(names: list[str]) -> dict[str, str]:
    return {n.lower(): n for n in names}


def _pick(names: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in names:
            return names[candidate]
    return None


def _as_float(values: Any) -> npt.NDArray[np.float64]:
    array = np.ma.filled(np.asarray(values), np.nan) if np.ma.isMaskedArray(values) else values
    return np.asarray(array, dtype=np.float64).reshape(-1)


def _ivar_to_sigma(ivar: npt.NDArray[Any]) -> npt.NDArray[np.float64]:
    ivar = _as_float(ivar)
    sigma = np.full(ivar.shape, np.nan)
    good = ivar > 0
    sigma[good] = 1.0 / np.sqrt(ivar[good])
    return sigma


def wave_scale_to_angstrom(unit: str | None) -> float | None:
    """Multiplier converting ``unit`` to Angstrom (``None`` when not a length unit we know)."""
    if not unit:
        return None
    return _WAVE_UNIT_ALIASES.get(str(unit).strip().lower())


def _normalise_wave(raw: RawSpectrum, unit: str | None) -> None:
    scale = wave_scale_to_angstrom(unit)
    if unit and scale is None:
        raw.wave_unit = str(unit)
        return
    if scale is not None and scale != 1.0:
        raw.wave = raw.wave * scale
        raw.meta["wave_unit_original"] = str(unit)
    raw.wave_unit = "Angstrom"


def _header_meta(header: fits.Header) -> dict[str, Any]:
    picked = {k: header[k] for k in HEADER_KEYS if k in header}
    return header_to_dict(fits.Header(list(picked.items()))) if picked else {}


# --- FITS -----------------------------------------------------------------------------------------


def _detect_fits_format(hdul: fits.HDUList) -> str:
    primary = hdul[0].header
    naxis = int(primary.get("NAXIS", 0))
    names = [h.name.upper() for h in hdul]
    if naxis == 0 and len(hdul) > 1 and isinstance(hdul[1], fits.BinTableHDU | fits.TableHDU):
        cols = {c.lower() for c in hdul[1].columns.names}
        if "loglam" in cols and "flux" in cols:
            return "sdss"
        if "wave" in cols and "flux" in cols and ("error" in cols or "err" in cols):
            return "hsla"
        return "fits"
    if any(n.endswith("_WAVELENGTH") for n in names):
        return "desi"
    if naxis == 2 and len(hdul) >= 3 and names[0] == "FLUX" and names[2] == "WAVELENGTH":
        return "desi"
    return "fits"


def _read_fits(path: Path, fmt: str) -> RawSpectrum:
    with fits.open(path, memmap=False) as hdul:
        detected = _detect_fits_format(hdul) if fmt in ("auto", "fits") else fmt
        if detected == "sdss":
            raw = _parse_sdss(hdul)
        elif detected == "desi":
            raw = _parse_desi(hdul)
        elif detected == "hsla" or (
            len(hdul) > 1
            and int(hdul[0].header.get("NAXIS", 0)) == 0
            and isinstance(hdul[1], fits.BinTableHDU | fits.TableHDU)
        ):
            raw = _parse_bintable(hdul)
            raw.format = detected if detected in ("hsla", "sdss") else "fits"
        else:
            raw = _parse_image_hdus(path, hdul)
        raw.meta.update(_header_meta(hdul[0].header))
        return raw


def _parse_sdss(hdul: fits.HDUList) -> RawSpectrum:
    table = hdul[1].data
    names = _lower_map(list(table.columns.names))
    loglam = _as_float(table[names["loglam"]])
    flux = _as_float(table[names["flux"]])
    error = _ivar_to_sigma(table[names["ivar"]]) if "ivar" in names else None
    continuum = _as_float(table[names["model"]]) if "model" in names else None
    raw = RawSpectrum(
        wave=10.0**loglam,
        flux=flux,
        error=error,
        continuum=continuum,
        flux_unit="1e-17 erg / (s cm2 Angstrom)",
        format="sdss",
    )
    raw.meta["airvac"] = "vac"
    for ext in hdul[2:]:
        if isinstance(ext, fits.BinTableHDU) and "Z" in ext.columns.names and len(ext.data):
            raw.meta["z"] = float(ext.data["Z"][0])
            if "Z_ERR" in ext.columns.names:
                raw.meta["z_err"] = float(ext.data["Z_ERR"][0])
            if "CLASS" in ext.columns.names:
                raw.meta["class"] = str(ext.data["CLASS"][0]).strip()
            break
    return raw


def _parse_desi(hdul: fits.HDUList) -> RawSpectrum:
    names = [h.name.upper() for h in hdul]
    cameras = sorted({n.split("_")[0] for n in names if n.endswith("_WAVELENGTH")})
    if cameras:
        parts: list[tuple[npt.NDArray[Any], npt.NDArray[Any], npt.NDArray[Any] | None]] = []
        for cam in cameras:
            wave = _as_float(hdul[f"{cam}_WAVELENGTH"].data)
            flux2d = np.atleast_2d(np.asarray(hdul[f"{cam}_FLUX"].data, dtype=np.float64))
            flux = flux2d[0]
            error: npt.NDArray[Any] | None = None
            if f"{cam}_IVAR" in names:
                error = _ivar_to_sigma(np.atleast_2d(hdul[f"{cam}_IVAR"].data)[0])
            parts.append((wave, flux, error))
        parts.sort(key=lambda p: float(p[0][0]))
        wave = np.concatenate([p[0] for p in parts])
        flux = np.concatenate([p[1] for p in parts])
        errors = [p[2] for p in parts]
        error = (
            np.concatenate([e for e in errors if e is not None])
            if all(e is not None for e in errors)
            else None
        )
        order = np.argsort(wave, kind="stable")
        raw = RawSpectrum(
            wave=wave[order],
            flux=flux[order],
            error=None if error is None else error[order],
            flux_unit="1e-17 erg / (s cm2 Angstrom)",
            format="desi",
        )
        raw.meta["cameras"] = cameras
        return raw
    # Brick layout: FLUX[nspec, npix], IVAR|ERROR[nspec, npix], WAVELENGTH[npix].
    flux = np.atleast_2d(np.asarray(hdul[0].data, dtype=np.float64))[0]
    second = hdul[1]
    if second.name.upper() == "ERROR":
        error = _as_float(np.atleast_2d(second.data)[0])
    else:
        error = _ivar_to_sigma(np.atleast_2d(second.data)[0])
    wave = _as_float(hdul[2].data)
    return RawSpectrum(wave=wave, flux=flux, error=error, format="desi")


def _parse_bintable(hdul: fits.HDUList) -> RawSpectrum:
    hdu = hdul[1]
    table = hdu.data
    names = _lower_map(list(table.columns.names))
    wave_col = _pick(names, WAVE_NAMES)
    flux_col = _pick(names, FLUX_NAMES)
    if wave_col is None or flux_col is None:
        raise SpectrumReadError(
            f"table has no wavelength/flux columns (found {list(table.columns.names)[:8]})"
        )
    wave = _as_float(table[wave_col])
    if wave_col.lower() == "loglam":
        wave = 10.0**wave
    flux = _as_float(table[flux_col])
    error_col = _pick(names, ERROR_NAMES)
    error = None
    if error_col is not None:
        error = _as_float(table[error_col])
        if error_col.lower() in ("ivar", "flux_ivar"):
            error = _ivar_to_sigma(error)
    cont_col = _pick(names, CONT_NAMES)
    continuum = _as_float(table[cont_col]) if cont_col is not None else None
    if wave.shape != flux.shape:
        raise SpectrumReadError("wavelength and flux columns have different lengths")
    raw = RawSpectrum(wave=wave, flux=flux, error=error, continuum=continuum, format="fits")
    units = {c.name.lower(): c.unit for c in hdu.columns}
    _normalise_wave(raw, units.get(wave_col.lower()))
    flux_unit = units.get(flux_col.lower()) or hdul[0].header.get("BUNIT")
    if flux_unit:
        raw.flux_unit = str(flux_unit)
    raw.meta["extname"] = hdu.name
    return raw


def _parse_image_hdus(path: Path, hdul: fits.HDUList) -> RawSpectrum:
    primary = hdul[0]
    naxis = int(primary.header.get("NAXIS", 0))
    if naxis == 0:
        data_hdus = [h for h in hdul[1:] if h.data is not None and h.data.ndim == 1]
        if not data_hdus:
            raise SpectrumReadError("no 1-d data or spectral table found in the FITS file")
        primary = data_hdus[0]
        naxis = 1
    names = [h.name.upper() for h in hdul]
    if naxis == 2:
        data = np.asarray(primary.data, dtype=np.float64)
        if data.shape[0] > 8:
            raise SpectrumReadError("2-d image data is not a spectrum (use load_image)")
        raw = RawSpectrum(
            wave=spectral_axis(primary.header, npix=data.shape[1]),
            flux=data[0],
            error=data[2] if data.shape[0] > 2 else None,
            format="fits",
        )
        raw.meta["layout"] = "sdss-spSpec"
        return raw
    flux = _as_float(primary.data)
    error: npt.NDArray[Any] | None = None
    continuum: npt.NDArray[Any] | None = None
    wave: npt.NDArray[Any] | None = None
    if len(hdul) > 1:
        if "WAVELENGTH" in names:
            wave = _as_float(hdul[names.index("WAVELENGTH")].data)
        elif len(hdul) > 2 and hdul[2].data is not None:
            wave = _as_float(hdul[2].data)
        for name in ("ERROR", "ERR", "SIG", "SIGMA", "UNCERTAINTY"):
            if name in names:
                error = _as_float(hdul[names.index(name)].data)
                break
        if error is None and names[1] != "WAVELENGTH" and hdul[1].data is not None:
            error = _as_float(hdul[1].data)
        if "CONTINUUM" in names:
            continuum = _as_float(hdul[names.index("CONTINUUM")].data)
        elif len(hdul) > 3 and hdul[3].data is not None and names[3] not in ("WAVELENGTH",):
            continuum = _as_float(hdul[3].data)
    if wave is None:
        wave = spectral_axis(primary.header, npix=flux.shape[0])
    if error is None and len(hdul) == 1:
        error = _sidecar_error(path)
    for arr_name, arr in (("error", error), ("continuum", continuum)):
        if arr is not None and arr.shape != flux.shape:
            raise SpectrumReadError(f"{arr_name} extension length does not match flux")
    raw = RawSpectrum(wave=wave, flux=flux, error=error, continuum=continuum, format="fits")
    _normalise_wave(raw, primary.header.get("CUNIT1"))
    if primary.header.get("BUNIT"):
        raw.flux_unit = str(primary.header["BUNIT"])
    return raw


def _sidecar_error(path: Path) -> npt.NDArray[Any] | None:
    base = re.sub(r"\.fits?$", "", str(path), flags=re.IGNORECASE)
    for suffix in _SIDECAR_SUFFIXES:
        candidate = Path(base + suffix)
        if candidate.is_file() and candidate != path:
            try:
                return _as_float(fits.getdata(candidate))
            except (OSError, ValueError):
                continue
    return None


# --- JSON and text --------------------------------------------------------------------------------


def _read_json(path: Path) -> RawSpectrum:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SpectrumReadError("JSON spectrum must be an object")
    if "wave_slice" in data and "flux_slice" in data:
        zabs = float(data.get("zabs", 0.0))
        wave = _as_float(data["wave_slice"]) * (1.0 + zabs)
        flux = _as_float(data["flux_slice"])
        error = _as_float(data["error_slice"]) if "error_slice" in data else None
        continuum: npt.NDArray[Any] | None = None
        if "cont" in data:
            continuum = _as_float(data["cont"])
        elif "fnorm" in data:
            fnorm = _as_float(data["fnorm"])
            continuum = np.zeros_like(flux)
            good = fnorm != 0
            continuum[good] = flux[good] / fnorm[good]
        raw = RawSpectrum(
            wave=wave, flux=flux, error=error, continuum=continuum, format="rbspec_json"
        )
        analysis = {
            k: data[k]
            for k in (
                "zabs",
                "linelist",
                "trans",
                "fval",
                "trans_wave",
                "vmin",
                "vmax",
                "W",
                "W_e",
                "N",
                "N_e",
                "logN",
                "logN_e",
                "vel_centroid",
                "vel_disp",
                "SNR",
            )
            if k in data
        }
        if analysis:
            raw.meta["rb_spec_analysis"] = analysis
        raw.meta["airvac"] = "vac"
        raw.meta["z"] = zabs
        return raw
    names = _lower_map(list(data))
    wave_col, flux_col = _pick(names, WAVE_NAMES), _pick(names, FLUX_NAMES)
    if wave_col is None or flux_col is None:
        raise SpectrumReadError("JSON has no wavelength/flux arrays")
    error_col, cont_col = _pick(names, ERROR_NAMES), _pick(names, CONT_NAMES)
    raw = RawSpectrum(
        wave=_as_float(data[wave_col]),
        flux=_as_float(data[flux_col]),
        error=_as_float(data[error_col]) if error_col else None,
        continuum=_as_float(data[cont_col]) if cont_col else None,
        format="rbspec_json",
    )
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        raw.meta.update(metadata)
    units = data.get("units")
    if isinstance(units, str):
        try:
            units = json.loads(units)
        except ValueError:
            units = None
    if isinstance(units, dict):
        _normalise_wave(raw, str(units.get("wave", "")) or None)
        if units.get("flux"):
            raw.flux_unit = str(units["flux"])
    return raw


def _read_text(path: Path, fmt: str) -> RawSpectrum:
    suffix = path.suffix.lower()
    if fmt == "ecsv" or suffix == ".ecsv":
        table = AstroTable.read(path, format="ascii.ecsv")
        detected = "ecsv"
    else:
        try:
            table = AstroTable.read(path, format="ascii")
        except Exception as exc:
            raise SpectrumReadError(f"could not parse text spectrum: {exc}") from exc
        detected = "ascii"
    names = _lower_map(list(table.colnames))
    wave_col = _pick(names, WAVE_NAMES) or (table.colnames[0] if len(table.colnames) >= 2 else None)
    flux_col = _pick(names, FLUX_NAMES) or (
        table.colnames[1] if len(table.colnames) >= 2 and wave_col == table.colnames[0] else None
    )
    if wave_col is None or flux_col is None:
        raise SpectrumReadError("text spectrum needs at least two numeric columns")
    error_col = _pick(names, ERROR_NAMES)
    cont_col = _pick(names, CONT_NAMES)
    positional = wave_col == table.colnames[0] and flux_col == table.colnames[1]
    if positional and error_col is None and len(table.colnames) >= 3:
        error_col = table.colnames[2]
    if positional and cont_col is None and len(table.colnames) >= 4:
        cont_col = table.colnames[3]
    raw = RawSpectrum(
        wave=_as_float(table[wave_col]),
        flux=_as_float(table[flux_col]),
        error=_as_float(table[error_col]) if error_col else None,
        continuum=_as_float(table[cont_col]) if cont_col else None,
        format=detected,
    )
    if error_col and error_col.lower() in ("ivar", "flux_ivar"):
        raw.error = _ivar_to_sigma(raw.error)  # type: ignore[arg-type]
    wave_unit = table[wave_col].unit
    _normalise_wave(raw, str(wave_unit) if wave_unit is not None else None)
    if table[flux_col].unit is not None:
        raw.flux_unit = str(table[flux_col].unit)
    if table.meta:
        raw.meta["table_meta"] = {str(k): v for k, v in table.meta.items() if _jsonable(v)}
    return raw


def _jsonable(value: Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


# --- rbcodes path ---------------------------------------------------------------------------------


def rbcodes_available() -> bool:
    """True when the ``rbcodes`` distribution can be imported."""
    try:
        return importlib.util.find_spec("rbcodes") is not None
    except (ImportError, ValueError):
        return False


def _read_with_rbcodes(path: Path) -> RawSpectrum | None:
    os.environ.setdefault("MPLBACKEND", "Agg")
    try:
        from rbcodes.utils.rb_spectrum import (  # noqa: PLC0415
            rb_read_spectrum,
        )
    except Exception:  # noqa: BLE001 - optional dependency with heavy imports
        return None
    spectrum: Any = rb_read_spectrum(str(path))
    if getattr(spectrum, "_read_failed", True):
        return None
    wave = np.asarray(spectrum.wavelength.value, dtype=np.float64)
    flux = np.asarray(spectrum.flux.value, dtype=np.float64)
    error = np.asarray(spectrum.sig.value, dtype=np.float64) if spectrum.sig_is_set else None
    cont = np.asarray(spectrum.co.value, dtype=np.float64) if spectrum.co_is_set else None
    raw = RawSpectrum(wave=wave, flux=flux, error=error, continuum=cont, format="rbcodes")
    _normalise_wave(raw, str(spectrum.wavelength.unit))
    raw.flux_unit = str(spectrum.flux.unit)
    raw.meta.update({k: v for k, v in dict(spectrum.meta or {}).items() if _jsonable(v)})
    return raw


# --- entry point ----------------------------------------------------------------------------------


def read_raw(path: Path, fmt: str = "auto", *, use_rbcodes: bool = True) -> RawSpectrum:
    """Parse ``path`` into a ``RawSpectrum`` using the requested or detected format."""
    if fmt not in SPECTRUM_FORMATS:
        raise SpectrumReadError(f"unknown spectrum format {fmt!r}")
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if fmt == "auto" and use_rbcodes and rbcodes_available():
        via_rbcodes = _read_with_rbcodes(path)
        if via_rbcodes is not None:
            return via_rbcodes
    suffix = path.suffix.lower()
    if fmt == "rbspec_json" or (fmt == "auto" and suffix == ".json"):
        return _read_json(path)
    if fmt in ("ascii", "ecsv") or (
        fmt == "auto" and suffix not in (".fits", ".fit", ".fts", ".gz", ".fz")
    ):
        return _read_text(path, fmt)
    return _read_fits(path, fmt)


def read_spectrum(path: Path, fmt: str = "auto", *, use_rbcodes: bool = True) -> Spectrum1D:
    """Read a 1-d spectrum from ``path`` into the ``astro.Spectrum1D`` port type."""
    raw = read_raw(path, fmt, use_rbcodes=use_rbcodes)
    order = np.argsort(raw.wave, kind="stable")
    sorted_already = bool(np.all(order == np.arange(order.size)))

    def pick(array: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return array if sorted_already else array[order]

    meta = {"source": path.name, "format": raw.format, **raw.meta}
    z = meta.get("z")
    return Spectrum1D(
        wave=pick(raw.wave),
        flux=pick(raw.flux),
        error=None if raw.error is None else pick(raw.error),
        continuum=None if raw.continuum is None else pick(raw.continuum),
        wave_unit=raw.wave_unit,
        flux_unit=raw.flux_unit,
        meta=meta,
        z=float(z) if isinstance(z, int | float) else None,
    )


__all__ = [
    "SPECTRUM_FORMATS",
    "RawSpectrum",
    "SpectrumFormat",
    "SpectrumReadError",
    "rbcodes_available",
    "read_raw",
    "read_spectrum",
    "wave_scale_to_angstrom",
]
