"""ds9 region files: read, write and rasterize ``astro.Region2D`` apertures.

Format and conventions follow ``rbcodes.GUIs.ifuviewer.processing.spatial_mask``
(``parse_ds9_regions`` / ``regions_to_ds9_text`` / the ``_mask_*`` rasterizers): ds9 ``image``
coordinates are 1-based, sky coordinates are degrees with sizes in arcseconds, ``box`` carries a
counter-clockwise angle in degrees, and ``# text={...}`` holds the label. Excluded (``-``) shapes
and annotation-only shapes (compass, vector, ruler, ...) are dropped: this pack only cares about
apertures that produce an extraction mask.

``astro.Region2D`` stores every shape twice when a WCS is known — ``pixel`` (0-based) and ``sky``
(degrees / arcsec) — so a workflow keeps working when the same regions are pointed at a differently
gridded cube.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
from astro_canvas_core.types import Region

from astro_canvas_rbcodes.kernels.ifu import annulus_mask, box_mask, circle_mask, polygon_mask

Shape = Literal["circle", "box", "annulus", "polygon"]
SHAPES: tuple[Shape, ...] = ("circle", "box", "annulus", "polygon")
SKY_SYSTEMS = ("fk5", "fk4", "icrs", "galactic", "ecliptic", "wcs")
PIXEL_SYSTEMS = ("image", "physical", "linear")
HEADER = (
    "# Region file format: DS9 version 4.1",
    'global color=green dashlist=8 3 width=1 font="helvetica 10 normal roman" '
    "select=1 highlite=1 dash=0 fixed=0 edit=1 move=1 delete=1 include=1 source=1",
)
_SHAPE_RE = re.compile(r"(\w+)\s*\(([^)]+)\)", re.IGNORECASE)
_TEXT_RE = re.compile(r"text\s*=\s*\{([^}]*)\}", re.IGNORECASE)
_TAG_RE = re.compile(r"tag\s*=\s*\{([^}]*)\}", re.IGNORECASE)


class SkyMapper:
    """The 2-d celestial part of a cube or image WCS, as pixel <-> sky in degrees.

    Wraps ``astropy.wcs.WCS`` so the ds9 helpers stay importable without a WCS in hand; build one
    with ``SkyMapper.from_dict(image.wcs)``, which returns ``None`` when the header has no
    celestial axes.
    """

    def __init__(self, wcs: Any) -> None:
        self.wcs = wcs

    @classmethod
    def from_dict(cls, wcs: dict[str, Any] | None) -> SkyMapper | None:
        """Build a mapper from the plain-dict WCS carried by ``Image2D`` / ``Cube3D``."""
        from astro_canvas_core.io.fits_meta import celestial_wcs  # noqa: PLC0415

        celestial = celestial_wcs(wcs)
        return None if celestial is None else cls(celestial)

    def to_sky(self, x: float, y: float) -> tuple[float, float]:
        """0-based pixel to ``(ra, dec)`` in degrees."""
        world = self.wcs.all_pix2world([[float(x), float(y)]], 0)[0]
        return float(world[0]), float(world[1])

    def to_pixel(self, ra: float, dec: float) -> tuple[float, float]:
        """``(ra, dec)`` in degrees to a 0-based pixel."""
        pixel = self.wcs.all_world2pix([[float(ra), float(dec)]], 0)[0]
        return float(pixel[0]), float(pixel[1])

    def pixel_scale_arcsec(self) -> float:
        """Mean pixel scale in arcseconds (``proj_plane_pixel_scales``)."""
        from astropy.wcs.utils import proj_plane_pixel_scales  # noqa: PLC0415

        return float(np.mean(np.abs(proj_plane_pixel_scales(self.wcs)))) * 3600.0

    def separation_arcsec(self, x0: float, y0: float, x1: float, y1: float) -> float:
        """Great-circle separation between two pixels, in arcseconds (``spatial_mask._sep``)."""
        ra0, dec0 = self.to_sky(x0, y0)
        ra1, dec1 = self.to_sky(x1, y1)
        d_ra = math.radians(ra1 - ra0) * math.cos(math.radians((dec0 + dec1) / 2.0))
        d_dec = math.radians(dec1 - dec0)
        return math.degrees(math.hypot(d_ra, d_dec)) * 3600.0


# --- geometry ----------------------------------------------------------------------------------


def region_center(region: Region) -> tuple[float, float]:
    """The region's centre in 0-based pixels (the polygon's vertex mean)."""
    values = list(region.pixel)
    if region.shape == "polygon":
        xs, ys = values[0::2], values[1::2]
        if not xs:
            return 0.0, 0.0
        return float(np.mean(xs)), float(np.mean(ys))
    return float(values[0]), float(values[1])


def region_mask(region: Region, ny: int, nx: int) -> npt.NDArray[np.bool_]:
    """Rasterize one region's ``pixel`` geometry onto an ``(ny, nx)`` boolean mask."""
    values = [float(v) for v in region.pixel]
    if region.shape == "circle" and len(values) >= 3:
        return circle_mask(ny, nx, values[0], values[1], values[2])
    if region.shape == "annulus" and len(values) >= 4:
        return annulus_mask(ny, nx, values[0], values[1], values[2], values[3])
    if region.shape == "box" and len(values) >= 4:
        angle = values[4] if len(values) > 4 else 0.0
        return box_mask(ny, nx, values[0], values[1], values[2], values[3], angle)
    if region.shape == "polygon" and len(values) >= 6:
        vertices = list(zip(values[0::2], values[1::2], strict=False))
        return polygon_mask(ny, nx, vertices)
    return np.zeros((ny, nx), dtype=bool)


