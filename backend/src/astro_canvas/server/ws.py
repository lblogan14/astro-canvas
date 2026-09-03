"""``WS /ws?token=…&client_id=…``: event stream plus ``subscribe`` / ``run`` / ``cancel`` /
``preview.request`` / ``output.request`` commands (design 6.4)."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from astro_canvas._version import __version__
from astro_canvas.engine.events import (
    GraphValidation,
    NodeOutputSummary,
    Subscription,
    output_frame,
)
from astro_canvas.server.auth import origin_allowed, ws_authorized
from astro_canvas.server.runtime import EngineRuntime, UnknownWorkflowError

log = structlog.get_logger("astro_canvas.ws")
router = APIRouter()

WS_UNAUTHORIZED = 4401
WS_FORBIDDEN_ORIGIN = 4403


class Subscribe(BaseModel):
    workflow_id: str


class RunCommand(BaseModel):
    targets: list[str] | None = None


class CancelCommand(BaseModel):
    run_id: str | None = None
    node_id: str | None = None


class PreviewRequest(BaseModel):
    node_id: str
    port: str
    viewport: dict[str, Any] = {}


class OutputRequest(BaseModel):
    node_id: str
    port: str


class WsSession:
    """One client connection: a subscription forwarder plus a command loop."""

    def __init__(self, websocket: WebSocket, runtime: EngineRuntime, client_id: str) -> None:
        self.ws = websocket
        self.runtime = runtime
        self.client_id = client_id
        self.workflow_id: str | None = None
        self._subscription: Subscription | None = None
        self._forwarder: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()

    async def send(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.ws.send_json(payload)

    async def send_bytes(self, data: bytes) -> None:
        async with self._send_lock:
            await self.ws.send_bytes(data)

    async def serve(self) -> None:
        await self.send(
            {
                "type": "hello",
                "client_id": self.client_id,
                "version": __version__,
                "ts": time.time(),
            }
        )
        while True:
            message = await self.ws.receive_json()
            await self.handle(message)

    async def handle(self, message: Any) -> None:
        if not isinstance(message, dict) or "type" not in message:
            await self.error("messages must be objects with a 'type'")
            return
        kind = str(message["type"])
        try:
            if kind == "subscribe":
                await self.subscribe(Subscribe.model_validate(message).workflow_id)
            elif kind == "run":
                await self.run(RunCommand.model_validate(message))
            elif kind == "cancel":
                await self.cancel(CancelCommand.model_validate(message))
            elif kind == "preview.request":
                await self.preview(PreviewRequest.model_validate(message))
            elif kind == "output.request":
                await self.output(OutputRequest.model_validate(message))
            elif kind == "ping":
                await self.send({"type": "pong", "ts": time.time()})
            else:
                await self.error(f"unknown message type {kind!r}")
        except ValidationError as exc:
            await self.error(f"invalid {kind} message: {exc.errors()[0].get('msg', exc)}")
        except UnknownWorkflowError as exc:
            await self.error(f"unknown workflow {exc}")

    async def error(self, message: str) -> None:
        await self.send({"type": "error", "message": message, "ts": time.time()})

    async def subscribe(self, workflow_id: str) -> None:
        scheduler = self.runtime.scheduler(workflow_id)
        await self.unsubscribe()
        self.workflow_id = workflow_id
        self._subscription = self.runtime.bus.subscribe(workflow_id)
        self._forwarder = asyncio.create_task(self._forward())
        await self.send(
            {
                "type": "subscribed",
                "workflow_id": workflow_id,
                "ts": time.time(),
                "current_run": scheduler.current_run.run_id if scheduler.current_run else None,
            }
        )
        validation = GraphValidation(workflow_id=workflow_id, node_errors=scheduler.issues)
        await self.send(validation.model_dump(mode="json"))
        for status in scheduler.snapshot().values():
            await self.send(status.model_dump(mode="json"))

    async def unsubscribe(self) -> None:
        if self._forwarder is not None:
            self._forwarder.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._forwarder
            self._forwarder = None
        if self._subscription is not None:
            self._subscription.close()
            self._subscription = None

    async def _forward(self) -> None:
        assert self._subscription is not None
        async for event in self._subscription:
            await self.send(event.model_dump(mode="json"))

    def _scheduler(self) -> Any:
        if self.workflow_id is None:
            raise UnknownWorkflowError("subscribe first")
        return self.runtime.scheduler(self.workflow_id)

    async def run(self, command: RunCommand) -> None:
        scheduler = self._scheduler()
        unknown = [t for t in command.targets or [] if t not in scheduler.graph.nodes]
        if unknown:
            await self.error(f"unknown or invalid target nodes {unknown}")
            return
        run_id = scheduler.start_run(command.targets)
        await self.send(
            {
                "type": "run.accepted",
                "run_id": run_id,
                "workflow_id": self.workflow_id,
                "ts": time.time(),
            }
        )

    async def cancel(self, command: CancelCommand) -> None:
        scheduler = self._scheduler()
        cancelled = scheduler.cancel(run_id=command.run_id, node_id=command.node_id)
        await self.send({"type": "cancel.result", "cancelled": cancelled, "ts": time.time()})

    async def preview(self, request: PreviewRequest) -> None:
        scheduler = self._scheduler()
        value = scheduler.output(request.node_id, request.port)
        if value is None:
            await self.error(f"no output for {request.node_id}.{request.port}")
            return
        summary = await asyncio.to_thread(value.summary, request.viewport)
        event = NodeOutputSummary(
            workflow_id=scheduler.workflow_id,
            node_id=request.node_id,
            port=request.port,
            type_id=value.type_id(),
            summary=summary,
        )
        await self.send(event.model_dump(mode="json"))

    async def output(self, request: OutputRequest) -> None:
        scheduler = self._scheduler()
        value = scheduler.output(request.node_id, request.port)
        if value is None:
            await self.error(f"no output for {request.node_id}.{request.port}")
            return
        frame = await asyncio.to_thread(output_frame, request.node_id, request.port, value)
        await self.send_bytes(frame)

    async def close(self) -> None:
        await self.unsubscribe()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Authenticated, same-origin event stream for one client."""
    settings = websocket.app.state.settings
    token = websocket.app.state.token if settings.auth else None
    if not ws_authorized(websocket.scope, token):
        await websocket.close(code=WS_UNAUTHORIZED, reason="missing or invalid token")
        return
    if not origin_allowed(websocket.scope):
        await websocket.close(code=WS_FORBIDDEN_ORIGIN, reason="origin not allowed")
        return
    await websocket.accept()
    runtime: EngineRuntime = websocket.app.state.runtime
    runtime.bus.bind(asyncio.get_running_loop())
    client_id = websocket.query_params.get("client_id") or uuid.uuid4().hex[:8]
    session = WsSession(websocket, runtime, client_id)
    try:
        await session.serve()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - log and drop the connection
        log.warning("websocket session failed", client_id=client_id, error=str(exc))
    finally:
        await session.close()
