"""A one-node example pack: ``rbcodes.utils.compute_SNR_1d.estimate_snr`` as a canvas node.

The tutorial that builds this is `docs/packs/tutorial.md`. Nothing here is shipped with the app;
it is the smallest complete pack, kept in the repository so the tutorial's code is tested rather
than transcribed.
"""

from __future__ import annotations

from astro_canvas.sdk import PackRegistry

__version__ = "0.1.0"


def register(registry: PackRegistry) -> None:
    """Entry point (``astro_canvas.nodes`` -> ``snr``).

    The import is inside the function so ``import astro_canvas_snr`` stays cheap: the app
    imports every pack's module at startup to find this function, and only calls it when it is
    actually building the registry.
    """
    from astro_canvas_snr import nodes  # noqa: PLC0415

    registry.add_module(nodes)


__all__ = ["__version__", "register"]
