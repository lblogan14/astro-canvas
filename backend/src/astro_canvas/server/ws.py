"""``WS /ws?token=…&client_id=…``: event stream plus ``subscribe`` / ``run`` / ``cancel`` /
``preview.request`` / ``output.request`` / ``preview.compute`` commands (design 6.4)."""

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
from astro_canvas.engine.batch import BatchSpec, spec_from_layout
from astro_canvas.engine.events import (
    GraphValidation,
    NodeOutputSummary,
    Subscription,
    output_frame,
)
from astro_canvas.engine.preview import compute_preview
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


class BatchCommand(BaseModel):
    """Start a batch over the subscribed workflow (``layouts.batch`` unless ``spec`` is given)."""

    rows: list[dict[str, Any]] = []
    spec: BatchSpec | None = None


class BatchCancelCommand(BaseModel):
    batch_id: str


class ComputeRequest(BaseModel):
    """Run a node body with candidate params (editor live preview); nothing is cached or emitted.

    Either ``node_id`` (inputs come from the graph's cached upstream outputs) or ``node_type``
    (a node without inputs, run on ``params`` alone). Replies are one tagged
    ``node.output.summary`` per output followed by ``preview.computed``.
    """

    node_id: str | None = None
    node_type: str | None = None
    params: dict[str, Any] = {}
    tag: str = "editor"
    viewport: dict[str, Any] = {}


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
            elif kind == "preview.compute":
                await self.compute(ComputeRequest.model_validate(message))
            elif kind == "batch.run":
                await self.batch(BatchCommand.model_validate(message))
            elif kind == "batch.cancel":
                await self.batch_cancel(BatchCancelCommand.model_validate(message))
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
                "auto_run": scheduler.auto_run,
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

    async def batch(self, command: BatchCommand) -> None:
        """Start a batch; ``batch.started``/``batch.row``/``batch.finished`` follow on the bus."""
        self._scheduler()  # the workflow must be subscribed
        assert self.workflow_id is not None
        doc = self.runtime.get(self.workflow_id)
        spec = command.spec or spec_from_layout(doc.layouts.get("batch") or {})
        if not command.rows or not spec.collect:
            await self.error("a batch needs rows and at least one collected output")
            return
        try:
            run = self.runtime.batches.start(doc, command.rows, spec)
        except ValueError as exc:
            await self.error(str(exc))
            return
        await self.send(
            {
                "type": "batch.accepted",
                "batch_id": run.batch_id,
                "workflow_id": self.workflow_id,
                "n_rows": run.n_rows,
                "ts": time.time(),
            }
        )

    async def batch_cancel(self, command: BatchCancelCommand) -> None:
        cancelled = self.runtime.batches.cancel(command.batch_id)
        await self.send(
            {
                "type": "batch.cancelled",
                "batch_id": command.batch_id,
                "cancelled": cancelled,
                "ts": time.time(),
            }
        )

    async def preview(self, request: PreviewRequest) -> None:
        scheduler = self._scheduler()
        value = scheduler.output(request.node_id, request.port)
        if value is None:
            await self.error(f"no output for {request.node_id}.{request.port}")
            return
        viewport = dict(request.viewport)
        raw_tag = viewport.pop("tag", None)
        tag = str(raw_tag) if raw_tag is not None else None
        try:
            summary = await asyncio.to_thread(value.summary, viewport)
        except Exception as exc:  # noqa: BLE001 - a bad viewport must not drop the socket
            await self.error(f"preview failed for {request.node_id}.{request.port}: {exc}")
            return
        event = NodeOutputSummary(
            workflow_id=scheduler.workflow_id,
            node_id=request.node_id,
            port=request.port,
            type_id=value.type_id(),
            summary=summary,
            tag=tag,
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

    async def compute(self, request: ComputeRequest) -> None:
        scheduler = self._scheduler()
        started = time.perf_counter()
        label = request.node_id or request.node_type or "?"
        try:
            type_id, outputs = await asyncio.to_thread(
                compute_preview,
                scheduler,
                self.runtime.registry,
                node_id=request.node_id,
                node_type=request.node_type,
                params=request.params,
            )
            summaries = {
                port: await asyncio.to_thread(value.summary, dict(request.viewport))
                for port, value in outputs.items()
            }
        except Exception as exc:  # noqa: BLE001 - reported to the client, never fatal
            await self.send(
                {
                    "type": "preview.computed",
                    "workflow_id": self.workflow_id,
                    "node_id": request.node_id,
                    "node_type": request.node_type,
                    "tag": request.tag,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_ms": (time.perf_counter() - started) * 1000.0,
                    "ts": time.time(),
                }
            )
            log.info("preview.compute failed", node=label, error=str(exc))
            return
        for port, value in outputs.items():
            event = NodeOutputSummary(
                workflow_id=scheduler.workflow_id,
                node_id=request.node_id or f"type:{type_id}",
                port=port,
                type_id=value.type_id(),
                summary=summaries[port],
                tag=request.tag,
            )
            await self.send(event.model_dump(mode="json"))
        await self.send(
            {
                "type": "preview.computed",
                "workflow_id": self.workflow_id,
                "node_id": request.node_id,
                "node_type": request.node_type,
                "tag": request.tag,
                "ok": True,
                "ports": list(outputs),
                "elapsed_ms": (time.perf_counter() - started) * 1000.0,
                "ts": time.time(),
            }
        )

    async def close(self) -> None:
        await self.unsubscribe()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Authenticated, same-origin event stream for one client."""
    settings = websocket.app.state.settings
    users = getattr(websocket.app.state, "users", None)
    user = None
    if users is not None:
        user = await users.authenticate_ws(websocket)
        if user is None:
            await websocket.close(code=WS_UNAUTHORIZED, reason="please log in")
            return
    else:
        token = websocket.app.state.token if settings.token_auth else None
        if not ws_authorized(websocket.scope, token):
            await websocket.close(code=WS_UNAUTHORIZED, reason="missing or invalid token")
            return
    if not origin_allowed(websocket.scope):
        await websocket.close(code=WS_FORBIDDEN_ORIGIN, reason="origin not allowed")
        return
    await websocket.accept()
    runtime: EngineRuntime = (
        await users.pool.get(user) if users is not None else websocket.app.state.runtime
    )
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
