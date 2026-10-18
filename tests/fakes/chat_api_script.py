"""Guion de respuestas de POST /api/chat para las pruebas de navegador (spec 008).

Intercepta ``**/api/chat`` con ``page.route``: responde en orden con lo encolado, registra cada
petición y permite retener una respuesta hasta ``release()``.
"""

import json
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

    def _handle(self, route: Route, request: Request) -> None:
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
        route.fulfill(
            status=item.status,
            content_type="application/json",
            body=item.body if isinstance(item.body, str) else json.dumps(item.body),
        )
