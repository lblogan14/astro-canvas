"""``astro-canvas serve`` and ``astro-canvas open``: run the server, or reuse a running one."""

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

from astro_canvas.logging import configure_logging
from astro_canvas.server.guard import ExposureError
from astro_canvas.settings import AuthMode, Settings, get_settings

log = structlog.get_logger("astro_canvas.cli")

READY_TIMEOUT_S = 30.0
PROBE_TIMEOUT_S = 1.0


def open_when_ready(url: str, *, timeout: float = READY_TIMEOUT_S, interval: float = 0.2) -> bool:
    """Poll ``url/api/health`` until it answers, then open ``url`` in the browser.

    Returns:
        ``True`` if the browser was opened, ``False`` on timeout.
    """
    deadline = time.monotonic() + timeout
    health = f"{url.split('?', 1)[0].rstrip('/')}/api/health"
    while time.monotonic() < deadline:
        try:
            if httpx.get(health, timeout=PROBE_TIMEOUT_S).status_code == 200:
                webbrowser.open(url)
                return True
        except httpx.HTTPError:
            pass
        time.sleep(interval)
    log.warning("server did not become ready; not opening browser", url=url)
    return False


def probe(url: str, *, timeout: float = PROBE_TIMEOUT_S) -> str | None:
    """The version a server at ``url`` reports, or ``None`` when nothing answers there."""
    try:
        response = httpx.get(f"{url.rstrip('/')}/api/health", timeout=timeout)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        return str(response.json().get("version", ""))
    except ValueError:  # pragma: no cover - /api/health always returns JSON
        return None


def entry_url(settings: Settings, token: str | None) -> str:
    """The URL to hand a browser: the bind address plus the token when there is one."""
    base = f"http://{settings.host}:{settings.port}"
    return f"{base}/?token={token}" if token else base


def run_server(settings: Settings, *, open_browser: bool) -> None:
    """Start uvicorn with the app built from ``settings`` (blocking)."""
    from astro_canvas.server.app import create_app  # noqa: PLC0415 - keeps --help fast

    log.info(
        "starting",
        url=f"http://{settings.host}:{settings.port}",
        workspace=str(settings.workspace),
    )
    app = create_app(settings)
    token = getattr(app.state, "token", None)
    url = entry_url(settings, token)
    if token:
        typer.echo(f"Open {url}")
    elif settings.user_auth:
        typer.echo(f"Astro Canvas is serving {url} with user accounts")
    if open_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips="*" if settings.public_url else "127.0.0.1",
    )


def serve(
    host: Annotated[str | None, typer.Option(help="Bind address (default 127.0.0.1).")] = None,
    port: Annotated[int | None, typer.Option(help="Port (default 8765).")] = None,
    workspace: Annotated[
        Path | None, typer.Option(help="Workspace folder (default <Documents>/AstroCanvas).")
    ] = None,
    open_browser: Annotated[
        bool, typer.Option("--open", help="Open the browser once the server is up.")
    ] = False,
    token: Annotated[
        str | None, typer.Option(help="Bearer token to require (default: generate one).")
    ] = None,
    auth: Annotated[
        AuthMode | None,
        typer.Option(
            help="none: no authentication. token: one shared bearer token. users: login accounts."
        ),
    ] = None,
    i_know_what_i_am_doing: Annotated[
        bool,
        typer.Option(
            "--i-know-what-i-am-doing",
            help="Allow a non-loopback bind address without user accounts.",
        ),
    ] = False,
) -> None:
    """Run the Astro Canvas server."""
    settings = get_settings(
        host=host,
        port=port,
        workspace=workspace,
        token=token,
        auth=auth,
        allow_public_bind=i_know_what_i_am_doing or None,
    )
    configure_logging(settings.log_level)
    try:
        run_server(settings, open_browser=open_browser)
    except ExposureError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None


def open_app_in_browser(
    port: Annotated[int | None, typer.Option(help="Port to look for and to serve on.")] = None,
    workspace: Annotated[Path | None, typer.Option(help="Workspace folder to open.")] = None,
    host: Annotated[str | None, typer.Option(help="Bind address (default 127.0.0.1).")] = None,
) -> None:
    """Open Astro Canvas: reuse the server that is already running, or start one.

    This is what the desktop shortcut runs. Clicking it twice must not start a second server on
    a port that is already taken, so it probes ``/api/health`` first and only then serves.
    """
    settings = get_settings(host=host, port=port, workspace=workspace)
    configure_logging(settings.log_level)
    base = f"http://{settings.host}:{settings.port}"
    version = probe(base)
    if version is not None:
        token = _saved_token(settings)
        url = entry_url(settings, token)
        typer.echo(f"Astro Canvas {version} is already running; opening {base}")
        webbrowser.open(url)
        return
    run_server(settings, open_browser=True)


def _saved_token(settings: Settings) -> str | None:
    """The token the running server wrote to the config folder, if it is still readable."""
    if settings.token:
        return settings.token
    try:
        return (Path(settings.config_dir) / "token").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


__all__ = ["entry_url", "open_app_in_browser", "open_when_ready", "probe", "run_server", "serve"]
