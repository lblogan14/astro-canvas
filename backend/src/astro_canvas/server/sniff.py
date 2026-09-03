"""Guess what a workspace file holds (spectrum, image, cube, table) so a drop can pick a loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

Kind = Literal["spectrum", "image", "cube", "table", "unknown"]

KIND_NODES: dict[str, str] = {
    "spectrum": "core.io.load_spectrum",
    "image": "core.io.load_image",
    "cube": "core.io.load_cube",
    "table": "core.io.load_table",
}

FITS_SUFFIXES = {".fits", ".fit", ".fts", ".fits.gz", ".fits.fz"}
TEXT_SUFFIXES = {".ecsv", ".csv", ".txt", ".dat", ".tsv", ".tab", ".asc", ".ascii"}
SPECTRAL_COLUMNS = {"wave", "wavelength", "loglam", "lambda", "wave_slice", "wavelen", "lam"}
FLUX_COLUMNS = {"flux", "spec", "flux_slice", "fluxes", "counts"}
SPECTRAL_CTYPES = {"WAVE", "AWAV", "FREQ", "VELO", "LINEAR", "WAVE-LOG", "LAMBDA"}


def _suffix(path: Path) -> str:
    name = path.name.lower()
    for compound in (".fits.gz", ".fits.fz"):
        if name.endswith(compound):
            return compound
    return path.suffix.lower()


def _has_spectrum_columns(names: list[str]) -> bool:
    lowered = {n.lower() for n in names}
    return bool(lowered & SPECTRAL_COLUMNS) and bool(lowered & FLUX_COLUMNS)


def sniff_kind(path: Path) -> tuple[Kind, str]:
    """Return ``(kind, detail)``; ``detail`` is a short human-readable reason."""
    suffix = _suffix(path)
    try:
        if suffix in FITS_SUFFIXES:
            return _sniff_fits(path)
        if suffix == ".json":
            return _sniff_json(path)
        if suffix in TEXT_SUFFIXES:
            return _sniff_text(path)
    except Exception as exc:  # noqa: BLE001 - sniffing is best-effort
        return "unknown", f"could not inspect file: {exc}"
    return "unknown", f"unrecognised extension {suffix or '(none)'}"


def _sniff_fits(path: Path) -> tuple[Kind, str]:
    from astro_canvas_core.io.fits_meta import primary_shape_and_tables  # noqa: PLC0415

    return primary_shape_and_tables(path)


def _sniff_json(path: Path) -> tuple[Kind, str]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        keys = [str(k) for k in data]
        if _has_spectrum_columns(keys):
            return "spectrum", "JSON with wavelength and flux arrays"
        return "table", "JSON object"
    if isinstance(data, list):
        return "table", "JSON array of rows"
    return "unknown", "JSON scalar"


def _sniff_text(path: Path) -> tuple[Kind, str]:
    from astropy.table import Table  # noqa: PLC0415

    try:
        table = Table.read(path, format="ascii.ecsv" if path.suffix.lower() == ".ecsv" else None)
    except Exception:  # noqa: BLE001 - fall back to the generic ASCII reader
        table = Table.read(path, format="ascii")
    names = list(table.colnames)
    if _has_spectrum_columns(names):
        return "spectrum", f"columns {names[:4]}"
    numeric = [n for n in names if table[n].dtype.kind in "fiu"]
    generic = all(n.startswith("col") for n in names)
    if generic and len(numeric) >= 2:
        return "spectrum", "two or more unnamed numeric columns"
    return "table", f"{len(table)} rows x {len(names)} columns"


__all__ = ["KIND_NODES", "Kind", "sniff_kind"]
