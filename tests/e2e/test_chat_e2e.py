"""E2E del agente de disputas: chat -> agente -> MCP stdio real -> SQLite temporal (spec 007)."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    DisputeRow,
    EscalationRow,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_transaction_repository import (
    SqlAlchemyTransactionRepository,
)
from dispute_agent.application.ports.llm import LLMResponse, ToolCall
from dispute_agent.config import AgentSettings
from dispute_agent.main import create_app

_PAN = "4111111111114321"
_DOCUMENT = "D-1001"
# El repositorio del core asigna el identificador opaco de la primera tarjeta (CARD-0001).
_CARD_REF = "CARD-0001"
_IDENTITY = IdentityBuilder()


def _call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def _tools(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(tool_calls=tuple(calls))


def _prepare_database(url: str) -> None:
    """Crea el esquema y los datos ficticios con los repositorios del core; cierra el engine."""
    engine = create_engine_from_url(url)
    try:
        create_schema(engine)
        with session_factory(engine)() as db:
            SqlAlchemyCustomerRepository(db).add(
                CustomerBuilder()
                .with_id("C-0001")
                .with_name("Laura Méndez")
                .with_document(_DOCUMENT)
                .with_card("4321")
                .build(),
                {"4321": _PAN},
                identity=_IDENTITY.build(),
            )
            transactions = SqlAlchemyTransactionRepository(db)
            occurred_at = datetime.now(UTC) - timedelta(days=7)
            for transaction_id, amount in (("TX-L1", "85000.00"), ("TX-L2", "800000.00")):
                transactions.add(
                    _CARD_REF,
                    TransactionBuilder(merchant="Tienda Aurora")
                    .with_id(transaction_id)
                    .with_card(_CARD_REF, "4321")
                    .with_occurred_at(occurred_at)
                    .with_amount(Decimal(amount))
                    .build(),
                )
    finally:
        engine.dispose()


def _script(today: date) -> list[LLMResponse]:
    return [
        _tools(_call("c1", "buscar_cliente", document=_DOCUMENT)),
        LLMResponse(text="Hola Laura, ¿me das tu fecha de nacimiento y la de expedición?"),
        _tools(
            _call(
                "c2",
                "verificar_identidad",
                birth_date=_IDENTITY.birth_date.isoformat(),
                document_issue_date=_IDENTITY.document_issue_date.isoformat(),
            )
        ),
        LLMResponse(text="Gracias, quedaste verificada."),
        _tools(
            _call(
                "c3",
                "consultar_transacciones",
                card_last4="4321",
                date_from=(today - timedelta(days=30)).isoformat(),
                date_to=today.isoformat(),
            )
        ),
        LLMResponse(text="Veo dos cobros recientes en tu tarjeta."),
        _tools(
            _call("c4", "evaluar_disputa", transaction_id="TX-L1"),
            _call("c5", "evaluar_disputa", transaction_id="TX-L2"),
        ),
        LLMResponse(text="Abrimos la disputa de un cobro y derivamos el otro."),
    ]


def _read_core(url: str) -> tuple[list[DisputeRow], list[EscalationRow]]:
    engine = create_engine_from_url(url)
    try:
        with Session(engine, expire_on_commit=False) as db:
            return (
                list(db.scalars(select(DisputeRow))),
                list(db.scalars(select(EscalationRow))),
            )
    finally:
        engine.dispose()


# Regla: RN-007-03 — Para verificar, el agente pide al cliente su fecha de nacimiento y la fecha
# de expedición de su documento e invoca `verificar_identidad` con el `customer_id` localizado
# (spec 002).
# Regla: RN-007-20 — Cada transacción con decisión `ESCALATE` genera su **propia** derivación con
# `escalar_a_analista`, con su `transaction_id`, el `card_id` de la transacción, las acciones
# previas sobre ella (`DISPUTE_OPENED` con `dispute_id`, `CARD_BLOCKED`) y la nota
# `<ID de regla>: <motivo comunicado>` de §5. Las derivaciones sin transacción (identidad,
# petición de una persona, falla, límite de iteraciones, fraude sin transacción) se registran una
# sola vez por causa. Cada derivación usa una `idempotency_key` propia, que solo se reutiliza para
# reintentar esa misma solicitud.
# Regla: DP-007-03 — ¬fraude ∧ `status = CONFIRMED` ∧ monto equivalente > 500.000 COP: ESCALATE
# (`AMOUNT_OVER_THRESHOLD`); `escalar_a_analista`; `El monto supera el límite para abrir disputas
# automáticamente.`; `Un analista revisará tu caso y te contactará.`
# Regla: DP-007-05 — ¬fraude ∧ `status = CONFIRMED` ∧ monto equivalente ≤ 500.000 COP ∧
# (comercio nacional ∨ antigüedad ≤ 90 días): RESOLVE; `iniciar_disputa`; `El cobro cumple las
# condiciones para abrir la disputa de inmediato.`; `Tu disputa quedó abierta; el banco la
# gestionará y te informará el resultado.`
# AC-007-34 · Art. 6
def test_ac_007_34_chat_e2e__identify_verify_and_dispute__dispute_and_escalation_in_core(
    tmp_path: Path,
) -> None:
    """AC-007-34 (y AC-007-01, AC-007-05): flujo completo contra el servidor MCP real por stdio."""
    url = f"sqlite:///{(tmp_path / 'core.db').as_posix()}"
    _prepare_database(url)
    settings = AgentSettings(
        core_database_url=url,
        core_seed_on_start=False,
        mcp_call_timeout_seconds=20,
        _env_file=None,  # type: ignore[call-arg]
    )
    llm = FakeLLM(_script(date.today()))
    messages = [
        f"Mi documento es {_DOCUMENT}",
        "Nací el 14 de marzo de 1985 y mi documento se expidió el 2 de abril de 2005",
        "Muéstrame mis transacciones recientes",
        "No reconozco ninguno de esos dos cobros",
    ]

    bodies: list[dict[str, Any]] = []
    with TestClient(create_app(settings, llm=llm)) as client:
        conversation_id: str | None = None
        for text in messages:
            payload: dict[str, Any] = {"message": text}
            if conversation_id is not None:
                payload["conversation_id"] = conversation_id
            response = client.post("/api/chat", json=payload)
            assert response.status_code == 200, response.text
            bodies.append(response.json())
            conversation_id = bodies[-1]["conversation_id"]

    last = bodies[-1]
    assert last["status"] == "ACTIVE"
    by_kind = {o["kind"]: o for o in last["outcomes"]}
    assert sorted(by_kind) == ["DISPUTE_OPENED", "ESCALATED"]
    assert len(last["outcomes"]) == 2
    opened, escalated = by_kind["DISPUTE_OPENED"], by_kind["ESCALATED"]
    assert (opened["transaction_id"], opened["rule"]) == ("TX-L1", "DP-007-05")
    assert (escalated["transaction_id"], escalated["rule"]) == ("TX-L2", "DP-007-03")

    disputes, escalations = _read_core(url)
    assert [(d.transaction_id, d.status) for d in disputes] == [("TX-L1", "OPEN")]
    assert opened["reference"] == disputes[0].dispute_id
    assert [(e.transaction_id, e.status, e.reason) for e in escalations] == [
        ("TX-L2", "PENDING", "AMOUNT_OVER_THRESHOLD")
    ]

    for body in bodies:
        serialized = str(body["reply"]) + str(body["outcomes"])
        assert _PAN not in serialized
        assert _DOCUMENT not in serialized


def _script_future_date_to(today: date) -> list[LLMResponse]:
    """Verificación y luego una consulta con `date_to` futuro y otra con fechas válidas."""
    verification = _script(today)[:4]
    return [
        *verification,
        _tools(
            _call(
                "c3",
                "consultar_transacciones",
                card_last4="4321",
                date_from=(today - timedelta(days=30)).isoformat(),
                date_to="2099-01-01",
            )
        ),
        _tools(
            _call(
                "c4",
                "consultar_transacciones",
                card_last4="4321",
                date_from=(today - timedelta(days=30)).isoformat(),
                date_to=today.isoformat(),
            )
        ),
        LLMResponse(text="Veo dos cobros recientes en tu tarjeta."),
    ]


# Regla: RN-010-01 — un INVALID_INPUT de `consultar_transacciones` se devuelve al LLM para corregir.
# Regla: RN-010-07 — cada rechazo corregible queda auditado como `tool_call` con el campo.
# AC-010-12 · Art. 8 (auditoría) · Art. 10 (no derivar sin necesidad)
def test_ac_010_12_chat__future_date_to_with_real_server__llm_corrects_and_conversation_stays_active(  # noqa: E501
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-010-12: `date_to` futuro rechazado por el servidor real; el LLM corrige y sigue ACTIVE."""
    url = f"sqlite:///{(tmp_path / 'core.db').as_posix()}"
    _prepare_database(url)
    settings = AgentSettings(
        core_database_url=url,
        core_seed_on_start=False,
        mcp_call_timeout_seconds=20,
        _env_file=None,  # type: ignore[call-arg]
    )
    llm = FakeLLM(_script_future_date_to(date.today()))
    messages = [
        f"Mi documento es {_DOCUMENT}",
        "Nací el 14 de marzo de 1985 y mi documento se expidió el 2 de abril de 2005",
        "Quiero revisar un cobro de mi tarjeta",
    ]

    bodies: list[dict[str, Any]] = []
    with TestClient(create_app(settings, llm=llm)) as client:
        conversation_id: str | None = None
        for text in messages:
            payload: dict[str, Any] = {"message": text}
            if conversation_id is not None:
                payload["conversation_id"] = conversation_id
            response = client.post("/api/chat", json=payload)
            assert response.status_code == 200, response.text
            bodies.append(response.json())
            conversation_id = bodies[-1]["conversation_id"]

    last = bodies[-1]
    assert last["status"] == "ACTIVE"
    assert last["outcomes"] == []
    assert last["reply"] == "Veo dos cobros recientes en tu tarjeta."
    _, escalations = _read_core(url)
    assert escalations == []

    audit_records = [
        json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")
    ]
    rejected = [
        r
        for r in audit_records
        if r.get("event_type") == "tool_call" and r.get("rule") == "RN-010-01"
    ]
    assert len(rejected) == 1
    assert rejected[0]["tool"] == "consultar_transacciones"
    assert rejected[0]["conversation_id"] == conversation_id
    assert rejected[0]["output"] == {
        "error": "INVALID_INPUT",
        "field": "date_to",
        "correction": 1,
        "of": 2,
    }
    assert not [r for r in audit_records if r.get("event_type") == "escalation"]


