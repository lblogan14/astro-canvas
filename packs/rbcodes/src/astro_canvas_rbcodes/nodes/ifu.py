"""``rbcodes.ifu.*`` nodes: ``rb_ifuview``'s cube flows as a graph.

Collapses (white light, narrow band, continuum-subtracted) turn a cube into an image; the
**aperture editor** draws circles, boxes, annuli and polygons on that image and ``aperture_extract``
turns them into spectra; ``moment_maps`` and ``snr_map`` measure the kinematics of one line, and the
ds9 nodes move regions in and out of the file format every other tool speaks.

Like ``rbcodes.multispec.view``, ``aperture_extract`` is an interactive node: the apertures live in
its ``regions`` parameter (that is what the editor writes), an optional ``region_seed`` input fills
them in while the parameter is empty, and the regions leave again as a ``Region2D`` output so
``regions_to_ds9`` and ``iau_names`` can consume exactly what was extracted.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import numpy as np
import numpy.typing as npt
from astro_canvas_core.io.paths import describe_file, file_fingerprint, resolve_in_workspace
from astro_canvas_core.types import (
    Cube3D,
    File,
    Image2D,
    Region,
    Region2D,
    Spectrum1D,
    SpectrumCollection,
    Table,
)

from astro_canvas.sdk import NodeContext, Param, node
from astro_canvas_rbcodes import _rb
from astro_canvas_rbcodes.kernels import ds9 as D
from astro_canvas_rbcodes.kernels import ifu as K
from astro_canvas_rbcodes.nodes import _ifu_backend as B
from astro_canvas_rbcodes.types import MomentMaps

CATEGORY = "rbcodes/IFU"

WaveParam = Annotated[float, Param(unit="Angstrom", min=0.0, max=1e7, label="Wavelength")]
OptionalWaveParam = Annotated[
    float,
    Param(unit="Angstrom", min=0.0, max=1e7, help="0 means the edge of the cube."),
]
ContinuumParam = Annotated[
    float,
    Param(unit="Angstrom", min=0.0, max=1e7, advanced=True, help="0 disables this window."),
]
CollapseParam = Annotated[
    K.CollapseMethod, Param(label="Method", help="How the selected channels are combined.")
]
RegionsParam = Annotated[
    list[Region],
    Param(
        widget="json",
        label="Apertures",
        help="Drawn in the aperture editor; overrides the region seed when it has rows.",
    ),
]
PathParam = Annotated[str, Param(widget="file", label="File")]


def _wave_window(cube: Cube3D, wmin: float, wmax: float) -> tuple[float | None, float | None]:
    """``0`` means "the edge of the cube" for both ends; the pair is returned in order."""
    lo = float(wmin) if wmin > 0 else None
    hi = float(wmax) if wmax > 0 else None
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _required_window(cube: Cube3D, wmin: float, wmax: float) -> tuple[float, float]:
    lo, hi = _wave_window(cube, wmin, wmax)
    lo = lo if lo is not None else float(cube.wave[0])
    hi = hi if hi is not None else float(cube.wave[-1])
    if lo >= hi:
        raise ValueError("the wavelength window is empty (wmin must be below wmax)")
    return lo, hi


def _image(data: npt.NDArray[np.float64], cube: Cube3D, unit: str | None, **meta: Any) -> Image2D:
    """A collapse as ``Image2D``, carrying the cube's celestial WCS and its provenance."""
    header = {
        key: value
        for key, value in cube.header.items()
        if key in ("OBJECT", "INSTRUME", "TELESCOP", "BUNIT", "_SOURCE")
    }
    header.update({f"_{k.upper()}": v for k, v in meta.items()})
    header["_RBCODES"] = _rb.provenance()
    wcs = cube.wcs
    if wcs is not None and int(wcs.get("naxis", 0)) > 2:
        wcs = _spatial_wcs(wcs)
    return Image2D(data=np.asarray(data, dtype=np.float32), header=header, wcs=wcs, unit=unit)


def _spatial_wcs(wcs: dict[str, Any]) -> dict[str, Any]:
    """The first two axes of a cube WCS dict (``spatial_header`` without the FITS round-trip)."""
    out: dict[str, Any] = {k: v for k, v in wcs.items() if k not in ("cd", "pc", "shape")}
    out["naxis"] = 2
    for key in ("ctype", "crval", "crpix", "cdelt", "cunit"):
        if key in wcs:
            out[key] = list(wcs[key])[:2]
    if "shape" in wcs:
        out["shape"] = list(wcs["shape"])[:2]
    for key in ("cd", "pc"):
        if key in wcs:
            out[key] = [[float(wcs[key][i][j]) for j in range(2)] for i in range(2)]
    return out


