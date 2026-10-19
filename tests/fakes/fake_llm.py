"""LLM falso con guion: devuelve respuestas en orden y registra las peticiones."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace

from dispute_agent.application.ports.llm import (
    ChatMessage,
    LLMError,
    LLMResponse,
    LLMStreamEnd,
    LLMTextDelta,
    ToolCall,
    ToolSpec,
)
from dispute_agent.application.ports.sleeper import Sleeper
from tests.fakes.virtual_sleeper import VirtualSleeper


@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolSpec, ...]


def tool_use_response(*calls: ToolCall, text: str = "") -> LLMResponse:
    return LLMResponse(text=text, tool_calls=tuple(calls), stop_reason="tool_use")


def end_turn_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, stop_reason="end_turn")


@dataclass(frozen=True)
class StreamRequest:
    system: str
    messages: tuple[ChatMessage, ...]


class _Hang:
    """Centinela: el stream entrega los trozos y luego no termina nunca."""


HANG = _Hang()

StreamScript = tuple[list[tuple[float, str]], LLMStreamEnd | LLMError | _Hang]


class FakeLLM:
    def __init__(
        self,
        script: list[LLMResponse | LLMError],
        infer_stop_reason: bool = True,
        stream_script: list[StreamScript] | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._script = list(script)
        self._infer_stop_reason = infer_stop_reason
        self._stream_script = list(stream_script or [])
        self._sleeper: Sleeper = sleeper if sleeper is not None else VirtualSleeper()
        self.requests: list[LLMRequest] = []
        self.stream_requests: list[StreamRequest] = []

    async def stream(
        self, system: str, messages: tuple[ChatMessage, ...]
    ) -> AsyncIterator[LLMTextDelta | LLMStreamEnd]:
        self.stream_requests.append(StreamRequest(system, tuple(messages)))
        if not self._stream_script:
            raise AssertionError("FakeLLM: guion de streaming agotado")
        chunks, end = self._stream_script.pop(0)
        for delay, text in chunks:
            await self._sleeper.sleep(delay)
            yield LLMTextDelta(text)
        if isinstance(end, LLMError):
            raise end
        if isinstance(end, _Hang):
            await asyncio.Event().wait()
        else:
            yield end

    async def complete(
        self,
        system: str,
        messages: tuple[ChatMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> LLMResponse:
        self.requests.append(LLMRequest(system, tuple(messages), tuple(tools)))
        if not self._script:
            raise AssertionError("FakeLLM: guion agotado")
        item = self._script.pop(0)
        if isinstance(item, LLMError):
            raise item
        if self._infer_stop_reason and item.stop_reason is None:
            return replace(item, stop_reason="tool_use" if item.tool_calls else "end_turn")
        return item
