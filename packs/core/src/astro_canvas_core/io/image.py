"""2-d image and 3-d cube readers (generic FITS plus KCWI/MUSE header conventions)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
from astropy.io import fits

from astro_canvas_core.io.fits_meta import header_to_dict, spectral_axis, wcs_dict
from astro_canvas_core.io.spectrum import wave_scale_to_angstrom
from astro_canvas_core.types import Cube3D, Image2D

CubeLoader = Literal["auto", "rbcodes"]
DATA_NAMES = ("FLUX", "DATA", "SCI", "SCIENCE", "IMAGE", "PRIMARY")
VAR_NAMES = ("VAR", "VARIANCE", "STAT", "IVAR", "ERR", "ERROR", "SIGMA", "UNCERT", "UNCERTAINTY")
_KCWI_SIDECARS = (
    (re.compile(r"_icubes?(\.fits?)$", re.IGNORECASE), r"_vcubes\1"),
    (re.compile(r"_icubed(\.fits?)$", re.IGNORECASE), r"_vcubed\1"),
    (re.compile(r"_icube(\.fits?)$", re.IGNORECASE), r"_vcube\1"),
)


class ImageReadError(ValueError):
    """The file has no array of the requested dimensionality."""


def _native_float32(data: Any) -> npt.NDArray[np.float32]:
    array = np.asarray(data)
    if array.dtype.kind not in "fiu":
        raise ImageReadError(f"unsupported pixel dtype {array.dtype}")
    return np.ascontiguousarray(array, dtype=np.float32)


def _pick_hdu(hdul: fits.HDUList, ext: int | str | None, ndim: int) -> fits.hdu.base._BaseHDU:
    if ext is not None:
        if isinstance(ext, str) and ext.strip().lstrip("-").isdigit():
            ext = int(ext)
        try:
            hdu = hdul[ext]
        except (KeyError, IndexError):
            raise ImageReadError(f"no extension {ext!r} in the file") from None
        if hdu.data is None or np.ndim(hdu.data) != ndim:
            raise ImageReadError(f"extension {ext!r} is not a {ndim}-d array")
        return hdu
    by_name = {h.name.upper(): h for h in hdul}
    for name in DATA_NAMES:
        hdu = by_name.get(name)
        if hdu is not None and hdu.data is not None and np.ndim(hdu.data) == ndim:
            return hdu
    for hdu in hdul:
        if hdu.data is not None and np.ndim(hdu.data) == ndim:
            return hdu
    raise ImageReadError(f"no {ndim}-d array found in the file")


def _combined_header(primary: fits.Header, hdu_header: fits.Header) -> fits.Header:
    header = primary.copy()
    header.update(hdu_header)
    return header


def read_image(path: Path, ext: int | str | None = None) -> Image2D:
    """Read a 2-d image (first 2-d HDU, or ``ext``) with its header and WCS as dicts."""
    with fits.open(path, memmap=False) as hdul:
        hdu = _pick_hdu(hdul, ext, 2)
        header = _combined_header(hdul[0].header, hdu.header)
        data = _native_float32(hdu.data)
    header_dict = header_to_dict(header)
    header_dict["_EXTNAME"] = hdu.name
    header_dict["_SOURCE"] = path.name
    return Image2D(
        data=data,
        header=header_dict,
        wcs=wcs_dict(header, 2),
        unit=str(header["BUNIT"]) if "BUNIT" in header else None,
    )


def _find_variance(
    hdul: fits.HDUList, path: Path, var_ext: int | str | None, shape: tuple[int, ...]
) -> npt.NDArray[np.float32] | None:
    if var_ext is not None:
        key: int | str = int(var_ext) if str(var_ext).lstrip("-").isdigit() else var_ext
        try:
            hdu = hdul[key]
        except (KeyError, IndexError):
            raise ImageReadError(f"no variance extension {var_ext!r} in the file") from None
        return _variance_from(hdu.name.upper(), hdu.data, shape)
    by_name = {h.name.upper(): h for h in hdul}
    for name in VAR_NAMES:
        hdu = by_name.get(name)
        if hdu is not None and hdu.data is not None and np.shape(hdu.data) == shape:
            return _variance_from(name, hdu.data, shape)
    for pattern, replacement in _KCWI_SIDECARS:
        sidecar = Path(pattern.sub(replacement, str(path)))
        if sidecar != path and sidecar.is_file():
            with fits.open(sidecar, memmap=False) as side:
                for hdu in side:
                    if hdu.data is not None and np.shape(hdu.data) == shape:
                        return _variance_from("VAR", hdu.data, shape)
    return None


def _variance_from(name: str, data: Any, shape: tuple[int, ...]) -> npt.NDArray[np.float32]:
    array = np.asarray(data, dtype=np.float64)
    if array.shape != shape:
        raise ImageReadError("variance extension shape does not match the data cube")
    if name in ("IVAR",):
        var = np.full(array.shape, np.nan)
        good = array > 0
        var[good] = 1.0 / array[good]
        array = var
    elif name in ("ERR", "ERROR", "SIGMA", "UNCERT", "UNCERTAINTY"):
        array = array**2
    return np.ascontiguousarray(array, dtype=np.float32)


def _instrument(header: fits.Header) -> str | None:
    value = header.get("INSTRUME") or header.get("INSTRUMENT")
    if value is None:
        return None
    text = str(value).strip().upper()
    if "KCWI" in text:
        return "KCWI"
    if "MUSE" in text:
        return "MUSE"
    if "MANGA" in text or header.get("SURVEY", "").upper() == "MANGA":
        return "MaNGA"
    return str(value).strip()


def read_cube(
    path: Path,
    ext: int | str | None = None,
    var_ext: int | str | None = None,
    *,
    loader: CubeLoader = "auto",
) -> Cube3D:
    """Read an IFU cube ``flux[nz, ny, nx]`` with its wavelength axis, variance, WCS and header.

    Conventions handled: generic FITS (first 3-d HDU), KCWI (``*_icube*.fits`` with variance in
    ``*_vcube*.fits`` sidecars), MUSE (``DATA`` + ``STAT`` extensions), MaNGA (``FLUX`` + ``IVAR``
    + ``WAVE``). Wavelengths are converted to Angstrom when the header unit allows.

    ``loader="rbcodes"`` reads the file through ``rbcodes.GUIs.ifuviewer.io.auto_cube.load_fits``
    instead, which dispatches on ``INSTRUME`` to its own KCWI/MUSE/generic classes; it raises when
    rbcodes is not installed. ``auto`` (the default) always uses the readers here, which handle the
    same conventions plus MaNGA and the KCWI variance sidecars.
    """
    if loader == "rbcodes":
        return _read_cube_with_rbcodes(path, var_ext)
    with fits.open(path, memmap=False) as hdul:
        hdu = _pick_hdu(hdul, ext, 3)
        header = _combined_header(hdul[0].header, hdu.header)
        flux = _native_float32(hdu.data)
        var = _find_variance(hdul, path, var_ext, flux.shape)
        wave: npt.NDArray[Any] | None = None
        by_name = {h.name.upper(): h for h in hdul}
        for name in ("WAVE", "WAVELENGTH", "LAMBDA"):
            table = by_name.get(name)
            if (
                table is not None
                and table.data is not None
                and np.size(table.data) == flux.shape[0]
            ):
                wave = np.asarray(table.data, dtype=np.float64).reshape(-1)
                break
        unit = header.get("CUNIT3")
        if wave is None:
            try:
                wave = spectral_axis(header, npix=flux.shape[0], axis=3)
            except ValueError:
                wave = np.arange(flux.shape[0], dtype=np.float64)
                unit = "pixel"
    scale = wave_scale_to_angstrom(str(unit) if unit else None)
    header_dict = header_to_dict(header)
    if scale is not None and scale != 1.0:
        wave = wave * scale
        header_dict["_WAVEUNIT_ORIGINAL"] = str(unit)
    header_dict["_WAVEUNIT"] = "Angstrom" if scale is not None else str(unit or "")
    header_dict["_EXTNAME"] = hdu.name
    header_dict["_SOURCE"] = path.name
    return Cube3D(
        flux=flux,
        var=var,
        wave=np.asarray(wave, dtype=np.float64),
        wcs=wcs_dict(header, 3),
        header=header_dict,
        instrument=_instrument(header),
    )


def _read_cube_with_rbcodes(path: Path, var_ext: int | str | None) -> Cube3D:
    """``auto_cube.load_fits``: rbcodes' own KCWI/MUSE/generic dispatch, wrapped as ``Cube3D``.

    rbcodes returns an ``IFUCube`` (or a ``FITSImage`` when the file has no 3-d extension) with
    ``flux``/``var``/``wave``/``header``; the WCS dict and instrument label are derived from that
    header here so the value looks the same whichever loader produced it.
    """
    try:
        from rbcodes.GUIs.ifuviewer.io import auto_cube  # noqa: PLC0415 - optional dependency
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImageReadError(
            "loader='rbcodes' needs the rbcodes distribution (it is only resolvable on "
            "Python < 3.11 until its python_requires pin is relaxed)"
        ) from exc
    sidecar = None if var_ext is None else str(var_ext)
    cube = auto_cube.load_fits(str(path), var=sidecar)
    flux = getattr(cube, "flux", None)
    if flux is None or np.ndim(flux) != 3:
        raise ImageReadError(f"rbcodes read {path.name} as a 2-d image, not a cube")
    header = cube.header if cube.header is not None else fits.Header()
    header_dict = header_to_dict(header)
    header_dict["_WAVEUNIT"] = "Angstrom"
    header_dict["_EXTNAME"] = str(header.get("EXTNAME", ""))
    header_dict["_SOURCE"] = path.name
    header_dict["_LOADER"] = type(cube).__name__
    return Cube3D(
        flux=_native_float32(flux),
        var=None if cube.var is None else _native_float32(cube.var),
        wave=np.asarray(cube.wave, dtype=np.float64),
        wcs=wcs_dict(header, 3) or wcs_dict(header, 2),
        header=header_dict,
        instrument=_instrument(header),
    )


__all__ = ["CubeLoader", "ImageReadError", "read_cube", "read_image"]
