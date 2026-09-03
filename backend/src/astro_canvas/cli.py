"""``astro-canvas`` command line interface."""

from __future__ import annotations

import threading
import time
import webbrowser
from pathlib import Path
from typing import Annotated

import httpx
import structlog
import typer
import uvicorn

from astro_canvas._version import __version__
from astro_canvas.logging import configure_logging
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings, get_settings

app = typer.Typer(
    name="astro-canvas",
    help="Node-based canvas for exploring astronomical data.",
    no_args_is_help=True,
    add_completion=False,
)

log = structlog.get_logger("astro_canvas.cli")


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


def open_when_ready(url: str, *, timeout: float = 30.0, interval: float = 0.2) -> bool:
    """Poll ``url/api/health`` until it answers, then open ``url`` in the browser.

    Returns:
        ``True`` if the browser was opened, ``False`` on timeout.
    """
    deadline = time.monotonic() + timeout
    health = f"{url}/api/health"
    while time.monotonic() < deadline:
        try:
            if httpx.get(health, timeout=1.0).status_code == 200:
                webbrowser.open(url)
                return True
        except httpx.HTTPError:
            pass
        time.sleep(interval)
    log.warning("server did not become ready; not opening browser", url=url)
    return False


def run_server(settings: Settings, *, open_browser: bool) -> None:
    """Start uvicorn with the app built from ``settings`` (blocking)."""
    url = f"http://{settings.host}:{settings.port}"
    log.info("starting", url=url, workspace=str(settings.workspace))
    if open_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address (default 127.0.0.1).")] = None,
    port: Annotated[int | None, typer.Option(help="Port (default 8765).")] = None,
    workspace: Annotated[
        Path | None, typer.Option(help="Workspace folder (default <Documents>/AstroCanvas).")
    ] = None,
    open_browser: Annotated[
        bool, typer.Option("--open", help="Open the browser once the server is up.")
    ] = False,
) -> None:
    """Run the Astro Canvas server."""
    settings = get_settings(host=host, port=port, workspace=workspace)
    configure_logging(settings.log_level)
    run_server(settings, open_browser=open_browser)


if __name__ == "__main__":  # pragma: no cover
    app()
