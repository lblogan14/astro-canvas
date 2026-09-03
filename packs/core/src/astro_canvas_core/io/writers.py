"""Writers behind ``core.io.save_*``: spectra (FITS/ECSV/JSON/CSV), tables and JSON values."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
from astropy.io import fits
from astropy.table import Table as AstroTable
from pydantic_core import to_jsonable_python

from astro_canvas_core.types import Spectrum1D, Table

SpectrumWriteFormat = Literal["fits", "ecsv", "json", "csv"]
TableWriteFormat = Literal["ecsv", "csv", "fits", "votable", "json"]


def _numpy_fallback(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"{type(value).__name__} is not JSON-serializable")


def spectrum_to_astropy(spec: Spectrum1D) -> AstroTable:
    """An astropy table with ``wave, flux[, error][, continuum]`` columns and units."""
    table = AstroTable()
    table["wave"] = spec.wave
    table["flux"] = spec.flux
    if spec.error is not None:
        table["error"] = spec.error
    if spec.continuum is not None:
        table["continuum"] = spec.continuum
    table["wave"].unit = spec.wave_unit
    for name in ("flux", "error", "continuum"):
        if name in table.colnames:
            table[name].unit = spec.flux_unit
    table.meta.update(
        {
            "frame": spec.frame,
            "z": spec.z,
            "v0_wrest": spec.v0_wrest,
            **{k: v for k, v in spec.meta.items() if isinstance(v, str | int | float | bool)},
        }
    )
    return table


def write_spectrum(spec: Spectrum1D, path: Path, fmt: SpectrumWriteFormat = "fits") -> Path:
    """Write ``spec`` to ``path``; the FITS layout follows rbcodes ``rb_write_fits``.

    FITS: ``PRIMARY`` = flux with ``ERROR``, ``WAVELENGTH`` and ``CONTINUUM`` image extensions.
    ECSV/CSV: a table with units. JSON: the rb_spectrum native layout.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "fits":
        primary = fits.PrimaryHDU(np.asarray(spec.flux, dtype=np.float64))
        primary.name = "FLUX"
        primary.header["BUNIT"] = spec.flux_unit
        primary.header["WAVEUNIT"] = spec.wave_unit
        primary.header["FRAME"] = spec.frame
        if spec.z is not None:
            primary.header["REDSHIFT"] = spec.z
        if spec.v0_wrest is not None:
            primary.header["V0WREST"] = spec.v0_wrest
        for key in ("airvac", "source", "format"):
            if isinstance(spec.meta.get(key), str):
                primary.header[key.upper()[:8]] = spec.meta[key]
        hdus: list[fits.hdu.base._BaseHDU] = [primary]
        error = spec.error if spec.error is not None else np.zeros_like(spec.flux)
        hdus.append(fits.ImageHDU(np.asarray(error, dtype=np.float64), name="ERROR"))
        hdus.append(fits.ImageHDU(np.asarray(spec.wave, dtype=np.float64), name="WAVELENGTH"))
        if spec.continuum is not None:
            hdus.append(
                fits.ImageHDU(np.asarray(spec.continuum, dtype=np.float64), name="CONTINUUM")
            )
        fits.HDUList(hdus).writeto(path, overwrite=True)
    elif fmt == "ecsv":
        spectrum_to_astropy(spec).write(path, format="ascii.ecsv", overwrite=True)
    elif fmt == "csv":
        spectrum_to_astropy(spec).write(path, format="ascii.csv", overwrite=True)
    elif fmt == "json":
        payload: dict[str, Any] = {
            "wavelength": spec.wave.tolist(),
            "flux": spec.flux.tolist(),
            "metadata": to_jsonable_python(
                {**spec.meta, "frame": spec.frame, "z": spec.z}, fallback=_numpy_fallback
            ),
            "units": {"wave": spec.wave_unit, "flux": spec.flux_unit},
        }
        if spec.error is not None:
            payload["error"] = spec.error.tolist()
        if spec.continuum is not None:
            payload["continuum"] = spec.continuum.tolist()
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        raise ValueError(f"unknown spectrum format {fmt!r}")
    return path


def table_to_astropy(table: Table) -> AstroTable:
    out = AstroTable({name: col for name, col in table.columns.items()})
    for name, unit in table.units.items():
        if name in out.colnames:
            try:
                out[name].unit = unit
            except (ValueError, TypeError):
                out.meta.setdefault("units", {})[name] = unit
    for key, value in table.meta.items():
        if key != "skipped_columns":
            out.meta[key] = value
    return out


def write_table(table: Table, path: Path, fmt: TableWriteFormat = "ecsv") -> Path:
    """Write an ``astro.Table`` as ECSV, CSV, FITS, VOTable or JSON rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        rows = [
            {name: _numpy_fallback(col[i]) for name, col in table.columns.items()}
            for i in range(table.n_rows)
        ]
        path.write_text(json.dumps(rows), encoding="utf-8")
        return path
    formats = {"ecsv": "ascii.ecsv", "csv": "ascii.csv", "fits": "fits", "votable": "votable"}
    if fmt not in formats:
        raise ValueError(f"unknown table format {fmt!r}")
    astro = table_to_astropy(table)
    if fmt == "fits":
        astro.meta = {
            k: v for k, v in astro.meta.items() if isinstance(v, str | int | float | bool)
        }
    astro.write(path, format=formats[fmt], overwrite=True)
    return path


def write_json(value: Any, path: Path, *, indent: int | None = 2) -> Path:
    """Write any JSON-able value (numpy arrays become lists)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_jsonable_python(value, fallback=_numpy_fallback)
    path.write_text(json.dumps(payload, indent=indent), encoding="utf-8")
    return path


__all__ = [
    "SpectrumWriteFormat",
    "TableWriteFormat",
    "spectrum_to_astropy",
    "table_to_astropy",
    "write_json",
    "write_spectrum",
    "write_table",
]
