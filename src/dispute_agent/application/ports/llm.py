"""Puerto del LLM: contrato mínimo y DTOs de mensajes y herramientas."""

from dataclasses import dataclass, field
from typing import Literal, Protocol


class LLMError(Exception):
    """Fallo del proveedor del LLM (red, cuota, respuesta inválida)."""


@dataclass(frozen=True)
class ToolSpec:
    """Descripción de una herramienta ofrecida al LLM."""

    name: str
    description: str
    input_schema: dict[str, object]


@dataclass(frozen=True)
class ToolCall:
    """Petición de uso de herramienta emitida por el LLM."""

    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ToolResult:
    """Resultado de una herramienta devuelto al LLM."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ChatMessage:
    """Mensaje de la conversación: texto, tool_use (assistant) o tool_result (user)."""

    role: Literal["user", "assistant"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = field(default=())
    tool_results: tuple[ToolResult, ...] = field(default=())


@dataclass(frozen=True)
class LLMResponse:
    """Respuesta del LLM: texto y/o llamadas a herramientas."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = field(default=())


class LLMPort(Protocol):
    async def complete(
        self,
        system: str,
        messages: tuple[ChatMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> LLMResponse: ...