def combined_mask(
    regions: list[Region], ny: int, nx: int, role: str | None = None
) -> npt.NDArray[np.bool_]:
    """Union of the masks of every region (optionally only those with the given ``role``)."""
    mask = np.zeros((ny, nx), dtype=bool)
    for region in regions:
        if role is not None and region.role != role:
            continue
        mask |= region_mask(region, ny, nx)
    return mask


def with_sky(region: Region, mapper: SkyMapper | None) -> Region:
    """A copy of ``region`` whose ``sky`` block is recomputed from its pixel geometry."""
    if mapper is None:
        return region.model_copy(update={"sky": None})
    return region.model_copy(update={"sky": _sky_values(region, mapper)})


def with_pixels(region: Region, mapper: SkyMapper | None) -> Region:
    """A copy of ``region`` whose pixel geometry is recomputed from its ``sky`` block."""
    if mapper is None or not region.sky:
        return region
    return region.model_copy(update={"pixel": _pixel_values(region.shape, region.sky, mapper)})


def _sky_values(region: Region, mapper: SkyMapper) -> list[float]:
    values = [float(v) for v in region.pixel]
    if region.shape == "polygon":
        out: list[float] = []
        for x, y in zip(values[0::2], values[1::2], strict=False):
            ra, dec = mapper.to_sky(x, y)
            out.extend([ra, dec])
        return out
    cx, cy = values[0], values[1]
    ra, dec = mapper.to_sky(cx, cy)
    scale = mapper.pixel_scale_arcsec()
    if region.shape == "circle":
        return [ra, dec, values[2] * scale]
    if region.shape == "annulus":
        return [ra, dec, values[2] * scale, values[3] * scale]
    angle = values[4] if len(values) > 4 else 0.0
    return [ra, dec, values[2] * scale, values[3] * scale, angle]


def _pixel_values(shape: str, sky: list[float], mapper: SkyMapper) -> list[float]:
    if shape == "polygon":
        out: list[float] = []
        for ra, dec in zip(sky[0::2], sky[1::2], strict=False):
            x, y = mapper.to_pixel(ra, dec)
            out.extend([x, y])
        return out
    cx, cy = mapper.to_pixel(sky[0], sky[1])
    scale = mapper.pixel_scale_arcsec()
    if shape == "circle":
        return [cx, cy, sky[2] / scale]
    if shape == "annulus":
        return [cx, cy, sky[2] / scale, sky[3] / scale]
    angle = sky[4] if len(sky) > 4 else 0.0
    return [cx, cy, sky[2] / scale, sky[3] / scale, angle]


# --- writing -----------------------------------------------------------------------------------


def to_ds9(regions: list[Region], sky: bool = False, frame: str = "fk5") -> str:
    """Render regions as ds9 region text (``image`` pixels, or ``frame`` degrees when ``sky``).

    Sky output needs every region to carry a ``sky`` block (``aperture_extract`` writes one
    whenever the cube has a celestial WCS); regions without one fall back to their pixel geometry.
    ``frame`` should name the WCS the coordinates came from - ``icrs`` for a modern header, ``fk5``
    for the label rb_ifuview always writes; the two differ by about 0.03 arcseconds.
    """
    lines = list(HEADER)
    lines.append((frame if frame in SKY_SYSTEMS else "fk5") if sky else "image")
    for region in regions:
        comment = _comment(region)
        if sky and region.sky:
            lines.append(_sky_line(region.shape, [float(v) for v in region.sky]) + comment)
        else:
            lines.append(_pixel_line(region.shape, [float(v) for v in region.pixel]) + comment)
    return "\n".join(lines) + "\n"


def _comment(region: Region) -> str:
    parts = []
    if region.label:
        parts.append(f"text={{{region.label}}}")
    if region.role != "source":
        parts.append(f"tag={{{region.role}}}")
    return f" # {' '.join(parts)}" if parts else ""


def _pixel_line(shape: str, v: list[float]) -> str:
    if shape == "circle":
        return f"circle({v[0] + 1:.4f},{v[1] + 1:.4f},{v[2]:.4f})"
    if shape == "annulus":
        return f"annulus({v[0] + 1:.4f},{v[1] + 1:.4f},{v[2]:.4f},{v[3]:.4f})"
    if shape == "box":
        angle = v[4] if len(v) > 4 else 0.0
        return f"box({v[0] + 1:.4f},{v[1] + 1:.4f},{v[2]:.4f},{v[3]:.4f},{angle:.4f})"
    points = ",".join(f"{value + 1:.4f}" for value in v)
    return f"polygon({points})"


