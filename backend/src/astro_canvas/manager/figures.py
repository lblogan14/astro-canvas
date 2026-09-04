"""PNG previews for bundle ``figures/`` and gallery cards (design 7.2, 7.3).

The browser draws every preview in the app, but a bundle has to carry pictures a *file manager*
can show, so the same ``summary()`` payloads are rasterised here. Design 7.2 allows either
server-side matplotlib or "stored PNG summaries"; this is the second, written against ``zlib``
alone so the server keeps its deliberately small dependency set (CLAUDE.md) and so a headless
lab install needs no plotting stack.

What it draws: a curve (anything summarising as ``wave``/``flux`` or ``x``/``y``) and an image
tile (2-D ``tile``/``image``/``moment0``). A value with neither -- a bare number -- has no
picture, and ``render_summary_png`` returns ``None`` rather than inventing one.
"""

from __future__ import annotations

import base64
import math
import struct
import zlib
from collections.abc import Sequence
from typing import Any

import structlog

from astro_canvas.sdk import PortType

log = structlog.get_logger("astro_canvas.bundles")

WIDTH, HEIGHT = 576, 324
"""16:9, the aspect the gallery card crops to."""
PADDING = 18
MAX_POINTS = 4000
"""Longer series are thinned; a card is 576 px wide and nobody reads sample 4001."""

BACKGROUND = (12, 16, 24)
FOREGROUND = (91, 141, 239)
GRID = (38, 46, 60)

VIRIDIS: tuple[tuple[int, int, int], ...] = (
    (68, 1, 84),
    (72, 40, 120),
    (62, 74, 137),
    (49, 104, 142),
    (38, 130, 142),
    (31, 158, 137),
    (53, 183, 121),
    (109, 205, 89),
    (180, 222, 44),
    (253, 231, 37),
)


