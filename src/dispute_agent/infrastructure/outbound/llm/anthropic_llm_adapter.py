"""Adaptador del LLMPort sobre la Messages API de Anthropic."""

import json
from collections.abc import AsyncIterator

import httpx
from anthropic import AsyncAnthropic

from dispute_agent.application.ports.llm import (
    INTERNAL_DATA_CLOSE,
    INTERNAL_DATA_OPEN,
    ChatMessage,
    LLMError,
    LLMResponse,
    LLMStreamEnd,
    LLMTextDelta,
    ToolCall,
    ToolSpec,
)


def _serialize_message(message: ChatMessage) -> dict[str, object]:
    content: list[dict[str, object]] = []
    if message.text:
        content.append({"type": "text", "text": message.text})
    for call in message.tool_calls:
        content.append(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
        )
    for result in message.tool_results:
        block: dict[str, object] = {
            "type": "tool_result",
            "tool_use_id": result.tool_call_id,
            "content": result.content,
        }
        if result.is_error:
            block["is_error"] = True
        content.append(block)
    return {"role": message.role, "content": content}


def _flatten_for_drafting(messages: tuple[ChatMessage, ...]) -> list[dict[str, object]]:
    """Aplana el historial a texto: la API rechaza tool_use/tool_result sin `tools`.

    Fusiona mensajes consecutivos del mismo rol (alternancia exigida por la API).
    """
    calls: dict[str, ToolCall] = {}
    flattened: list[dict[str, object]] = []
    for message in messages:
        parts: list[str] = []
        if message.text:
            parts.append(message.text)
        for call in message.tool_calls:
            calls[call.id] = call
            arguments = json.dumps(call.arguments, ensure_ascii=False)
            parts.append(
                f"{INTERNAL_DATA_OPEN}Consulta realizada: {call.name} {arguments}"
                f"{INTERNAL_DATA_CLOSE}"
            )
        for result in message.tool_results:
            origin = calls.get(result.tool_call_id)
            name = origin.name if origin else "desconocida"
            args = json.dumps(origin.arguments if origin else {}, ensure_ascii=False)
            error = " (error)" if result.is_error else ""
            parts.append(
                f"{INTERNAL_DATA_OPEN}Resultado de {name} {args}{error}: "
                f"{result.content}{INTERNAL_DATA_CLOSE}"
            )
        if not parts:
            continue
        text = "\n".join(parts)
        if flattened and flattened[-1]["role"] == message.role:
            flattened[-1]["content"] = f"{flattened[-1]['content']}\n{text}"
        else:
            flattened.append({"role": message.role, "content": text})
    return flattened


class AnthropicLLMAdapter:
    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int = 1024,
        max_retries: int = 2,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client = AsyncAnthropic(
            api_key=api_key, max_retries=max_retries, http_client=http_client
        )

    async def complete(
        self,
        system: str,
        messages: tuple[ChatMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> LLMResponse:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[_serialize_message(m) for m in messages],  # type: ignore[misc]
                tools=[
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": t.input_schema,
                    }
                    for t in tools
                ],
            )
            texts: list[str] = []
            calls: list[ToolCall] = []
            for block in response.content:
                if block.type == "text":
                    texts.append(block.text)
                elif block.type == "tool_use":
                    arguments = block.input if isinstance(block.input, dict) else {}
                    calls.append(ToolCall(block.id, block.name, dict(arguments)))
            return LLMResponse("".join(texts), tuple(calls), response.stop_reason)
        except Exception as exc:
            raise LLMError(
                f"Falló la llamada al proveedor del LLM ({type(exc).__name__})."
            ) from None

    async def stream(
        self,
        system: str,
        messages: tuple[ChatMessage, ...],
    ) -> AsyncIterator[LLMTextDelta | LLMStreamEnd]:
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=_flatten_for_drafting(messages),  # type: ignore[arg-type]
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield LLMTextDelta(text)
                final = await stream.get_final_message()
            if final.stop_reason is None:
                raise ConnectionError("flujo cortado")  # SSE sin message_delta/message_stop
            calls: list[ToolCall] = []
            for block in final.content:
                if block.type == "tool_use":
                    arguments = block.input if isinstance(block.input, dict) else {}
                    calls.append(ToolCall(block.id, block.name, dict(arguments)))
            end = LLMStreamEnd(final.stop_reason, tuple(calls))
        except Exception as exc:
            raise LLMError(
                f"Falló la llamada al proveedor del LLM ({type(exc).__name__})."
            ) from None
        yield end