def _unit(cube: Cube3D) -> str | None:
    value = cube.header.get("BUNIT")
    return str(value) if value else None


# --- collapses ---------------------------------------------------------------------------------


@node(
    id="rbcodes.ifu.whitelight",
    name="White Light",
    category=CATEGORY,
    icon="sun",
    cost="auto",
    preview="image-thumb",
)
def whitelight(
    cube: Cube3D,
    wmin: OptionalWaveParam = 0.0,
    wmax: OptionalWaveParam = 0.0,
    method: CollapseParam = "mean",
    ctx: NodeContext | None = None,
) -> Image2D:
    """Collapse a cube along the spectral axis into one image (``build_whitelight``).

    Args:
        cube: The IFU cube.
        wmin: Blue edge of the band (0: the first channel).
        wmax: Red edge of the band (0: the last channel).
        method: Combine the channels by ``mean``, ``sum`` or ``median`` (all NaN-aware).

    Returns:
        The collapsed image with the cube's spatial WCS.
    """
    lo, hi = _wave_window(cube, wmin, wmax)
    data = B.build_whitelight(cube.flux, cube.wave, lo, hi, method)
    return _image(data, cube, _unit(cube), band=[lo, hi], method=method, kind="whitelight")


@node(
    id="rbcodes.ifu.narrowband",
    name="Narrow Band",
    category=CATEGORY,
    icon="scan-line",
    cost="auto",
    preview="image-thumb",
)
def narrowband(
    cube: Cube3D,
    wmin: WaveParam = 0.0,
    wmax: WaveParam = 0.0,
    method: CollapseParam = "mean",
    ctx: NodeContext | None = None,
) -> Image2D:
    """Collapse an explicit wavelength window into an image (``build_narrowband``).

    Args:
        cube: The IFU cube.
        wmin: Blue edge of the window.
        wmax: Red edge of the window.
        method: Combine the channels by ``mean``, ``sum`` or ``median``.

    Returns:
        The narrow-band image.
    """
    lo, hi = _required_window(cube, wmin, wmax)
    data = B.build_whitelight(cube.flux, cube.wave, lo, hi, method)
    return _image(data, cube, _unit(cube), band=[lo, hi], method=method, kind="narrowband")


@node(
    id="rbcodes.ifu.continuum_sub",
    name="Continuum-Subtracted Image",
    category=CATEGORY,
    icon="minus",
    cost="auto",
    preview="image-thumb",
)
def continuum_sub(
    cube: Cube3D,
    wmin: WaveParam = 0.0,
    wmax: WaveParam = 0.0,
    bcont_min: ContinuumParam = 0.0,
    bcont_max: ContinuumParam = 0.0,
    rcont_min: ContinuumParam = 0.0,
    rcont_max: ContinuumParam = 0.0,
    method: CollapseParam = "mean",
    ctx: NodeContext | None = None,
) -> Image2D:
    """Narrow-band image minus the mean of one or two continuum windows (``build_continuum_sub``).

    Args:
        cube: The IFU cube.
        wmin: Blue edge of the on-band window.
        wmax: Red edge of the on-band window.
        bcont_min: Blue edge of the blue continuum window.
        bcont_max: Red edge of the blue continuum window.
        rcont_min: Blue edge of the red continuum window (0: use only the blue one).
        rcont_max: Red edge of the red continuum window.
        method: Combine the channels by ``mean``, ``sum`` or ``median``.

    Returns:
        The continuum-subtracted image.
    """
    lo, hi = _required_window(cube, wmin, wmax)
    if not (bcont_min > 0 and bcont_max > 0):
        raise ValueError("a blue continuum window is required")
    red = (rcont_min, rcont_max) if rcont_min > 0 and rcont_max > 0 else (None, None)
    data = B.build_continuum_sub(
        cube.flux, cube.wave, lo, hi, bcont_min, bcont_max, red[0], red[1], method
    )
    return _image(
        data,
        cube,
        _unit(cube),
        band=[lo, hi],
        continuum=[bcont_min, bcont_max, red[0], red[1]],
        kind="continuum_sub",
    )


