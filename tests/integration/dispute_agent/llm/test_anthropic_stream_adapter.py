"""Integración de AnthropicLLMAdapter.stream con httpx.MockTransport (SSE, sin red real)."""

import json

import httpx
import pytest

from dispute_agent.application.ports.llm import (
    ChatMessage,
    LLMError,
    LLMStreamEnd,
    LLMTextDelta,
    ToolCall,
    ToolResult,
)
from dispute_agent.infrastructure.outbound.llm.anthropic_llm_adapter import (
    AnthropicLLMAdapter,
)

_MODEL = "claude-test-model"


def _adapter(transport: httpx.MockTransport) -> AnthropicLLMAdapter:
    return AnthropicLLMAdapter(
        api_key="sk-ant-ficticia",
        model=_MODEL,
        max_retries=0,
        http_client=httpx.AsyncClient(transport=transport),
    )


def _sse(events: list[tuple[str, dict[str, object]]]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def _message_start() -> tuple[str, dict[str, object]]:
    return (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": _MODEL,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        },
    )


def _text_block(index: int, chunks: list[str]) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = [
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "text", "text": ""},
            },
        )
    ]
    for chunk in chunks:
        events.append(
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "text_delta", "text": chunk},
                },
            )
        )
    events.append(("content_block_stop", {"type": "content_block_stop", "index": index}))
    return events


def _tool_block(index: int) -> list[tuple[str, dict[str, object]]]:
    return [
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_9",
                    "name": "buscar_cliente",
                    "input": {},
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "input_json_delta", "partial_json": '{"document": "9"}'},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": index}),
    ]


def _message_end(stop_reason: str) -> list[tuple[str, dict[str, object]]]:
    return [
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]


def _sse_response(body: bytes) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


# Regla: RN-009-03 — La redacción es una llamada al LLM sin herramientas, con el historial
# del turno, que se transmite en tiempo real; su razón de parada decide si es completa.
# AC-009-01 · Art. 5 (el dominio decide; el LLM solo redacta)
# AC-009-31 · Art. 5 (historial aplanado en bloques `<datos_internos>`, sin `[herramienta`)
async def test_stream__flattened_history_without_tools__yields_deltas_and_stop_reason() -> None:
    """AC-009-01: sin tools, historial aplanado a texto, deltas y LLMStreamEnd con stop_reason."""
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        events = [
            _message_start(),
            *_text_block(0, ["Tu ", "disputa ", "quedó abierta."]),
            *_tool_block(1),
            *_message_end("tool_use"),
        ]
        return _sse_response(_sse(events))

    history = (
        ChatMessage("user", "hola"),
        ChatMessage(
            "assistant",
            "Busco.",
            tool_calls=(ToolCall("toolu_1", "buscar_cliente", {"document": "123"}),),
        ),
        ChatMessage("user", tool_results=(ToolResult("toolu_1", '{"ok": true}'),)),
    )
    items = [i async for i in _adapter(httpx.MockTransport(handler)).stream("sys", history)]

    body = captured[0]
    assert "tools" not in body
    assert "tool_choice" not in body
    assert body["stream"] is True
    assert body["system"] == "sys"
    messages = body["messages"]
    assert isinstance(messages, list)
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert "tool_use" not in json.dumps(messages)
    assert "tool_result" not in json.dumps(messages)
    assert messages[1]["content"] == (
        'Busco.\n<datos_internos>Consulta realizada: buscar_cliente {"document": "123"}'
        "</datos_internos>"
    )
    assert messages[2]["content"] == (
        '<datos_internos>Resultado de buscar_cliente {"document": "123"}: {"ok": true}'
        "</datos_internos>"
    )
    assert "[herramienta" not in json.dumps(messages)
    assert "[resultado" not in json.dumps(messages)
    assert items == [
        LLMTextDelta("Tu "),
        LLMTextDelta("disputa "),
        LLMTextDelta("quedó abierta."),
        LLMStreamEnd("tool_use", (ToolCall("toolu_9", "buscar_cliente", {"document": "9"}),)),
    ]


# Regla: RN-009-03 — La redacción se envía al LLM respetando la alternancia de roles de la
# API y terminando en un mensaje del usuario (caso límite: mensajes consecutivos del mismo rol).
# AC-009-01 · Art. 5
async def test_stream__consecutive_same_role__merged_and_ends_with_user() -> None:
    """AC-009-01: mensajes consecutivos del mismo rol se fusionan."""
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _sse_response(
            _sse([_message_start(), *_text_block(0, ["ok"]), *_message_end("end_turn")])
        )

    history = (
        ChatMessage("user", "hola"),
        ChatMessage("user", "tengo un cobro raro"),
        ChatMessage("assistant", "Dime más."),
        ChatMessage("user", "es de ayer"),
    )
    items = [i async for i in _adapter(httpx.MockTransport(handler)).stream("sys", history)]

    messages = captured[0]["messages"]
    assert isinstance(messages, list)
    assert messages == [
        {"role": "user", "content": "hola\ntengo un cobro raro"},
        {"role": "assistant", "content": "Dime más."},
        {"role": "user", "content": "es de ayer"},
    ]
    assert items[-1] == LLMStreamEnd("end_turn")


# Regla: RN-009-09 — Si la redacción se interrumpe por un error del LLM, la cliente no recibe
# detalles del proveedor.
# AC-009-09 · Art. 10 (ante la duda, escalar)
async def test_stream__http_error__raises_llm_error_without_details() -> None:
    """AC-009-09: un error HTTP del proveedor se traduce en LLMError sin detalles."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, json={"error": "sk-ant-ficticia"})
    )
    with pytest.raises(LLMError) as exc:
        _ = [i async for i in _adapter(transport).stream("sys", (ChatMessage("user", "hola"),))]
    assert "sk-ant-ficticia" not in str(exc.value)
    assert str(exc.value).startswith("Falló la llamada al proveedor del LLM (")


# Regla: RN-009-09 — Un corte del flujo de la redacción es una interrupción: se informa como
# fallo del LLM, sin texto parcial ni detalles internos.
# AC-009-09 · Art. 10 (ante la duda, escalar)
async def test_stream__sse_cut_before_message_stop__raises_llm_error() -> None:
    """AC-009-09: un SSE cortado antes de message_stop se traduce en LLMError."""
    body = _sse([_message_start(), *_text_block(0, ["Tu "])])
    transport = httpx.MockTransport(lambda request: _sse_response(body))
    seen: list[object] = []
    with pytest.raises(LLMError):
        async for item in _adapter(transport).stream("sys", (ChatMessage("user", "hola"),)):
            seen.append(item)
    assert seen == [LLMTextDelta("Tu ")]
