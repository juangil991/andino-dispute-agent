"""Guion progresivo de POST /api/chat/stream para las pruebas de navegador (spec 009).

App ASGI que envuelve la app real: responde ``POST /api/chat/stream`` con los eventos SSE que
cada prueba encola, emitidos de forma progresiva desde el servidor (demoras, puertas
``hold``/``release``, cierre abrupto, evento no JSON, código de error). El resto de rutas va a la
app real. El estado está protegido para usarse desde el hilo del servidor y el de la prueba.
"""

import asyncio
import json
import threading
from dataclasses import dataclass
from typing import Any

from tests.fakes.chat_api_script import RecordedRequest

Scope = dict[str, Any]


@dataclass(frozen=True)
class _Event:
    name: str
    data: str
    delay_ms: int


@dataclass(frozen=True)
class _Hold:
    gate: str


@dataclass(frozen=True)
class _Close:
    pass


@dataclass(frozen=True)
class _Error:
    status: int
    body: Any


_Step = _Event | _Hold | _Close | _Error


class ChatStreamScript:
    def __init__(self, app: Any) -> None:
        self._app = app
        self._lock = threading.Lock()
        self._queue: list[list[_Step]] = []
        self._gates: dict[str, threading.Event] = {}
        self._requests: list[RecordedRequest] = []

    # ---- API para las pruebas (hilo de la prueba) ----

    def reset(self) -> None:
        """Limpia cola, puertas y peticiones registradas (una vez por prueba)."""
        with self._lock:
            self._queue.clear()
            for gate in self._gates.values():
                gate.set()
            self._gates.clear()
            self._requests.clear()

    @property
    def requests(self) -> list[RecordedRequest]:
        with self._lock:
            return list(self._requests)

    def enqueue_stream(self) -> "StreamBuilder":
        """Empieza a guionizar el flujo de la siguiente petición."""
        steps: list[_Step] = []
        with self._lock:
            self._queue.append(steps)
        return StreamBuilder(self, steps)

    def enqueue_error(self, status: int, body: Any = None) -> "ChatStreamScript":
        """La siguiente petición recibe este código HTTP antes de transmitir."""
        with self._lock:
            self._queue.append([_Error(status, body if body is not None else {"detail": "error"})])
        return self

    def release(self, gate: str = "default") -> None:
        """Libera la puerta ``gate`` (también si se llama antes de que el flujo llegue a ella)."""
        self._gate(gate).set()

    # ---- internos ----

    def _gate(self, name: str) -> threading.Event:
        with self._lock:
            return self._gates.setdefault(name, threading.Event())

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"] == "/api/chat/stream"
        ):
            await self._serve(scope, receive, send)
            return
        await self._app(scope, receive, send)

    async def _serve(self, scope: Scope, receive: Any, send: Any) -> None:
        raw = b""
        more = True
        while more:
            message = await receive()
            raw += message.get("body", b"")
            more = message.get("more_body", False)
        host, port = scope.get("server") or ("127.0.0.1", 0)
        with self._lock:
            self._requests.append(
                RecordedRequest(
                    method=scope["method"],
                    url=f"http://{host}:{port}{scope['path']}",
                    json_body=json.loads(raw) if raw else None,
                )
            )
            steps = self._queue.pop(0) if self._queue else None
        if steps is None:
            steps = [_Error(500, {"detail": "ChatStreamScript: guion agotado"})]
        if steps and isinstance(steps[0], _Error):
            error = steps[0]
            payload = error.body if isinstance(error.body, str) else json.dumps(error.body)
            await self._respond(send, error.status, "application/json", payload.encode())
            return
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/event-stream"),
                    (b"cache-control", b"no-cache"),
                ],
            }
        )
        for step in steps:
            if isinstance(step, _Hold):
                gate = self._gate(step.gate)
                while not gate.is_set():
                    await asyncio.sleep(0.005)
            elif isinstance(step, _Close):
                break
            elif isinstance(step, _Event):
                if step.delay_ms:
                    await asyncio.sleep(step.delay_ms / 1000)
                chunk = f"event: {step.name}\ndata: {step.data}\n\n".encode()
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    @staticmethod
    async def _respond(send: Any, status: int, content_type: str, body: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", content_type.encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})


class StreamBuilder:
    """Guion fluido del flujo de una petición."""

    def __init__(self, script: ChatStreamScript, steps: list[_Step]) -> None:
        self._script = script
        self._steps = steps

    def event(self, name: str, data: Any, delay_ms: int = 0) -> "StreamBuilder":
        """Evento SSE con ``data`` serializado a JSON."""
        self._steps.append(_Event(name, json.dumps(data, ensure_ascii=False), delay_ms))
        return self

    def raw_event(self, name: str, data: str, delay_ms: int = 0) -> "StreamBuilder":
        """Evento SSE con ``data`` literal (p. ej. no JSON)."""
        self._steps.append(_Event(name, data, delay_ms))
        return self

    def hold(self, gate: str = "default") -> "StreamBuilder":
        """Nada más sale hasta ``script.release(gate)``."""
        self._steps.append(_Hold(gate))
        return self

    def close(self) -> "StreamBuilder":
        """Cierra el flujo en este punto, sin evento final."""
        self._steps.append(_Close())
        return self
