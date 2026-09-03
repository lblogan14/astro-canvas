"""Astro Canvas core node pack: port types and the first ``core.*`` nodes."""

from __future__ import annotations

from astro_canvas.sdk import PackRegistry

__version__ = "0.1.0a0"


def register(registry: PackRegistry) -> None:
    """Entry point (``astro_canvas.nodes`` -> ``core``): register types and nodes."""
    # Lazy so `import astro_canvas_core` stays cheap (astropy/pyarrow load on registration).
    from astro_canvas_core import types  # noqa: PLC0415
    from astro_canvas_core.nodes import list as list_nodes  # noqa: PLC0415
    from astro_canvas_core.nodes import math, note, spec  # noqa: PLC0415

    registry.add_module(types)
    for module in (math, spec, list_nodes, note):
        registry.add_module(module)


__all__ = ["__version__", "register"]
