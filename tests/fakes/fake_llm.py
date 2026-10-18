"""LLM falso con guion: devuelve respuestas en orden y registra las peticiones."""

from dataclasses import dataclass

from dispute_agent.application.ports.llm import ChatMessage, LLMError, LLMResponse, ToolSpec


@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolSpec, ...]


class FakeLLM:
    def __init__(self, script: list[LLMResponse | LLMError]) -> None:
        self._script = list(script)
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
        return item
