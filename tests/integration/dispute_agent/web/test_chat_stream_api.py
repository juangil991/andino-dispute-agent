"""Tests de `POST /api/chat/stream` con la app real compuesta por `create_app`.

Spec 009: AC-009-01 y AC-009-08 (§7.1); regresión de AC-007-31 (§7.3).
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM, StreamScript, end_turn_response, tool_use_response
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.virtual_sleeper import VirtualSleeper

from dispute_agent.application.ports.banking_tools import (
    CardRef,
    CustomerMatch,
    CustomerSearch,
    EscalationRegistered,
    VerificationResult,
)
from dispute_agent.application.ports.llm import LLMError, LLMResponse, LLMStreamEnd, ToolCall
from dispute_agent.config import AgentSettings
from dispute_agent.domain import messages
from dispute_agent.domain.models.outcome import OutcomeKind
from dispute_agent.main import create_app

_NOW = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)


def _settings() -> AgentSettings:
    return AgentSettings(_env_file=None)  # type: ignore[call-arg]


def _client(
    llm: FakeLLM, sleeper: VirtualSleeper, banking: FakeBankingTools | None = None
) -> TestClient:
    app = create_app(
        _settings(),
        banking=banking if banking is not None else FakeBankingTools(),
        llm=llm,
        clock=FixedAgentClock(_NOW),
        sleeper=sleeper,
    )
    return TestClient(app)


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


def _llm(sleeper: VirtualSleeper, stream: list[StreamScript], verify: bool = False) -> FakeLLM:
    script: list[LLMResponse | LLMError] = [end_turn_response("decisión interna")]
    if verify:
        script.insert(0, _verify_in_turn())
    return FakeLLM(script, stream_script=stream, sleeper=sleeper)


def _verify_in_turn() -> LLMResponse:
    """Guion que deja verificada a la cliente en el propio turno (RN-007-39)."""
    return tool_use_response(
        ToolCall("v1", "buscar_cliente", {"document": "D-1001"}),
        ToolCall(
            "v2",
            "verificar_identidad",
            {"birth_date": "1990-01-01", "document_issue_date": "2010-01-01"},
        ),
    )


def _verified_banking() -> FakeBankingTools:
    return (
        FakeBankingTools()
        .respond(
            "search_customer",
            CustomerSearch((CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 4321"),)),), False),
        )
        .respond("verify_identity", VerificationResult(True, 3, False))
    )


# Regla: RN-009-01 — `POST /api/chat/stream` responde `200` con un flujo de eventos
# `start`, `word`* y `end` (§7.1) cuando la entrada es válida.
# AC-009-01 · Art. 5
def test_chat_stream__valid_input__emits_start_word_and_end_events() -> None:
    """AC-009-01: eventos start, word y end con los campos de §7.1."""
    sleeper = VirtualSleeper()
    llm = _llm(
        sleeper,
        [([(0.1, "Hola "), (0.1, "señora "), (0.1, "Pérez.")], LLMStreamEnd("end_turn"))],
        verify=True,
    )
    with _client(llm, sleeper, _verified_banking()) as client:
        response = client.post("/api/chat/stream", json={"message": "hola"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "start"
    assert names[-1] == "end"
    words = [data for name, data in events if name == "word"]
    assert words
    assert set(names[1:-1]) == {"word"}
    start, end = events[0][1], events[-1][1]
    assert set(start) == {"conversation_id"}
    assert set(end) == {"conversation_id", "reply", "status", "outcomes"}
    assert "".join(w["text"] for w in words) == end["reply"] == "Hola señora Pérez."
    assert end["status"] == "ACTIVE"
    assert end["outcomes"] == []
    assert start["conversation_id"] == end["conversation_id"]


# Regla: RN-009-10 — Si la redacción termina sin `end_turn`, el flujo cierra con
# `interrupted` (status ESCALATED, mensaje fijo de fallo del LLM) (§7.1).
# AC-009-09 · Art. 10
def test_chat_stream__draft_cut__emits_interrupted_event() -> None:
    """AC-009-09: el evento final es `interrupted` si la redacción se corta."""
    sleeper = VirtualSleeper()
    llm = _llm(sleeper, [([(0.1, "Hola ")], LLMStreamEnd("max_tokens"))], verify=True)
    banking = _verified_banking().respond(
        "escalate",
        EscalationRegistered(
            escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="OTHER"
        ),
    )
    with _client(llm, sleeper, banking) as client:
        response = client.post("/api/chat/stream", json={"message": "hola"})
    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[0][0] == "start"
    name, final = events[-1]
    assert name == "interrupted"
    assert final["status"] == "ESCALATED"
    assert final["reply"].startswith(messages.OUTCOME_REASONS[OutcomeKind.LLM_FAILURE])
    assert [n for n, _ in events].count("interrupted") == 1


# Regla: RN-009-01 — `422` y `404` son errores HTTP antes de transmitir, sin llamar al LLM.
# AC-009-08 · Art. 7
@pytest.mark.parametrize(
    ("body", "status"),
    [
        pytest.param({"message": "   "}, 422, id="blank-message"),
        pytest.param({"message": "x" * 2001}, 422, id="message-too-long"),
        pytest.param({"conversation_id": "no-existe", "message": "hola"}, 404, id="unknown-id"),
    ],
)
def test_chat_stream__invalid_input__fails_before_streaming(
    body: dict[str, str], status: int
) -> None:
    """AC-009-08: entrada inválida responde error HTTP, sin flujo y sin LLM."""
    sleeper = VirtualSleeper()
    llm = _llm(sleeper, [])
    with _client(llm, sleeper) as client:
        response = client.post("/api/chat/stream", json=body)
    assert response.status_code == status
    assert not response.headers["content-type"].startswith("text/event-stream")
    assert llm.requests == []
    assert llm.stream_requests == []


# Regla: RN-009-01 — `POST /api/chat` no cambia (contrato JSON de spec 007 §7.3).
# AC-007-31 · Art. 5
def test_chat_endpoint__unchanged_by_stream_endpoint__keeps_json_contract() -> None:
    """AC-007-31: `POST /api/chat` conserva su contrato JSON."""
    sleeper = VirtualSleeper()
    llm = _llm(sleeper, [], verify=True)
    with _client(llm, sleeper, _verified_banking()) as client:
        response = client.post("/api/chat", json={"message": "hola"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"conversation_id", "reply", "status", "outcomes"}
    assert body["reply"] == "decisión interna"
    assert body["status"] == "ACTIVE"
    assert body["outcomes"] == []
