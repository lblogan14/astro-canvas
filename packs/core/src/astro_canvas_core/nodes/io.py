"""``core.io.*`` nodes: load spectra, tables, images and cubes from the workspace; save results."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from astro_canvas.sdk import NodeContext, Param, node
from astro_canvas_core.io.image import CubeLoader, read_cube, read_image
from astro_canvas_core.io.paths import describe_file, file_fingerprint, resolve_in_workspace
from astro_canvas_core.io.spectrum import SPECTRUM_FORMATS, read_spectrum
from astro_canvas_core.io.table import TABLE_FORMATS, read_table
from astro_canvas_core.io.writers import write_json, write_spectrum, write_table
from astro_canvas_core.types import Cube3D, File, Image2D, Json, Spectrum1D, Table

PathParam = Annotated[str, Param(widget="file", label="File")]
ExtParam = Annotated[
    str,
    Param(
        label="Extension",
        help="FITS extension name or number; empty picks the first suitable HDU.",
        advanced=True,
    ),
]


def _workspace(ctx: NodeContext | None) -> Path:
    return Path(ctx.workspace) if ctx is not None else Path.cwd()


def _ext(value: str) -> int | str | None:
    text = value.strip()
    if not text:
        return None
    return int(text) if text.lstrip("-").isdigit() else text


@node(
    id="core.io.load_spectrum",
    name="Load Spectrum",
    category="Data/Load",
    icon="file-chart-line",
    fingerprint=file_fingerprint,
)
def load_spectrum(
    path: PathParam = "",
    format: Annotated[str, Param(choices=SPECTRUM_FORMATS, label="Format")] = "auto",  # noqa: A002
    use_rbcodes: Annotated[bool, Param(advanced=True, label="Prefer rbcodes parsers")] = True,
    ctx: NodeContext | None = None,
) -> Spectrum1D:
    """Read a 1-d spectrum from a workspace file.

    Supports FITS (binary tables, multi-extension ``FLUX/ERROR/WAVELENGTH/CONTINUUM``, header
    WCS axes, SDSS ``spSpec`` layouts), SDSS/DESI/HSLA products, ASCII/ECSV tables and rb_spec
    JSON. When the ``rbcodes`` distribution is installed its ``rb_spectrum`` readers run first.

    Args:
        path: Workspace-relative file path.
        format: Force a parser instead of auto-detecting it.
        use_rbcodes: Try rbcodes' readers before the built-in astropy parsers.

    Returns:
        The spectrum with wavelengths in Angstrom (converted when the unit is known).
    """
    if not path:
        raise ValueError("choose a file to load")
    target = resolve_in_workspace(_workspace(ctx), path)
    return read_spectrum(target, format, use_rbcodes=use_rbcodes)


@node(
    id="core.io.load_table",
    name="Load Table",
    category="Data/Load",
    icon="table",
    fingerprint=file_fingerprint,
)
def load_table(
    path: PathParam = "",
    format: Annotated[str, Param(choices=TABLE_FORMATS, label="Format")] = "auto",  # noqa: A002
    ext: ExtParam = "",
    ctx: NodeContext | None = None,
) -> Table:
    """Read a table (FITS binary table, ECSV, CSV/ASCII, VOTable or JSON rows).

    Args:
        path: Workspace-relative file path.
        format: Force a reader instead of detecting it from the suffix.
        ext: FITS extension to read (name or number).

    Returns:
        The table as named columns (multi-dimensional columns are skipped and listed in ``meta``).
    """
    if not path:
        raise ValueError("choose a file to load")
    target = resolve_in_workspace(_workspace(ctx), path)
    return read_table(target, format, _ext(ext))


@node(
    id="core.io.load_image",
    name="Load Image",
    category="Data/Load",
    icon="image",
    cost="auto",
    fingerprint=file_fingerprint,
)
def load_image(
    path: PathParam = "",
    ext: ExtParam = "",
    ctx: NodeContext | None = None,
) -> Image2D:
    """Read a 2-d FITS image with its header and WCS.

    Args:
        path: Workspace-relative FITS file.
        ext: Extension holding the image (default: first 2-d HDU, preferring ``SCI``/``DATA``).

    Returns:
        The image as float32 pixels plus header and WCS dictionaries.
    """
    if not path:
        raise ValueError("choose a file to load")
    target = resolve_in_workspace(_workspace(ctx), path)
    return read_image(target, _ext(ext))


@node(
    id="core.io.load_cube",
    name="Load Cube",
    category="Data/Load",
    icon="box",
    cost="auto",
    fingerprint=file_fingerprint,
)
def load_cube(
    path: PathParam = "",
    ext: ExtParam = "",
    var_ext: Annotated[
        str, Param(label="Variance extension", advanced=True, help="Empty: auto-detect.")
    ] = "",
    loader: Annotated[
        CubeLoader,
        Param(label="Loader", help="Which reader interprets the file's instrument conventions."),
    ] = "auto",
    ctx: NodeContext | None = None,
) -> Cube3D:
    """Read an IFU data cube (generic FITS, KCWI ``_icubes``/``_vcubes``, MUSE ``DATA``/``STAT``).

    Args:
        path: Workspace-relative FITS file.
        ext: Extension holding the flux cube (default: first 3-d HDU).
        var_ext: Extension holding the variance (default: ``VAR``/``STAT``/``IVAR`` or a sidecar).
        loader: ``auto`` uses the readers in this pack (KCWI, MUSE, MaNGA and generic FITS);
            ``rbcodes`` reads the file through ``rb_ifuview``'s own ``auto_cube.load_fits``
            instrument dispatch, and needs the rbcodes distribution.

    Returns:
        The cube with wavelengths in Angstrom (when the header unit is known), variance and WCS.
    """
    if not path:
        raise ValueError("choose a file to load")
    target = resolve_in_workspace(_workspace(ctx), path)
    return read_cube(target, _ext(ext), _ext(var_ext), loader=loader)


@node(id="core.io.save_spectrum", name="Save Spectrum", category="Data/Save", icon="save")
def save_spectrum(
    spec: Spectrum1D,
    path: Annotated[str, Param(label="Output path")] = "outputs/spectrum.fits",
    format: Annotated[  # noqa: A002
        Literal["fits", "ecsv", "json", "csv"], Param(label="Format")
    ] = "fits",
    ctx: NodeContext | None = None,
) -> File:
    """Write a spectrum into the workspace (FITS uses the rbcodes multi-extension layout).

    Args:
        spec: The spectrum to save.
        path: Workspace-relative output path (folders are created).
        format: File format.

    Returns:
        The written file (path, size, blake3).
    """
    root = _workspace(ctx)
    target = resolve_in_workspace(root, path)
    write_spectrum(spec, target, format)
    return describe_file(root, target)


@node(id="core.io.save_table", name="Save Table", category="Data/Save", icon="save")
def save_table(
    table: Table,
    path: Annotated[str, Param(label="Output path")] = "outputs/table.ecsv",
    format: Annotated[  # noqa: A002
        Literal["ecsv", "csv", "fits", "votable", "json"], Param(label="Format")
    ] = "ecsv",
    ctx: NodeContext | None = None,
) -> File:
    """Write a table into the workspace.

    Args:
        table: The table to save.
        path: Workspace-relative output path (folders are created).
        format: File format.

    Returns:
        The written file.
    """
    root = _workspace(ctx)
    target = resolve_in_workspace(root, path)
    write_table(table, target, format)
    return describe_file(root, target)


@node(id="core.io.save_json", name="Save JSON", category="Data/Save", icon="save")
def save_json(
    value: Json,
    path: Annotated[str, Param(label="Output path")] = "outputs/value.json",
    indent: Annotated[int, Param(min=0, max=8, advanced=True)] = 2,
    ctx: NodeContext | None = None,
) -> File:
    """Write any JSON value into the workspace.

    Args:
        value: The value to save.
        path: Workspace-relative output path (folders are created).
        indent: Pretty-print indentation (0 for compact).

    Returns:
        The written file.
    """
    root = _workspace(ctx)
    target = resolve_in_workspace(root, path)
    payload: Any = value.value
    write_json(payload, target, indent=indent or None)
    return describe_file(root, target)
