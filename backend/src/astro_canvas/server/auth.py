"""Bearer-token authentication for ``/api/*`` and ``/ws`` (design 6.5, 11).

The token comes from ``ASTRO_CANVAS_TOKEN`` or is generated at startup and written to
``<config>/token`` so the launcher can open ``http://host:port/?token=…``. ``/api/health``,
the OpenAPI document and the docs page stay public.
"""

from __future__ import annotations

import contextlib
import secrets
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import structlog

from astro_canvas.settings import Settings

log = structlog.get_logger("astro_canvas.server")

PUBLIC_PATHS = frozenset(
    {"/api/health", "/api/openapi.json", "/api/docs", "/api/docs/oauth2-redirect"}
)
Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def ensure_token(settings: Settings) -> str:
    """Return the configured token, generating and persisting one when needed."""
    token = settings.token or secrets.token_urlsafe(32)
    token_file = Path(settings.config_dir) / "token"
    try:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(token, encoding="utf-8")
        with contextlib.suppress(OSError):  # Windows ACLs
            token_file.chmod(0o600)
    except OSError as exc:  # pragma: no cover - unwritable config dir
        log.warning("could not write token file", path=str(token_file), error=str(exc))
    return token


def token_from_scope(scope: Scope) -> str | None:
    """``Authorization: Bearer <token>`` header or ``?token=`` query parameter."""
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            text = value.decode("latin-1")
            scheme, _, credential = text.partition(" ")
            if scheme.lower() == "bearer" and credential:
                return str(credential).strip()
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    values = query.get("token")
    return str(values[0]) if values else None


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or not (path.startswith("/api/") or path == "/ws")


class TokenAuthMiddleware:
    """Pure ASGI middleware rejecting unauthenticated ``/api`` HTTP requests with 401.

    WebSocket connections are checked by the endpoint itself (so it can close with a code).
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or is_public(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        supplied = token_from_scope(scope)
        if supplied is not None and secrets.compare_digest(supplied, self.token):
            await self.app(scope, receive, send)
            return
        body = b'{"detail":"missing or invalid token"}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def ws_authorized(scope: Scope, token: str | None) -> bool:
    """True when auth is disabled or the WebSocket handshake carries the right token."""
    if token is None:
        return True
    supplied = token_from_scope(scope)
    return supplied is not None and secrets.compare_digest(supplied, token)


def origin_allowed(scope: Scope) -> bool:
    """Reject cross-site WebSocket connections: the Origin host must match the Host header."""
    headers = dict(scope.get("headers", []))
    origin = headers.get(b"origin")
    if origin is None:
        return True
    host = headers.get(b"host", b"").decode("latin-1").split(":")[0]
    origin_host = origin.decode("latin-1").split("://", 1)[-1].split("/", 1)[0].split(":")[0]
    local = {"localhost", "127.0.0.1", "[::1]", "::1"}
    return origin_host == host or (origin_host in local and host in local)
