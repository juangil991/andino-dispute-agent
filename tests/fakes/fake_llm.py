"""LLM falso con guion: devuelve respuestas en orden y registra las peticiones."""

from dataclasses import dataclass, replace

from dispute_agent.application.ports.llm import (
    ChatMessage,
    LLMError,
    LLMResponse,
    ToolCall,
    ToolSpec,
)


@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolSpec, ...]


def tool_use_response(*calls: ToolCall, text: str = "") -> LLMResponse:
    return LLMResponse(text=text, tool_calls=tuple(calls), stop_reason="tool_use")


def end_turn_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, stop_reason="end_turn")


class FakeLLM:
    def __init__(
        self, script: list[LLMResponse | LLMError], infer_stop_reason: bool = True
    ) -> None:
        self._script = list(script)
        self._infer_stop_reason = infer_stop_reason
        self.requests: list[LLMRequest] = []

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
