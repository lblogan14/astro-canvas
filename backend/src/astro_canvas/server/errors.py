"""Turn every unhandled exception into an answer the UI can show.

FastAPI's default for an unhandled exception is a 500 with the body ``Internal Server Error``,
which reaches the SPA as a toast saying nothing. Phase 13's error-UX audit asks for the opposite:
the exception's own message, the same one-line `hint` a failing node gets, and a `request_id` the
server logged the traceback under, so a support email can be matched to a log line.

`ValidationError` from pydantic is separated out because it is nearly always a *stored document*
that no longer validates, not a bug: it answers 422.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from astro_canvas.engine.hints import hint_for

log = structlog.get_logger("astro_canvas.server")


class ErrorBody(BaseModel):
    """The shape of every error the server generates itself (`ApiError` in the SPA)."""

    detail: str = Field(description="What went wrong, in the exception's own words.")
    hint: str | None = Field(default=None, description="What the user can do about it.")
    request_id: str | None = Field(
        default=None, description="Correlates with the traceback in the server log."
    )


def _body(exc: BaseException, request_id: str | None = None) -> dict[str, Any]:
    return ErrorBody(
        detail=f"{type(exc).__name__}: {exc}",
        hint=hint_for(exc),
        request_id=request_id,
    ).model_dump()


def install_error_handlers(app: FastAPI) -> None:
    """Attach the unhandled-exception and validation handlers to ``app``."""

    @app.exception_handler(ValidationError)
    async def on_validation_error(request: Request, exc: Exception) -> JSONResponse:
        log.warning("validation_error", path=request.url.path, error=str(exc))
        return JSONResponse(status_code=422, content=_body(exc))

    @app.exception_handler(Exception)
    async def on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = uuid.uuid4().hex[:12]
        log.exception("unhandled_error", path=request.url.path, request_id=request_id)
        return JSONResponse(status_code=500, content=_body(exc, request_id))
