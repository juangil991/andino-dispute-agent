"""E2E del streaming del agente: /api/chat/stream -> agente -> MCP stdio real (spec 009)."""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.fakes.fake_llm import FakeLLM, StreamScript, end_turn_response
from tests.fakes.fixed_agent_clock import FixedAgentClock

from core_banking_mcp.infrastructure.outbound.persistence.database import create_engine_from_url
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    DisputeRow,
    EscalationRow,
)
from core_banking_mcp.infrastructure.outbound.persistence.seeds.customers import SEED_CUSTOMERS
from core_banking_mcp.infrastructure.outbound.persistence.seeds.disputes import SEED_DISPUTES
from core_banking_mcp.infrastructure.outbound.persistence.seeds.transactions import (
    SEED_TRANSACTIONS,
)
from dispute_agent.application.ports.llm import ChatMessage, LLMStreamEnd
from dispute_agent.config import AgentSettings
from dispute_agent.main import create_app

_REPLY = "Para ayudarte necesito tu número de documento."
_CHUNKS = ["Para ", "ayudarte ", "necesito ", "tu ", "número ", "de ", "documento."]


def _seed_secrets() -> list[str]:
    """Datos ficticios de las semillas que nunca deben llegar a la redacción ni al flujo."""
    secrets: list[str] = ["****"]
    for customer, pans, _identity in SEED_CUSTOMERS:
        secrets += [customer.customer_id, customer.full_name, customer.document, *pans.values()]
        secrets += [card.last4 for card in customer.cards]
    for transaction in SEED_TRANSACTIONS:
        secrets += [transaction.transaction_id, transaction.card_id, transaction.merchant]
    return secrets


def _message_texts(message: ChatMessage) -> list[str]:
    texts = [message.text]
    for call in message.tool_calls:
        texts += [call.id, call.name, json.dumps(call.arguments, default=str)]
    for result in message.tool_results:
        texts += [result.tool_call_id, result.content]
    return texts


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


# Regla: RN-009-26 — La llamada de redacción no tiene herramientas y solo recibe el historial y
# los `outcomes` del turno; antes de verificar la identidad (Art. 7) las guardas de la spec 007
# impiden que ese historial contenga datos de la cuenta, por lo que lo transmitido no los incluye.
# AC-009-14 · Art. 7
def test_chat_stream__unverified_customer__has_no_account_data(tmp_path: Path) -> None:
    """AC-009-14: sin identidad verificada, redacción y flujo no contienen datos de cuenta."""
    url = f"sqlite:///{(tmp_path / 'core.db').as_posix()}"
    settings = AgentSettings(
        core_database_url=url,
        core_seed_on_start=True,
        mcp_call_timeout_seconds=20,
        _env_file=None,  # type: ignore[call-arg]
    )
    stream: list[StreamScript] = [([(0.0, chunk) for chunk in _CHUNKS], LLMStreamEnd("end_turn"))]
    llm = FakeLLM([end_turn_response(_REPLY)], stream_script=stream)
    with TestClient(create_app(settings, llm=llm, clock=FixedAgentClock())) as client:
        response = client.post("/api/chat/stream", json={"message": "No reconozco un cobro"})

    assert response.status_code == 200
    secrets = _seed_secrets()

    # (1) Entrada de la redacción: una sola llamada, sin datos de cuenta ni de las semillas.
    assert len(llm.stream_requests) == 1
    request = llm.stream_requests[0]
    inputs = [request.system]
    for message in request.messages:
        inputs += _message_texts(message)
    for text in inputs:
        assert not [s for s in secrets if s in text]
    assert not [t for t in inputs if "consultar_transacciones" in t and "TX-" in t]
    assert all(not m.tool_results for m in request.messages)

    # (2) Fragmentos transmitidos.
    events = _parse_sse(response.text)
    words = [data["text"] for name, data in events if name == "word"]
    assert "".join(words) == _REPLY
    for word in words:
        assert not [s for s in secrets if s in word]

    # (3) Cierre normal sin resultados.
    name, end = events[-1]
    assert name == "end"
    assert end["status"] == "ACTIVE"
    assert end["outcomes"] == []

    # (4) Ninguna herramienta de escritura se ejecutó en el servidor real.
    engine = create_engine_from_url(url)
    try:
        with Session(engine) as db:
            assert len(list(db.scalars(select(DisputeRow)))) == len(SEED_DISPUTES)
            assert list(db.scalars(select(EscalationRow))) == []
    finally:
        engine.dispose()
