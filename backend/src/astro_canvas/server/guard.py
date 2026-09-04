"""Refuse to serve a public interface without user accounts (design 11).

The desktop tier binds loopback and guards ``/api`` with one bearer token that the launcher
puts in the URL. That token is fine for a single user on their own machine and wrong for a
network: it is shared by everyone who has it, and the pack manager installs into the *server's*
environment, so anyone who can reach ``/api/manager`` changes what every other user runs.

``--host 0.0.0.0`` therefore needs either ``--auth users`` or an explicit
``--i-know-what-i-am-doing``, and the check lives here rather than in the CLI so that
``uvicorn --factory astro_canvas.server.app:create_app`` and the Docker image are guarded too.
"""

from __future__ import annotations

from astro_canvas.settings import Settings

OVERRIDE_FLAG = "--i-know-what-i-am-doing"
OVERRIDE_ENV = "ASTRO_CANVAS_ALLOW_PUBLIC_BIND=1"


class ExposureError(RuntimeError):
    """The requested bind address would expose the server to more than this machine."""


def exposure_problem(settings: Settings) -> str | None:
    """Why ``settings`` must not be served, or ``None`` when it is safe.

    Args:
        settings: The configuration ``serve`` is about to start.

    Returns:
        A message naming the fix, or ``None``.
    """
    if settings.is_loopback or settings.user_auth or settings.allow_public_bind:
        return None
    if settings.auth == "none":
        return (
            f"refusing to serve {settings.host}:{settings.port} with --auth none: every visitor "
            "would have full access to your files. Use --auth users for a shared server, or "
            f"pass {OVERRIDE_FLAG} (env {OVERRIDE_ENV}) if this port really is private."
        )
    return (
        f"refusing to serve {settings.host}:{settings.port} with --auth token: the one token is "
        "shared by everyone who reaches it, and the pack manager installs into this server's own "
        "environment. Use --auth users for a shared server, keep --host 127.0.0.1 for yourself, "
        f"or pass {OVERRIDE_FLAG} (env {OVERRIDE_ENV}) if this port really is private."
    )


def check_exposure(settings: Settings) -> None:
    """Raise ``ExposureError`` when ``settings`` would expose the server unsafely."""
    problem = exposure_problem(settings)
    if problem is not None:
        raise ExposureError(problem)


__all__ = ["OVERRIDE_ENV", "OVERRIDE_FLAG", "ExposureError", "check_exposure", "exposure_problem"]
