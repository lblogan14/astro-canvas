"""Generate the Astro Canvas brand mark: ``favicon.svg``, ``favicon.ico``, ``apple-touch-icon``.

The mark is a node card holding a spectrum: a flat continuum with one emission line, an input
port on the left edge and an output port on the right, in the canvas's own Okabe-Ito port
colours. It doubles as an *A*. Geometry lives here so the vector and the rasters cannot drift;
``frontend/src/components/BrandMark.vue`` mirrors the same numbers for the in-app header.

Run it after changing anything below::

    uv run --directory backend python ../scripts/make_icons.py

The rasterisers are hand-rolled (supersampled coverage masks, a minimal PNG writer and a
PNG-in-ICO container) because the backend environment has no image library -- only numpy, which
the SDK already depends on.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "frontend" / "public"

VIEWBOX = 32.0
SUPERSAMPLE = 8

CARD = (16.0, 16.0, 11.0, 11.0, 4.0)  # cx, cy, half-width, half-height, corner radius
CARD_FILL = (0x00, 0x72, 0xB2)  # Okabe-Ito blue, the canvas colour for astro.Spectrum1D
TRACE = ((8.2, 21.0), (13.4, 21.0), (16.0, 10.2), (18.6, 21.0), (23.8, 21.0))
TRACE_WIDTH = 2.6
TRACE_FILL = (0xFF, 0xFF, 0xFF)
IN_PORT = (5.0, 16.0, 2.8, (0xE6, 0x9F, 0x00))  # Okabe-Ito orange
OUT_PORT = (27.0, 16.0, 2.8, (0x00, 0x9E, 0x73))  # Okabe-Ito green

ICO_SIZES = (16, 32, 48)
APPLE_SIZE = 180

Rgb = tuple[int, int, int]


def _grid(size: int) -> tuple[np.ndarray, np.ndarray]:
    """Sample points at the centre of every supersampled pixel, in viewBox units."""
    n = size * SUPERSAMPLE
    axis = (np.arange(n) + 0.5) * (VIEWBOX / n)
    return np.meshgrid(axis, axis)


def _rounded_rect(xx: np.ndarray, yy: np.ndarray) -> np.ndarray:
    cx, cy, hw, hh, r = CARD
    dx = np.abs(xx - cx) - (hw - r)
    dy = np.abs(yy - cy) - (hh - r)
    outside = np.hypot(np.maximum(dx, 0.0), np.maximum(dy, 0.0))
    return outside + np.minimum(np.maximum(dx, dy), 0.0) - r <= 0.0


def _disc(xx: np.ndarray, yy: np.ndarray, cx: float, cy: float, r: float) -> np.ndarray:
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r


def _stroke(xx: np.ndarray, yy: np.ndarray) -> np.ndarray:
    """The trace as round-capped capsules, which is what SVG's round joins draw."""
    mask = np.zeros(xx.shape, dtype=bool)
    for (px, py), (qx, qy) in zip(TRACE, TRACE[1:], strict=False):
        dx, dy = qx - px, qy - py
        t = np.clip(((xx - px) * dx + (yy - py) * dy) / (dx * dx + dy * dy), 0.0, 1.0)
        near = (xx - (px + t * dx)) ** 2 + (yy - (py + t * dy)) ** 2
        mask |= near <= (TRACE_WIDTH / 2) ** 2
    return mask


def _paint(buf: np.ndarray, mask: np.ndarray, rgb: Rgb) -> None:
    for channel in range(3):
        buf[..., channel] = np.where(mask, rgb[channel], buf[..., channel])
    buf[..., 3] = np.where(mask, 1.0, buf[..., 3])


def render(size: int, *, full_bleed: bool = False) -> np.ndarray:
    """Rasterise the mark to an RGBA array. ``full_bleed`` drops the corner radius and ports."""
    xx, yy = _grid(size)
    buf = np.zeros((size * SUPERSAMPLE, size * SUPERSAMPLE, 4), dtype=np.float64)
    if full_bleed:
        _paint(buf, np.ones(xx.shape, dtype=bool), CARD_FILL)
    else:
        _paint(buf, _rounded_rect(xx, yy), CARD_FILL)
    _paint(buf, _stroke(xx, yy), TRACE_FILL)
    if not full_bleed:
        for cx, cy, r, rgb in (IN_PORT, OUT_PORT):
            _paint(buf, _disc(xx, yy, cx, cy, r), rgb)
    return _downsample(buf, size)


def _downsample(buf: np.ndarray, size: int) -> np.ndarray:
    small = buf.reshape(size, SUPERSAMPLE, size, SUPERSAMPLE, 4).mean(axis=(1, 3))
    alpha = small[..., 3]
    out = np.zeros((size, size, 4), dtype=np.uint8)
    for channel in range(3):
        # Un-premultiply so edge pixels keep their colour instead of fading toward black.
        straight = np.where(alpha > 0, small[..., channel] / np.maximum(alpha, 1e-9), 0.0)
        out[..., channel] = np.clip(np.rint(straight), 0, 255)
    out[..., 3] = np.clip(np.rint(alpha * 255), 0, 255)
    return out


def png_bytes(rgba: np.ndarray) -> bytes:
    """Encode an RGBA array as a PNG (colour type 6, no filtering)."""
    height, width, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[row].tobytes() for row in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(raw, 9)),
            chunk(b"IEND", b""),
        )
    )


def ico_bytes(pngs: dict[int, bytes]) -> bytes:
    """Wrap PNG images in an ICO container (Vista+ reads PNG-compressed entries)."""
    entries, blobs = b"", b""
    offset = 6 + 16 * len(pngs)
    for size, data in sorted(pngs.items()):
        entries += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return struct.pack("<HHH", 0, 1, len(pngs)) + entries + blobs


def svg_text() -> str:
    cx, cy, hw, hh, r = CARD
    trace = f"M{TRACE[0][0]} {TRACE[0][1]}" + "".join(f" L{x} {y}" for x, y in TRACE[1:])
    ports = "\n".join(
        f'  <circle cx="{px}" cy="{py}" r="{pr}" fill="{_hex(rgb)}" />'
        for px, py, pr, rgb in (IN_PORT, OUT_PORT)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" role="img"
     aria-label="Astro Canvas">
  <title>Astro Canvas</title>
  <rect x="{cx - hw}" y="{cy - hh}" width="{hw * 2}" height="{hh * 2}" rx="{r}"
        fill="{_hex(CARD_FILL)}" />
  <path d="{trace}" fill="none" stroke="{_hex(TRACE_FILL)}" stroke-width="{TRACE_WIDTH}"
        stroke-linecap="round" stroke-linejoin="round" />
{ports}
</svg>
"""


def _hex(rgb: Rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def main() -> int:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    written = []

    svg = PUBLIC / "favicon.svg"
    svg.write_text(svg_text(), encoding="utf-8")
    written.append(svg)

    ico = PUBLIC / "favicon.ico"
    ico.write_bytes(ico_bytes({size: png_bytes(render(size)) for size in ICO_SIZES}))
    written.append(ico)

    apple = PUBLIC / "apple-touch-icon.png"
    apple.write_bytes(png_bytes(render(APPLE_SIZE, full_bleed=True)))
    written.append(apple)

    for path in written:
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