class Canvas:
    """A tiny RGB raster with the two primitives a preview needs."""

    def __init__(self, width: int = WIDTH, height: int = HEIGHT) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(BACKGROUND * (width * height))

    def set(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 3
            self.pixels[offset : offset + 3] = bytes(color)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        """Bresenham, thickened by one pixel vertically so a thin curve stays visible."""
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.set(x0, y0, color)
            self.set(x0, y0 + 1, color)
            if x0 == x1 and y0 == y1:
                return
            doubled = 2 * err
            if doubled >= dy:
                err += dy
                x0 += sx
            if doubled <= dx:
                err += dx
                y0 += sy

    def frame(self, color: tuple[int, int, int] = GRID) -> None:
        for x in range(PADDING, self.width - PADDING):
            self.set(x, PADDING, color)
            self.set(x, self.height - PADDING, color)
        for y in range(PADDING, self.height - PADDING):
            self.set(PADDING, y, color)
            self.set(self.width - PADDING, y, color)

    def png(self) -> bytes:
        """Encode as a non-interlaced 8-bit RGB PNG (filter 0 on every scanline)."""
        raw = bytearray()
        stride = self.width * 3
        for y in range(self.height):
            raw.append(0)
            raw += self.pixels[y * stride : (y + 1) * stride]
        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        return b"".join(
            [
                b"\x89PNG\r\n\x1a\n",
                _chunk(b"IHDR", header),
                _chunk(b"IDAT", zlib.compress(bytes(raw), 6)),
                _chunk(b"IEND", b""),
            ]
        )


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _thin(values: Sequence[Any]) -> list[Any]:
    step = max(1, len(values) // MAX_POINTS)
    return list(values[::step])


def _finite_pairs(x: Sequence[Any], y: Sequence[Any]) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for a, b in zip(x, y, strict=False):
        try:
            fa, fb = float(a), float(b)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fa) and math.isfinite(fb):
            xs.append(fa)
            ys.append(fb)
    return xs, ys


def _colormap(fraction: float) -> tuple[int, int, int]:
    position = min(max(fraction, 0.0), 1.0) * (len(VIRIDIS) - 1)
    low = int(position)
    high = min(low + 1, len(VIRIDIS) - 1)
    blend = position - low
    a, b = VIRIDIS[low], VIRIDIS[high]
    return (
        int(a[0] + (b[0] - a[0]) * blend),
        int(a[1] + (b[1] - a[1]) * blend),
        int(a[2] + (b[2] - a[2]) * blend),
    )


def draw_curve(canvas: Canvas, x: Sequence[Any], y: Sequence[Any]) -> bool:
    xs, ys = _finite_pairs(_thin(x), _thin(y))
    if len(xs) < 2:
        return False
    x_lo, x_hi = min(xs), max(xs)
    y_lo, y_hi = min(ys), max(ys)
    x_span = (x_hi - x_lo) or 1.0
    y_span = (y_hi - y_lo) or 1.0
    inner_w = canvas.width - 2 * PADDING
    inner_h = canvas.height - 2 * PADDING
    canvas.frame()
    previous: tuple[int, int] | None = None
    for px, py in zip(xs, ys, strict=True):
        sx = PADDING + int((px - x_lo) / x_span * inner_w)
        sy = canvas.height - PADDING - int((py - y_lo) / y_span * inner_h)
        if previous is not None:
            canvas.line(previous[0], previous[1], sx, sy, FOREGROUND)
        previous = (sx, sy)
    return True


def draw_tile(canvas: Canvas, rows: Sequence[Sequence[Any]]) -> bool:
    """Nearest-neighbour resample of a 2-D tile, colour-mapped between its finite extremes."""
    height = len(rows)
    width = max((len(row) for row in rows), default=0)
    if height == 0 or width == 0:
        return False
    finite = [
        float(v) for row in rows for v in row if isinstance(v, int | float) and float(v) == float(v)
    ]
    if not finite:
        return False
    low, high = min(finite), max(finite)
    span = (high - low) or 1.0
    for sy in range(canvas.height):
        row = rows[min(height - 1, sy * height // canvas.height)]
        for sx in range(canvas.width):
            if not row:
                continue
            value = row[min(len(row) - 1, sx * len(row) // canvas.width)]
            try:
                scaled = (float(value) - low) / span
            except (TypeError, ValueError):
                continue
            canvas.set(sx, canvas.height - 1 - sy, _colormap(scaled))
    return True


def decode_tile(payload: dict[str, Any]) -> list[list[float]] | None:
    """Rows of a base64 float32 image tile (``image_tile`` in the core pack's port types).

    Summaries carry big images as ``{"width", "height", "dtype": "f4", "b64"}`` rather than
    nested lists, so the card renderer has to speak that shape too.
    """
    width = int(payload.get("width", 0))
    height = int(payload.get("height", 0))
    if width <= 0 or height <= 0 or payload.get("dtype") != "f4":
        return None
    try:
        raw = base64.b64decode(str(payload.get("b64", "")), validate=True)
    except (ValueError, TypeError):
        return None
    if len(raw) < width * height * 4:
        return None
    values = struct.unpack(f"<{width * height}f", raw[: width * height * 4])
    return [list(values[row * width : (row + 1) * width]) for row in range(height)]


def render_summary_png(value: PortType, *, title: str = "") -> bytes | None:
    """Draw one output value as a PNG, or ``None`` when there is nothing to draw.

    Works off ``summary()`` -- the same payload the node thumbnails use -- so a new port type
    gets a bundle figure the moment it summarises a curve or an image. ``title`` is accepted for
    call-site symmetry with a future labelled renderer; this one draws no text.
    """
    del title
    try:
        summary = value.summary()
    except Exception as exc:  # noqa: BLE001 - a figure is a nicety, never a failure
        log.warning("summary failed", type_id=value.type_id(), error=str(exc))
        return None
    canvas = Canvas()
    if not _draw(canvas, summary):
        return None
    return canvas.png()


def _draw(canvas: Canvas, summary: dict[str, Any]) -> bool:
    """Render whichever shape the summary carries; ``False`` when none of them fits."""
    for x_key, y_key in (("wave", "flux"), ("x", "y"), ("z", "corr")):
        x, y = summary.get(x_key), summary.get(y_key)
        if isinstance(x, list) and isinstance(y, list) and draw_curve(canvas, x, y):
            return True
    for key in ("tile", "image", "moment0", "data", "white_light"):
        tile = summary.get(key)
        if isinstance(tile, list) and tile and isinstance(tile[0], list):
            return draw_tile(canvas, tile)
        if isinstance(tile, dict):
            rows = decode_tile(tile)
            if rows is not None and draw_tile(canvas, rows):
                return True
    return False


__all__ = [
    "HEIGHT",
    "WIDTH",
    "Canvas",
    "decode_tile",
    "draw_curve",
    "draw_tile",
    "render_summary_png",
]
