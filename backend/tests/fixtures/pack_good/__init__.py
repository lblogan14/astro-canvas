"""Fixture pack that registers cleanly."""

from __future__ import annotations

from astro_canvas.sdk import PackRegistry, PortType, node, port_type


@port_type(id="fixture.Token", color="#123456")
class Token(PortType):
    """A fixture port type."""

    text: str


@node(id="good.text.token", name="Token", category="Fixture")
def token(text: str = "hi") -> Token:
    """Wrap text in a Token.

    Args:
        text: The text.
    """
    return Token(text=text)


def register(registry: PackRegistry) -> None:
    import sys

    registry.add_module(sys.modules[__name__])