def _sky_line(shape: str, v: list[float]) -> str:
    if shape == "circle":
        return f'circle({v[0]:.6f},{v[1]:.6f},{v[2]:.4f}")'
    if shape == "annulus":
        return f'annulus({v[0]:.6f},{v[1]:.6f},{v[2]:.4f}",{v[3]:.4f}")'
    if shape == "box":
        angle = v[4] if len(v) > 4 else 0.0
        return f'box({v[0]:.6f},{v[1]:.6f},{v[2]:.4f}",{v[3]:.4f}",{angle:.4f})'
    points = ",".join(f"{value:.6f}" for value in v)
    return f"polygon({points})"


# --- reading -----------------------------------------------------------------------------------


def from_ds9(text: str, mapper: SkyMapper | None = None) -> list[Region]:
    """Parse ds9 region text into ``Region`` rows.

    Sky shapes need ``mapper`` to gain pixel geometry; without one they are kept with their sky
    values only when they are already in image coordinates, and skipped otherwise.
    """
    system = "image"
    out: list[Region] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.lower().startswith("global"):
            continue
        lowered = line.lower()
        if lowered in SKY_SYSTEMS or lowered in PIXEL_SYSTEMS:
            system = lowered
            continue
        comment = ""
        if "#" in line:
            line, comment = (part.strip() for part in line.split("#", 1))
        if line.startswith("-"):
            continue  # excluded region
        match = _SHAPE_RE.match(line)
        if match is None:
            continue
        name = match.group(1).lower()
        if name not in SHAPES:
            continue
        shape: Shape = name
        args = [a.strip() for a in match.group(2).split(",")]
        region = _region_from(shape, args, system, comment, mapper)
        if region is not None:
            out.append(region)
    return out


def _region_from(
    shape: Shape, args: list[str], system: str, comment: str, mapper: SkyMapper | None
) -> Region | None:
    """One parsed shape as a ``Region``, or ``None`` when it cannot be placed on the pixel grid."""
    text = _TEXT_RE.search(comment)
    tag = _TAG_RE.search(comment)
    label = text.group(1).strip() if text else ""
    role: Literal["source", "background"] = (
        "background"
        if tag is not None and tag.group(1).strip().lower() == "background"
        else "source"
    )
    sky: list[float] | None = None
    try:
        if system in SKY_SYSTEMS:
            if mapper is None:
                return None  # sky coordinates need a WCS to become pixels
            sky = _parse_sky_args(shape, args)
            pixel = _pixel_values(shape, sky, mapper)
        else:
            pixel = _parse_pixel_args(shape, args)
            if mapper is not None:
                sky = _sky_values(Region(shape=shape, pixel=pixel), mapper)
    except (IndexError, ValueError):
        return None
    return Region(shape=shape, pixel=pixel, sky=sky, label=label or None, role=role)


def _parse_pixel_args(shape: Shape, args: list[str]) -> list[float]:
    values = [_strip_unit(a) for a in args]
    if shape == "polygon":
        return [v - 1.0 for v in values]
    out = [values[0] - 1.0, values[1] - 1.0, *values[2:]]
    if shape == "box" and len(out) == 4:
        out.append(0.0)
    return out


def _parse_sky_args(shape: Shape, args: list[str]) -> list[float]:
    if shape == "polygon":
        return [float(a) for a in args]
    out = [float(args[0]), float(args[1])]
    sizes = args[2:] if shape != "box" else args[2:4]
    out.extend(_parse_size_arcsec(a) for a in sizes)
    if shape == "box":
        out.append(_strip_unit(args[4]) if len(args) > 4 else 0.0)
    return out


def _parse_size_arcsec(text: str) -> float:
    """A ds9 angular size (``12.5"``, ``0.5'``, ``0.01d``, bare degrees) in arcseconds."""
    value = text.strip()
    if value.endswith('"'):
        return float(value[:-1])
    if value.endswith("'"):
        return float(value[:-1]) * 60.0
    if value.lower().endswith("d"):
        return float(value[:-1]) * 3600.0
    if value.lower().endswith("r"):
        return math.degrees(float(value[:-1])) * 3600.0
    return float(value) * 3600.0


def _strip_unit(text: str) -> float:
    return float(re.sub(r"[^\d.eE+\-]", "", text.strip()))


def iau_name(ra_deg: float, dec_deg: float, prefix: str = "J") -> str:
    """IAU-style designation (``J100828.8+213336``) for a sky position, as ``spatial_mask`` does."""
    from astropy import units as u  # noqa: PLC0415
    from astropy.coordinates import SkyCoord  # noqa: PLC0415

    coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
    return f"{prefix}{coord.to_string('hmsdms', sep='', precision=1).replace(' ', '')}"


__all__ = [
    "HEADER",
    "PIXEL_SYSTEMS",
    "SHAPES",
    "SKY_SYSTEMS",
    "Shape",
    "SkyMapper",
    "combined_mask",
    "from_ds9",
    "iau_name",
    "region_center",
    "region_mask",
    "to_ds9",
    "with_pixels",
    "with_sky",
]