@node(id="rbcodes.ifu.subcube", name="Subcube", category=CATEGORY, icon="crop", cost="auto")
def subcube(
    cube: Cube3D,
    wmin: OptionalWaveParam = 0.0,
    wmax: OptionalWaveParam = 0.0,
    x0: Annotated[int, Param(min=0, max=100000, label="x from")] = 0,
    x1: Annotated[int, Param(min=0, max=100000, label="x to", help="0 means the right edge.")] = 0,
    y0: Annotated[int, Param(min=0, max=100000, label="y from")] = 0,
    y1: Annotated[int, Param(min=0, max=100000, label="y to", help="0 means the top edge.")] = 0,
    ctx: NodeContext | None = None,
) -> Cube3D:
    """Cut a cube down in wavelength and in the spatial plane (``IFUCube.crop``).

    ``CRPIX`` is shifted with the cut so the WCS still points at the same sky, which is what makes
    the smaller cube a drop-in replacement upstream of the collapses and the aperture editor.

    Args:
        cube: The IFU cube.
        wmin: Blue edge to keep (0: the first channel).
        wmax: Red edge to keep (0: the last channel).
        x0: First column to keep (0-based, inclusive).
        x1: Last column to keep, exclusive (0: to the right edge).
        y0: First row to keep (0-based, inclusive).
        y1: Last row to keep, exclusive (0: to the top edge).

    Returns:
        The cropped cube.
    """
    nz, ny, nx = cube.shape
    lo, hi = _wave_window(cube, wmin, wmax)
    channels = cube.band(lo, hi)
    xa, xb = int(x0), int(x1) if x1 > 0 else nx
    ya, yb = int(y0), int(y1) if y1 > 0 else ny
    if not (0 <= xa < xb <= nx and 0 <= ya < yb <= ny):
        raise ValueError(f"the box [{xa}:{xb}, {ya}:{yb}] is outside a {ny} x {nx} field")
    flux = np.ascontiguousarray(cube.flux[channels, ya:yb, xa:xb])
    var = None if cube.var is None else np.ascontiguousarray(cube.var[channels, ya:yb, xa:xb])
    header = dict(cube.header)
    header["_CROP"] = [xa, xb, ya, yb]
    return Cube3D(
        flux=flux,
        var=var,
        wave=cube.wave[channels],
        wcs=_shift_wcs(cube.wcs, xa, ya, int(np.flatnonzero(channels)[0])),
        header=header,
        instrument=cube.instrument,
    )


def _shift_wcs(wcs: dict[str, Any] | None, dx: int, dy: int, dz: int) -> dict[str, Any] | None:
    """``CRPIX`` follows a crop; FITS pixels are 1-based, the offsets here are 0-based."""
    if wcs is None:
        return None
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in wcs.items()}
    crpix = [float(v) for v in out.get("crpix", [])]
    for axis, shift in enumerate((dx, dy, dz)):
        if axis < len(crpix):
            crpix[axis] -= shift
    if crpix:
        out["crpix"] = crpix
    return out


# --- apertures ---------------------------------------------------------------------------------


