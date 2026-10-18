"""Adaptador del LLMPort sobre la Messages API de Anthropic."""

import httpx
from anthropic import AsyncAnthropic

from dispute_agent.application.ports.llm import (
    ChatMessage,
    LLMError,
    LLMResponse,
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
