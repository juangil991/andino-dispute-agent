"""Tests de la API de chat con identificación: respuesta fija y sin traslado entre conversaciones.

Spec 007: AC-007-55 y AC-007-57 (RN-007-38, RN-007-43, RN-009-04).
"""

import json
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM, StreamScript, end_turn_response, tool_use_response
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.virtual_sleeper import VirtualSleeper

from dispute_agent.application.ports.banking_tools import (
    CardRef,
    CustomerMatch,
    CustomerSearch,
    VerificationResult,
)
from dispute_agent.application.ports.llm import LLMResponse, ToolCall
from dispute_agent.config import AgentSettings
from dispute_agent.domain.messages import IDENTIFICATION_REPLIES, IdentificationReply
from dispute_agent.main import create_app

_NOW = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)
_LOCATE = IDENTIFICATION_REPLIES[IdentificationReply.REMINDER_LOCATE]


def _client(
    llm: FakeLLM, banking: FakeBankingTools, sleeper: VirtualSleeper | None = None
) -> TestClient:
    settings = AgentSettings(_env_file=None)  # type: ignore[call-arg]
    app = create_app(
        settings,
        banking=banking,
        llm=llm,
        clock=FixedAgentClock(_NOW),
        sleeper=sleeper or VirtualSleeper(),
    )
    return TestClient(app)


def _banking() -> FakeBankingTools:
    return (
        FakeBankingTools()
        .respond(
            "search_customer",
            CustomerSearch((CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 4321"),)),), False),
        )
        .respond("verify_identity", VerificationResult(True, 3, False))
    )


def _verify_in_turn() -> LLMResponse:
    return tool_use_response(
        ToolCall("v1", "buscar_cliente", {"document": "D-1001"}),
        ToolCall(
            "v2",
            "verificar_identidad",
            {"birth_date": "1990-01-01", "document_issue_date": "2010-01-01"},
        ),
    )


def _parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        name = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        events.append((name, json.loads(data)))
    return events


# Regla: RN-007-38 — Si al terminar el turno la cliente no está verificada, el `reply` no es el
# texto del LLM sino un texto fijo de §7.4 (en `POST /api/chat/stream` se envía completo en el
# evento `end`, sin eventos `word`).
# AC-007-57 · Art. 7
def test_ac_007_57_chat_stream_api__unverified_turn__start_and_end_without_words() -> None:
    """AC-007-57: el cuerpo SSE trae `start` y `end` sin `word`, con REMINDER_LOCATE."""
    sleeper = VirtualSleeper()
    stream: list[StreamScript] = []
    llm = FakeLLM(
        [end_turn_response("Claro, ya reviso eso por ti.")],
        stream_script=stream,
        sleeper=sleeper,
    )
    with _client(llm, FakeBankingTools(), sleeper) as client:
        response = client.post("/api/chat/stream", json={"message": "hola"})
    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [name for name, _ in events] == ["start", "end"]
    assert events[1][1]["reply"] == _LOCATE
    assert events[1][1]["status"] == "ACTIVE"
    assert llm.stream_requests == []


# Regla: RN-007-43 — la identificación vive en la conversación: una conversación nueva no la hereda.
# AC-007-55 · Art. 7
def test_ac_007_55_chat_api__new_conversation__does_not_inherit_identification() -> None:
    """AC-007-55: B nueva no hereda la verificación de A; A sigue verificada."""
    banking = _banking()
    llm = FakeLLM(
        [
            _verify_in_turn(),
            end_turn_response("Gracias, ya verifiqué tu identidad."),
            tool_use_response(ToolCall("c1", "consultar_transacciones", {"card_last4": "4321"})),
            end_turn_response("Claro, ya reviso eso por ti."),
            end_turn_response("Sigo aquí, texto del LLM."),
        ]
    )
    with _client(llm, banking) as client:
        first = client.post("/api/chat", json={"message": "mi documento es D-1001"})
        assert first.status_code == 200
        conv_a = first.json()["conversation_id"]
        assert first.json()["reply"] == "Gracias, ya verifiqué tu identidad."

        second = client.post("/api/chat", json={"message": "quiero ver mis movimientos"})
        assert second.status_code == 200
        body_b = second.json()
        assert body_b["conversation_id"] != conv_a
        assert body_b["reply"] == _LOCATE
        assert all(tool != "list_transactions" for tool, _ in banking.calls)

        third = client.post("/api/chat", json={"conversation_id": conv_a, "message": "hola"})
        assert third.status_code == 200
        assert third.json()["conversation_id"] == conv_a
        assert third.json()["reply"] == "Sigo aquí, texto del LLM."
