"""One place every router asks for the engine.

With a single user there is one ``EngineRuntime`` on ``app.state``. With ``--auth users`` there is
one per logged-in user, and the router-level dependency in ``server/users.py`` puts the caller's
on ``request.state`` before the endpoint runs -- so every handler keeps calling ``get_runtime`` and
none of them has to know which mode the server is in.
"""

from __future__ import annotations

from fastapi import Request

from astro_canvas.server.runtime import EngineRuntime


def get_runtime(request: Request) -> EngineRuntime:
    """The engine for this request: the caller's own in users mode, the server's otherwise."""
    scoped: EngineRuntime | None = getattr(request.state, "runtime", None)
    if scoped is not None:
        return scoped
    runtime: EngineRuntime = request.app.state.runtime
    return runtime


__all__ = ["get_runtime"]