@node(
    id="rbcodes.ifu.aperture_extract",
    name="Aperture Extract",
    category=CATEGORY,
    icon="circle-dot",
    cost="auto",
    editor="aperture-editor",
    outputs=("spectra", "regions"),
)
def aperture_extract(
    cube: Cube3D,
    regions: RegionsParam = [],  # noqa: B006 - a param default, never mutated
    method: Annotated[
        K.ExtractMethod,
        Param(label="Extraction", help="How the spaxels under each aperture are combined."),
    ] = "sum",
    background: Annotated[
        Literal["none", "mean", "median"],
        Param(label="Background", help="Subtract the level of the background apertures."),
    ] = "none",
    region_seed: Region2D | None = None,
    ctx: NodeContext | None = None,
) -> tuple[SpectrumCollection, Region2D]:
    """Extract one spectrum per aperture drawn on the cube (``processing.aperture_extract``).

    Apertures marked ``background`` are not extracted: they estimate the sky level that
    ``background`` subtracts from every source spectrum, exactly as rb_ifuview's annulus does.

    Args:
        cube: The IFU cube.
        regions: The apertures, in pixel (and sky) coordinates. Drawn in the aperture editor.
        method: ``sum`` (variance propagated), ``mean``, ``median`` or ``variance_weighted``
            (quasi-optimal, needs a variance cube).
        background: ``none``, or the statistic used over the background apertures.
        region_seed: Apertures to start from while ``regions`` is empty (e.g. a ds9 file).

    Returns:
        spectra: One spectrum per source aperture, labelled by the aperture.
        regions: The apertures that were used, with their sky coordinates filled in.
    """
    rows = list(regions) if regions else list(region_seed.regions if region_seed else [])
    if not rows:
        raise ValueError("draw at least one aperture (or connect a region seed)")
    _, ny, nx = cube.shape
    mapper = D.SkyMapper.from_dict(cube.wcs)
    rows = [D.with_sky(row, mapper) for row in rows]
    sources = [row for row in rows if row.role == "source"]
    if not sources:
        raise ValueError("every aperture is marked as background; mark at least one as a source")
    bg_mask = D.combined_mask(rows, ny, nx, role="background")
    if background != "none" and not bg_mask.any():
        raise ValueError("background subtraction needs at least one background aperture")

    items: list[Spectrum1D] = []
    labels: list[str] = []
    for index, region in enumerate(sources):
        mask = D.region_mask(region, ny, nx)
        if not mask.any():
            raise ValueError(f"aperture {region.label or index + 1} covers no spaxel of the cube")
        flux, error = B.extract(cube.flux, cube.var, mask, method)
        if background != "none":
            flux = B.subtract_background(flux, cube.flux, bg_mask, background)
        label = region.label or f"{region.shape} {index + 1}"
        items.append(
            Spectrum1D(
                wave=np.asarray(cube.wave, dtype=np.float64),
                flux=flux,
                error=error,
                flux_unit=_unit(cube) or "",
                meta={
                    "aperture": label,
                    "shape": region.shape,
                    "n_spaxels": int(mask.sum()),
                    "method": method,
                    "background": background,
                    **_rb.provenance(),
                },
            )
        )
        labels.append(label)
    return SpectrumCollection(items=items, labels=labels), Region2D(regions=rows)


@node(
    id="rbcodes.ifu.regions_from_ds9",
    name="Regions from ds9",
    category=CATEGORY,
    icon="file-input",
    fingerprint=file_fingerprint,
)
def regions_from_ds9(
    path: PathParam = "",
    reference: Image2D | None = None,
    ctx: NodeContext | None = None,
) -> Region2D:
    """Read a ds9 ``.reg`` file into apertures (``spatial_mask.parse_ds9_regions``).

    Image-coordinate files need nothing else; sky-coordinate files need ``reference`` (any image or
    collapse of the cube) to turn degrees back into pixels. Excluded shapes and annotation-only
    shapes (compass, ruler, vector, ...) are skipped.

    Args:
        path: Workspace-relative ``.reg`` file.
        reference: An image whose WCS resolves sky coordinates.

    Returns:
        The apertures, with pixel and (when a WCS was available) sky coordinates.
    """
    if not path:
        raise ValueError("choose a .reg file to load")
    root = _workspace(ctx)
    target = resolve_in_workspace(root, path)
    mapper = D.SkyMapper.from_dict(reference.wcs) if reference is not None else None
    rows = D.from_ds9(target.read_text(encoding="utf-8"), mapper)
    if not rows:
        raise ValueError(f"{target.name} has no circle/box/annulus/polygon region this pack reads")
    return Region2D(regions=rows)


@node(
    id="rbcodes.ifu.regions_to_ds9",
    name="Regions to ds9",
    category=CATEGORY,
    icon="file-output",
)
def regions_to_ds9(
    regions: Region2D,
    path: Annotated[str, Param(label="Output path")] = "outputs/apertures.reg",
    frame: Annotated[
        Literal["image", "fk5", "icrs"],
        Param(label="Coordinates", help="Pixel coordinates, or sky when the regions carry one."),
    ] = "image",
    ctx: NodeContext | None = None,
) -> File:
    """Write apertures as a ds9 region file (``spatial_mask.regions_to_ds9_text``).

    Args:
        regions: The apertures to write.
        path: Workspace-relative output path (folders are created).
        frame: ``image`` writes 1-based pixels; ``fk5`` (what rb_ifuview writes) and ``icrs``
            write degrees with arcsecond sizes. Pick the one the cube's header declares - the two
            sky frames differ by about 0.03 arcseconds.

    Returns:
        The written file.
    """
    root = _workspace(ctx)
    target = resolve_in_workspace(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        D.to_ds9(regions.regions, sky=frame != "image", frame=frame), encoding="utf-8"
    )
    return describe_file(root, target)


