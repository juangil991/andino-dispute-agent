"""Guion de respuestas de POST /api/chat para las pruebas de navegador (spec 008).

Intercepta ``**/api/chat`` con ``page.route``: responde en orden con lo encolado, registra cada
petición y permite retener una respuesta hasta ``release()``.
"""

import json
import re
import threading
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Page, Request, Route


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    url: str
    json_body: Any


@dataclass(frozen=True)
class _Scripted:
    status: int
    body: Any
    delay_ms: int
    hold: bool
    abort: bool


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _words(reply: str) -> list[str]:
    """Trocea ``reply`` en palabras con su espacio previo; la unión es exactamente ``reply``."""
    tokens = re.findall(r"\s*\S+", reply)
    rest = reply[len("".join(tokens)) :]
    if rest:
        if tokens:
            tokens[-1] += rest
        else:
            tokens = [rest]
    return tokens


def _to_sse(body: Any) -> str:
    """Cuerpo SSE completo para un JSON válido; si no es válido, lo devuelve tal cual."""
    if isinstance(body, str):
        return body
    if not (
        isinstance(body, dict)
        and isinstance(body.get("reply"), str)
        and isinstance(body.get("status"), str)
    ):
        return json.dumps(body)
    conversation_id = body.get("conversation_id")
    parts = [_sse("start", {"conversation_id": conversation_id})]
    parts.extend(_sse("word", {"text": word}) for word in _words(body["reply"]))
    parts.append(
        _sse(
            "end",
            {
                "conversation_id": conversation_id,
                "reply": body["reply"],
                "status": body["status"],
                "outcomes": body.get("outcomes", []),
            },
        )
    )
    return "".join(parts)


class ChatApiScript:
    def __init__(self) -> None:
        self._queue: list[_Scripted] = []
        self._gate = threading.Event()
        self.requests: list[RecordedRequest] = []

    def enqueue(
        self,
        status: int = 200,
        body: Any = None,
        delay_ms: int = 0,
        hold: bool = False,
        abort: bool = False,
    ) -> "ChatApiScript":
        """Encola una respuesta; ``hold`` la retiene hasta ``release()``; ``abort`` corta la red."""
        self._queue.append(_Scripted(status, body, delay_ms, hold, abort))
        return self

    def release(self) -> None:
        """Libera la respuesta retenida."""
        self._gate.set()

    def install(self, page: Page) -> None:
        page.route("**/api/chat", self._handle)
        page.route("**/api/chat/stream", self._handle_stream)

    def _handle_stream(self, route: Route, request: Request) -> None:
        """Traduce la respuesta JSON guionizada a SSE (spec 009 §7.1) en un cuerpo completo."""
        self._handle(route, request, stream=True)

    def _handle(self, route: Route, request: Request, stream: bool = False) -> None:
        raw = request.post_data
        self.requests.append(
            RecordedRequest(
                method=request.method,
                url=request.url,
                json_body=json.loads(raw) if raw else None,
            )
        )
        if not self._queue:
            raise AssertionError("ChatApiScript: guion agotado")
        item = self._queue.pop(0)
        if item.hold:
            self._gate.wait(timeout=30)
        if item.delay_ms:
            threading.Event().wait(item.delay_ms / 1000)
        if item.abort:
            route.abort("failed")
            return
        if stream and item.status == 200:
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=_to_sse(item.body),
            )
            return
        route.fulfill(
            status=item.status,
            content_type="application/json",
            body=item.body if isinstance(item.body, str) else json.dumps(item.body),
        )
