"""Integración del AnthropicLLMAdapter con httpx.MockTransport (sin red real)."""

import json

import httpx
import pytest

from dispute_agent.application.ports.llm import (
    ChatMessage,
    LLMError,
    LLMResponse,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from dispute_agent.infrastructure.outbound.llm.anthropic_llm_adapter import (
    AnthropicLLMAdapter,
)

_MODEL = "claude-test-model"
_TOOLS = (
    ToolSpec(
        name="buscar_cliente",
        description="Busca al cliente.",
        input_schema={"type": "object", "properties": {}},
    ),
)


def _adapter(handler: httpx.MockTransport) -> AnthropicLLMAdapter:
    return AnthropicLLMAdapter(
        api_key="sk-ant-ficticia",
        model=_MODEL,
        max_retries=0,
        http_client=httpx.AsyncClient(transport=handler),
    )


def _ok_body(content: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": _MODEL,
        "content": content,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


# Regla: RN-007-23 — El loop admite como máximo **8** llamadas al LLM por cada mensaje del
# cliente (configurable). Al superarlo, o si el LLM falla o devuelve una salida inválida, el
# agente no ejecuta ninguna acción pendiente de ese turno. Deriva con `INCONCLUSIVE_RULES` si
# se superó el límite, o con `UNRECOVERABLE_SYSTEM_FAILURE` si falló el LLM, informa al
# cliente con un mensaje fijo y cierra la conversación.
# AC-007-25 · Art. 10 (ante la duda, escalar)
async def test_ac_007_25_anthropic_adapter__server_error__raises_llm_error() -> None:
    """AC-007-25: un error 500 del proveedor se traduce en LLMError."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, json={"error": "sk-ant-ficticia"})
    )
    with pytest.raises(LLMError) as exc:
        await _adapter(transport).complete("sys", (ChatMessage("user", "hola"),), _TOOLS)
    assert "sk-ant-ficticia" not in str(exc.value)


# Regla: RN-007-34 — Una razón de parada distinta de `tool_use` y `end_turn` es una salida
# inválida.
# AC-007-40 · Art. 10 (ante la duda, escalar)
@pytest.mark.parametrize(
    "stop_reason",
    ["tool_use", "end_turn", "max_tokens", "refusal", "pause_turn"],
)
async def test_ac_007_40_anthropic_adapter__stop_reason__passed_through(
    stop_reason: str,
) -> None:
    """AC-007-40: LLMResponse.stop_reason copia el stop_reason de la Messages API."""
    body = _ok_body([{"type": "text", "text": "ok"}])
    body["stop_reason"] = stop_reason
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    response = await _adapter(transport).complete("sys", (ChatMessage("user", "hola"),), _TOOLS)
    assert response.stop_reason == stop_reason


# Soporte de tests: traducción de respuesta y petición · Art. 3
async def test_support_anthropic_adapter__text_and_tool_use__maps_to_llm_response() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=_ok_body(
                [
                    {"type": "text", "text": "Voy a buscarte."},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "buscar_cliente",
                        "input": {"document": "123"},
                    },
                ]
            ),
        )
    )
    response = await _adapter(transport).complete("sys", (ChatMessage("user", "hola"),), _TOOLS)
    assert response == LLMResponse(
        "Voy a buscarte.",
        (ToolCall("toolu_1", "buscar_cliente", {"document": "123"}),),
        "end_turn",
    )


async def test_support_anthropic_adapter__history__serialized_as_messages_api() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=_ok_body([{"type": "text", "text": "ok"}]))

    history = (
        ChatMessage("user", "hola"),
        ChatMessage(
            "assistant",
            "Busco.",
            tool_calls=(ToolCall("toolu_1", "buscar_cliente", {"document": "123"}),),
        ),
        ChatMessage(
            "user",
            tool_results=(ToolResult("toolu_1", '{"ok": true}'), ToolResult("toolu_2", "x", True)),
        ),
    )
    await _adapter(httpx.MockTransport(handler)).complete("sys", history, _TOOLS)
    body = captured[0]
    assert body["model"] == _MODEL
    assert body["system"] == "sys"
    assert body["tools"] == [
        {
            "name": "buscar_cliente",
            "description": "Busca al cliente.",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    assert body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hola"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Busco."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "buscar_cliente",
                    "input": {"document": "123"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"ok": true}'},
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_2",
                    "content": "x",
                    "is_error": True,
                },
            ],
        },
    ]


async def test_support_anthropic_adapter__network_error__raises_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red sk-ant-ficticia")

    with pytest.raises(LLMError) as exc:
        await _adapter(httpx.MockTransport(handler)).complete(
            "sys", (ChatMessage("user", "hola"),), _TOOLS
        )
    assert "sk-ant-ficticia" not in str(exc.value)