@node(
    id="rbcodes.ifu.iau_names",
    name="IAU Names",
    category=CATEGORY,
    icon="tag",
    preview="table-head",
)
def iau_names(
    regions: Region2D,
    reference: Image2D | None = None,
    prefix: Annotated[str, Param(label="Prefix", help="Prepended to every designation.")] = "J",
    ctx: NodeContext | None = None,
) -> Table:
    """Name every aperture after its sky position (``spatial_mask.iau_name``).

    The names are what rb_ifuview writes extracted spectra as, so a batch of apertures keeps its
    identity across files.

    Args:
        regions: The apertures to name.
        reference: An image whose WCS resolves apertures that carry no sky coordinates.
        prefix: Prefix of the designation (``J`` gives ``J100828.8+213336``).

    Returns:
        A table of ``label``, ``name``, ``ra``, ``dec``, ``shape``, ``role`` and pixel centres.
    """
    mapper = D.SkyMapper.from_dict(reference.wcs) if reference is not None else None
    names: list[str] = []
    labels: list[str] = []
    ras: list[float] = []
    decs: list[float] = []
    shapes: list[str] = []
    roles: list[str] = []
    xs: list[float] = []
    ys: list[float] = []
    for index, region in enumerate(regions.regions):
        cx, cy = D.region_center(region)
        sky = region.sky
        if not sky and mapper is not None:
            sky = D.with_sky(region, mapper).sky
        ra, dec = (float(sky[0]), float(sky[1])) if sky else (float("nan"), float("nan"))
        names.append(D.iau_name(ra, dec, prefix) if sky else f"{prefix}{index + 1:03d}")
        labels.append(region.label or f"{region.shape} {index + 1}")
        ras.append(ra)
        decs.append(dec)
        shapes.append(region.shape)
        roles.append(region.role)
        xs.append(cx)
        ys.append(cy)
    return Table(
        columns={
            "label": np.asarray(labels, dtype=np.str_),
            "name": np.asarray(names, dtype=np.str_),
            "ra": np.asarray(ras, dtype=np.float64),
            "dec": np.asarray(decs, dtype=np.float64),
            "x": np.asarray(xs, dtype=np.float64),
            "y": np.asarray(ys, dtype=np.float64),
            "shape": np.asarray(shapes, dtype=np.str_),
            "role": np.asarray(roles, dtype=np.str_),
        },
        units={"ra": "deg", "dec": "deg", "x": "pixel", "y": "pixel"},
        meta=_rb.provenance(prefix=prefix),
    )


# --- moment maps -------------------------------------------------------------------------------


