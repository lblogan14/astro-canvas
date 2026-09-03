"""``core.note.*`` nodes."""

from __future__ import annotations

from typing import Annotated

from astro_canvas.sdk import Param, node


@node(id="core.note.markdown", name="Note", category="Utilities", icon="sticky-note")
def markdown(text: Annotated[str, Param(widget="markdown")] = "") -> None:
    """A Markdown note on the canvas. It has no ports and never executes anything.

    Args:
        text: Markdown source rendered inside the node.
    """