_WRONG_LAST4 = (
    "4231"  # dígitos de la tarjeta 4321 intercambiados; no es de ninguna tarjeta de la clienta
)


def _script_wrong_card_then_correct(today: date) -> list[LLMResponse]:
    """Verificación, consulta con tarjeta ajena (4231) y luego con la correcta (4321)."""
    verification = _script(today)[:4]
    date_from = (today - timedelta(days=89)).isoformat()  # 90 días contando ambos extremos
    return [
        *verification,
        _tools(
            _call(
                "c3",
                "consultar_transacciones",
                card_last4=_WRONG_LAST4,
                date_from=date_from,
                date_to=today.isoformat(),
            )
        ),
        _tools(
            _call(
                "c4",
                "consultar_transacciones",
                card_last4="4321",
                date_from=date_from,
                date_to=today.isoformat(),
            )
        ),
        LLMResponse(text="Veo dos cobros recientes en tu tarjeta."),
    ]


# Regla: RN-011-03 — una tarjeta que no es de la clienta no llega al servidor; se devuelve al LLM.
# Regla: RN-011-09 — el rechazo queda auditado como `tool_call` sin los 4 dígitos pedidos.
# AC-011-12 · Art. 8 (auditoría) · Art. 10 (no derivar sin necesidad)
def test_ac_011_12_chat__wrong_card_digits_with_real_server__guard_blocks_then_llm_corrects(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-011-12: la guarda frena la tarjeta ajena; el LLM corrige y sigue ACTIVE."""
    url = f"sqlite:///{(tmp_path / 'core.db').as_posix()}"
    _prepare_database(url)
    settings = AgentSettings(
        core_database_url=url,
        core_seed_on_start=False,
        mcp_call_timeout_seconds=20,
        _env_file=None,  # type: ignore[call-arg]
    )
    llm = FakeLLM(_script_wrong_card_then_correct(date.today()))
    messages = [
        f"Mi documento es {_DOCUMENT}",
        "Nací el 14 de marzo de 1985 y mi documento se expidió el 2 de abril de 2005",
        "Quiero revisar un cobro de mi tarjeta",
    ]

    bodies: list[dict[str, Any]] = []
    with TestClient(create_app(settings, llm=llm)) as client:
        conversation_id: str | None = None
        for text in messages:
            payload: dict[str, Any] = {"message": text}
            if conversation_id is not None:
                payload["conversation_id"] = conversation_id
            response = client.post("/api/chat", json=payload)
            assert response.status_code == 200, response.text
            bodies.append(response.json())
            conversation_id = bodies[-1]["conversation_id"]

    last = bodies[-1]
    assert last["status"] == "ACTIVE"
    assert last["outcomes"] == []
    assert last["reply"] == "Veo dos cobros recientes en tu tarjeta."
    _, escalations = _read_core(url)
    assert escalations == []

    audit_records = [
        json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")
    ]
    rejected = [
        r
        for r in audit_records
        if r.get("event_type") == "tool_call" and r.get("rule") == "RN-011-03"
    ]
    assert len(rejected) == 1
    assert rejected[0]["tool"] == "consultar_transacciones"
    assert rejected[0]["conversation_id"] == conversation_id
    assert rejected[0]["output"] == {"error": "UNKNOWN_CARD", "correction": 1, "of": 2}
    assert _WRONG_LAST4 not in json.dumps(rejected[0]["input"])
    # El servidor no recibió la 1.ª petición: ninguna consulta con el valor erróneo llegó a él.
    queries = [
        r
        for r in audit_records
        if r.get("event_type") == "tool_call"
        and r.get("tool") == "consultar_transacciones"
        and r.get("rule") != "RN-011-03"
    ]
    assert len(queries) == 1
    assert _WRONG_LAST4 not in json.dumps(queries[0])
    # La 2.ª consulta (rango válido de 90 días) devolvió transacciones, no un INVALID_INPUT.
    assert not [r for r in audit_records if r.get("rule") == "RN-010-01"]
    assert "INVALID_INPUT" not in json.dumps(queries[0])
    assert queries[0]["output"] == {"transactions": 2, "refinement_required": False}
    assert queries[0]["input"]["card_last4"] == "4321"
    assert not [r for r in audit_records if r.get("event_type") == "escalation"]