@node(
    id="rbcodes.ifu.moment_maps",
    name="Moment Maps",
    category=CATEGORY,
    icon="waves",
    cost="expensive",
)
def moment_maps(
    cube: Cube3D,
    wmin: WaveParam = 0.0,
    wmax: WaveParam = 0.0,
    lambda_rest: Annotated[
        float,
        Param(
            unit="Angstrom",
            min=0.0,
            max=1e7,
            label="Line centre",
            help="Observed wavelength that maps to v = 0.",
        ),
    ] = 0.0,
    bcont_min: ContinuumParam = 0.0,
    bcont_max: ContinuumParam = 0.0,
    rcont_min: ContinuumParam = 0.0,
    rcont_max: ContinuumParam = 0.0,
    subtract_continuum: Annotated[
        bool, Param(label="Subtract continuum", help="Fit a linear baseline over both windows.")
    ] = True,
    snr_min: Annotated[
        float,
        Param(min=0.0, max=1000.0, label="SNR threshold", help="Blank m1/m2 below this SNR."),
    ] = 0.0,
    ctx: NodeContext | None = None,
) -> MomentMaps:
    """Moment 0, 1 and 2 of one emission line, plus its SNR map (``processing.moment_maps``).

    With both continuum windows given, a per-spaxel linear baseline is fitted through them and
    removed before the moments (``subtract_linear_continuum``), and they also provide the noise
    estimate when the cube carries no variance.

    Args:
        cube: The IFU cube.
        wmin: Blue edge of the line window.
        wmax: Red edge of the line window.
        lambda_rest: Observed wavelength of the line centre (v = 0).
        bcont_min: Blue edge of the blue continuum window.
        bcont_max: Red edge of the blue continuum window.
        rcont_min: Blue edge of the red continuum window.
        rcont_max: Red edge of the red continuum window.
        subtract_continuum: Remove the linear baseline through the two windows first.
        snr_min: Blank the velocity and dispersion maps where the SNR is below this.

    Returns:
        The moment maps with the cube's spatial WCS.
    """
    lo, hi = _required_window(cube, wmin, wmax)
    rest = float(lambda_rest) if lambda_rest > 0 else (lo + hi) / 2.0
    blue = (bcont_min, bcont_max) if bcont_min > 0 and bcont_max > 0 else None
    red = (rcont_min, rcont_max) if rcont_min > 0 and rcont_max > 0 else None
    flux: npt.NDArray[Any] = cube.flux
    if subtract_continuum and blue is not None and red is not None:
        flux = B.subtract_linear_continuum(cube.flux, cube.wave, *blue, *red)
    if ctx is not None:
        ctx.progress(0.3, "moments")
    m0 = B.moment(flux, cube.wave, lo, hi, 0, rest)
    m1 = B.moment(flux, cube.wave, lo, hi, 1, rest)
    m2 = B.moment(flux, cube.wave, lo, hi, 2, rest)
    if ctx is not None:
        ctx.progress(0.8, "signal-to-noise")
    snr = B.snr_map(m0, flux, cube.wave, lo, hi, var=cube.var, cont1=blue, cont2=red)
    if snr is not None and snr_min > 0:
        faint = ~(snr >= snr_min)
        m1 = np.where(faint, np.nan, m1)
        m2 = np.where(faint, np.nan, m2)
    return MomentMaps(
        m0=np.asarray(m0, dtype=np.float32),
        m1=np.asarray(m1, dtype=np.float32),
        m2=np.asarray(m2, dtype=np.float32),
        snr=None if snr is None else np.asarray(snr, dtype=np.float32),
        wcs=_spatial_wcs(cube.wcs) if cube.wcs else None,
        unit=_unit(cube),
        lambda_rest=rest,
        window=(lo, hi),
        meta=_rb.provenance(
            continuum=[blue, red], subtracted=bool(subtract_continuum and blue and red)
        ),
    )


@node(
    id="rbcodes.ifu.snr_map",
    name="SNR Map",
    category=CATEGORY,
    icon="activity",
    cost="auto",
    preview="image-thumb",
)
def snr_map(
    cube: Cube3D,
    wmin: WaveParam = 0.0,
    wmax: WaveParam = 0.0,
    bcont_min: ContinuumParam = 0.0,
    bcont_max: ContinuumParam = 0.0,
    rcont_min: ContinuumParam = 0.0,
    rcont_max: ContinuumParam = 0.0,
    ctx: NodeContext | None = None,
) -> Image2D:
    """Per-spaxel signal-to-noise of the integrated line flux (``compute_snr_map``).

    The noise comes from the variance cube when there is one, and from the scatter in the
    continuum windows otherwise; without either the node reports that it cannot measure noise.

    Args:
        cube: The IFU cube.
        wmin: Blue edge of the line window.
        wmax: Red edge of the line window.
        bcont_min: Blue edge of the blue continuum window.
        bcont_max: Red edge of the blue continuum window.
        rcont_min: Blue edge of the red continuum window.
        rcont_max: Red edge of the red continuum window.

    Returns:
        The SNR map.
    """
    lo, hi = _required_window(cube, wmin, wmax)
    blue = (bcont_min, bcont_max) if bcont_min > 0 and bcont_max > 0 else None
    red = (rcont_min, rcont_max) if rcont_min > 0 and rcont_max > 0 else None
    m0 = B.moment(cube.flux, cube.wave, lo, hi, 0, None)
    snr = B.snr_map(m0, cube.flux, cube.wave, lo, hi, var=cube.var, cont1=blue, cont2=red)
    if snr is None:
        raise ValueError(
            "no noise estimate: the cube has no variance and no continuum window was given"
        )
    return _image(snr, cube, None, band=[lo, hi], kind="snr")


def _workspace(ctx: NodeContext | None) -> Any:
    from pathlib import Path  # noqa: PLC0415

    return Path(ctx.workspace) if ctx is not None else Path.cwd()
