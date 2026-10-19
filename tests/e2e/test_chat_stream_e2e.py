"""E2E del streaming del agente: /api/chat/stream -> agente -> MCP stdio real (spec 009)."""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.fakes.fake_llm import FakeLLM, end_turn_response
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
from dispute_agent.config import AgentSettings
from dispute_agent.main import create_app

_REPLY = "Para ayudarte necesito tu número de documento."
_REMINDER_LOCATE = (
    "Antes de ayudarte necesito identificarte. Indícame tu número de documento, "
    "tu nombre completo o los últimos 4 dígitos de tu tarjeta."
)


def _seed_secrets() -> list[str]:
    """Datos ficticios de las semillas que nunca deben llegar a la redacción ni al flujo."""
    secrets: list[str] = ["****"]
    for customer, pans, _identity in SEED_CUSTOMERS:
        secrets += [customer.customer_id, customer.full_name, customer.document, *pans.values()]
        secrets += [card.last4 for card in customer.cards]
    for transaction in SEED_TRANSACTIONS:
        secrets += [transaction.transaction_id, transaction.card_id, transaction.merchant]
    return secrets


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


# Regla: RN-009-26 y RN-007-38 — antes de verificar la identidad (Art. 7) el `reply` es un texto
# fijo que se envía completo en `end`, sin llamada de redacción y sin datos de la cuenta.
# AC-009-14 (spec 009 0.2.0) · Art. 7
def test_chat_stream__unverified_customer__has_no_account_data(tmp_path: Path) -> None:
    """AC-009-14: sin identidad verificada el flujo es start y end con REMINDER_LOCATE."""
    url = f"sqlite:///{(tmp_path / 'core.db').as_posix()}"
    settings = AgentSettings(
        core_database_url=url,
        core_seed_on_start=True,
        mcp_call_timeout_seconds=20,
        _env_file=None,  # type: ignore[call-arg]
    )
    llm = FakeLLM([end_turn_response(_REPLY)])
    with TestClient(create_app(settings, llm=llm, clock=FixedAgentClock())) as client:
        response = client.post("/api/chat/stream", json={"message": "No reconozco un cobro"})

    assert response.status_code == 200
    secrets = _seed_secrets()

    # (1) Sin llamada de redacción: el texto es fijo (RN-007-38).
    assert len(llm.stream_requests) == 0

    # (2) Flujo: start y end, sin eventos word, con el literal de spec 007 §7.4.
    events = _parse_sse(response.text)
    assert [name for name, _ in events] == ["start", "end"]
    name, end = events[-1]
    assert name == "end"
    assert end["reply"] == _REMINDER_LOCATE
    assert _REPLY not in end["reply"]
    assert not [s for s in secrets if s in end["reply"]]

    # (3) Cierre normal sin resultados.
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
