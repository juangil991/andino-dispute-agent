"""Tests de la API `POST /api/chat` con la app real compuesta por `create_app`.

Spec 007: AC-007-01, AC-007-26 y AC-007-31 (§7.3).
"""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock

from dispute_agent.application.ports.banking_tools import (
    CardRef,
    CustomerMatch,
    CustomerSearch,
    DisputeOpened,
    EscalationRegistered,
    TransactionPage,
    VerificationResult,
)
from dispute_agent.application.ports.llm import LLMResponse, ToolCall
from dispute_agent.config import AgentSettings
from dispute_agent.domain import messages
from dispute_agent.main import create_app

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 17)


def _settings() -> AgentSettings:
    return AgentSettings(_env_file=None)  # type: ignore[call-arg]


def _call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def _tools(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(tool_calls=tuple(calls))


def _registered() -> EscalationRegistered:
    return EscalationRegistered(
        escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="OTHER"
    )


def _verify_in_turn() -> LLMResponse:
    """Guion que deja verificada a la cliente en el propio turno (RN-007-39)."""
    return _tools(
        _call("v1", "buscar_cliente", document="D-1001"),
        _call(
            "v2", "verificar_identidad", birth_date="1990-01-01", document_issue_date="2010-01-01"
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


def _client(llm: FakeLLM, banking: FakeBankingTools | None = None) -> TestClient:
    app = create_app(
        _settings(),
        banking=banking if banking is not None else FakeBankingTools(),
        llm=llm,
        clock=FixedAgentClock(_NOW),
    )
    return TestClient(app)


# Regla: RN-007-25 — Cada respuesta de `POST /api/chat` incluye el texto redactado por el LLM
# (`reply`) y la lista estructurada `outcomes` con lo ocurrido en el turno (§7.3): por cada
# acción o decisión, su tipo, la transacción o tarjeta enmascarada, la regla aplicada, el motivo
# y los próximos pasos, ambos en español y con el texto fijo de §5 o de §7.3. El LLM recibe esos
# `outcomes` para redactar la respuesta, pero no puede alterarlos.
# AC-007-31 · Art. 5
def test_ac_007_31_chat_api__invalid_requests__rejected_without_calling_llm() -> None:
    """AC-007-31: las 6 filas del contrato de POST /api/chat."""
    llm = FakeLLM(
        [
            _verify_in_turn(),
            LLMResponse(text="Hola, ¿en qué te ayudo?"),
            LLMResponse(text="Sigo aquí."),
        ]
    )
    with _client(llm, _verified_banking()) as client:
        # Fila 1: sin conversation_id -> conversación nueva.
        first = client.post("/api/chat", json={"message": "hola"})
        assert first.status_code == 200
        body = first.json()
        assert body["conversation_id"]
        assert body["reply"] == "Hola, ¿en qué te ayudo?"
        assert body["status"] == "ACTIVE"
        assert body["outcomes"] == []

        # Fila 2: con el id devuelto -> mismo id y el historial previo llega al LLM.
        second = client.post(
            "/api/chat", json={"conversation_id": body["conversation_id"], "message": "hola"}
        )
        assert second.status_code == 200
        assert second.json()["conversation_id"] == body["conversation_id"]
        # Primer turno: 2 llamadas al LLM (verificación y respuesta); segundo turno: 1.
        assert len(llm.requests) == 3
        sent = [(m.role, m.text) for m in llm.requests[2].messages]
        assert ("user", "hola") in sent
        assert ("assistant", "Hola, ¿en qué te ayudo?") in sent

        calls_before = len(llm.requests)
        # Fila 3: conversación desconocida -> 404.
        unknown = client.post(
            "/api/chat", json={"conversation_id": "desconocida", "message": "hola"}
        )
        assert unknown.status_code == 404
        # Fila 4: mensaje vacío o solo espacios -> 422.
        assert client.post("/api/chat", json={"message": ""}).status_code == 422
        assert client.post("/api/chat", json={"message": "   "}).status_code == 422
        # Fila 5: 2001 caracteres -> 422.
        assert client.post("/api/chat", json={"message": "a" * 2001}).status_code == 422
        # Fila 6: `{}` o JSON inválido -> 422.
        assert client.post("/api/chat", json={}).status_code == 422
        invalid = client.post(
            "/api/chat", content="{no es json", headers={"Content-Type": "application/json"}
        )
        assert invalid.status_code == 422
        assert len(llm.requests) == calls_before


# Soporte de tests: el límite de 2000 caracteres y el recorte de espacios del mensaje
# (§7.3) · Art. 3
def test_chat_api__message_boundaries__2000_chars_and_trim() -> None:
    llm = FakeLLM([LLMResponse(text="ok"), LLMResponse(text="ok")])
    with _client(llm) as client:
        assert client.post("/api/chat", json={"message": "a" * 2000}).status_code == 200
        assert client.post("/api/chat", json={"message": "  hola  "}).status_code == 200
    assert llm.requests[1].messages[-1].text == "hola"


def _dispute_flow_script(transaction_id: str, final_text: str) -> list[LLMResponse]:
    return [
        _tools(_call("c1", "buscar_cliente", document="D-1001")),
        _tools(
            _call(
                "c2",
                "verificar_identidad",
                birth_date="1990-01-01",
                document_issue_date="2010-01-01",
            )
        ),
        _tools(
            _call(
                "c3",
                "consultar_transacciones",
                card_last4="4321",
                date_from="2026-09-01",
                date_to="2026-10-17",
            )
        ),
        _tools(_call("c4", "evaluar_disputa", transaction_id=transaction_id)),
        LLMResponse(text=final_text),
    ]


def _dispute_banking() -> FakeBankingTools:
    tx = (
        DisputedTransactionBuilder()
        .transaction_id("TX-L1")
        .card("CARD-L1", "**** 4321")
        .amount("85000.00", "COP")
        .days_ago(7, _TODAY)
        .national()
        .build()
    )
    return (
        FakeBankingTools()
        .respond(
            "search_customer",
            CustomerSearch((CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 4321"),)),), False),
        )
        .respond("verify_identity", VerificationResult(True, 3, False))
        .respond("list_transactions", TransactionPage((tx,), False))
        .respond(
            "open_dispute",
            DisputeOpened("D-0001", "OPEN", _NOW, "UNRECOGNIZED_CHARGE", tx),
        )
        .respond("escalate", _registered())
    )


# Regla: RN-007-25 — Cada respuesta de `POST /api/chat` incluye el texto redactado por el LLM
# (`reply`) y la lista estructurada `outcomes` con lo ocurrido en el turno (§7.3): por cada
# acción o decisión, su tipo, la transacción o tarjeta enmascarada, la regla aplicada, el motivo
# y los próximos pasos, ambos en español y con el texto fijo de §5 o de §7.3. El LLM recibe esos
# `outcomes` para redactar la respuesta, pero no puede alterarlos.
# Regla: DP-007-05 — ¬fraude ∧ `status = CONFIRMED` ∧ monto equivalente ≤ 500.000 COP ∧
# (comercio nacional ∨ antigüedad ≤ 90 días): RESOLVE; `iniciar_disputa`
# AC-007-01 · Art. 5
def test_ac_007_01_chat_api__dispute_opened__outcomes_in_response() -> None:
    """AC-007-01: 85.000 COP nacional -> DISPUTE_OPENED con DP-007-05 y el dispute_id."""
    banking = _dispute_banking()
    llm = FakeLLM(_dispute_flow_script("TX-L1", "Abrimos tu disputa."))
    with _client(llm, banking) as client:
        response = client.post("/api/chat", json={"message": "No reconozco el cobro TX-L1"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["reply"] == "Abrimos tu disputa."
    assert len(body["outcomes"]) == 1
    outcome = body["outcomes"][0]
    assert outcome["kind"] == "DISPUTE_OPENED"
    assert outcome["transaction_id"] == "TX-L1"
    assert outcome["rule"] == "DP-007-05"
    assert outcome["reference"] == "D-0001"
    assert outcome["reason"] == messages.DP_REASONS["DP-007-05"]
    assert outcome["next_steps"] == messages.DP_NEXT_STEPS["DP-007-05"]
    opens = [args for name, args in banking.calls if name == "open_dispute"]
    assert [(a["transaction_id"], a["reason"]) for a in opens] == [("TX-L1", "UNRECOGNIZED_CHARGE")]
    assert not [name for name, _ in banking.calls if name == "escalate"]


# Regla: RN-007-24 — Una conversación se **cierra** tras derivar por petición de una persona
# (RN-007-18/19), fraude sin identidad (RN-007-17), identificación fallida (RN-007-04/05), falla
# del sistema (RN-007-21/22) o límite de iteraciones (RN-007-23). En una conversación cerrada, el
# agente no llama al LLM ni a ninguna herramienta y responde con el mensaje fijo `Tu caso ya fue
# derivado a un analista. Una persona continuará la atención.` Las derivaciones de una
# transacción por DP-007-02/03/04/06/07 **no** cierran la conversación.
# AC-007-26 · Art. 5
def test_ac_007_26_chat_api__closed_conversation__escalated_status() -> None:
    """AC-007-26: tras derivar por petición de una persona, el siguiente mensaje no llama a nada."""
    banking = FakeBankingTools().respond("escalate", _registered())
    llm = FakeLLM(
        [
            _tools(_call("c1", "solicitar_atencion_humana")),
            LLMResponse(text="Te derivamos con una persona."),
        ]
    )
    with _client(llm, banking) as client:
        first = client.post("/api/chat", json={"message": "Quiero hablar con una persona"})
        assert first.status_code == 200
        assert first.json()["status"] == "ESCALATED"
        llm_calls = len(llm.requests)
        banking_calls = len(banking.calls)

        second = client.post(
            "/api/chat",
            json={"conversation_id": first.json()["conversation_id"], "message": "¿hola?"},
        )

    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "ESCALATED"
    assert body["reply"] == (
        "Tu caso ya fue derivado a un analista. Una persona continuará la atención."
    )
    assert body["reply"] == messages.CONVERSATION_CLOSED_MESSAGE
    assert body["outcomes"] == []
    assert len(llm.requests) == llm_calls
    assert len(banking.calls) == banking_calls


# Soporte de tests: el filtro de PAN (RN-007-26) llega a `reply` por el endpoint · Art. 3
def test_chat_api__pan_in_llm_reply__is_redacted() -> None:
    llm = FakeLLM(
        [_verify_in_turn(), LLMResponse(text="Tu tarjeta 4111111111114321 fue revisada.")]
    )
    with _client(llm, _verified_banking()) as client:
        response = client.post("/api/chat", json={"message": "hola"})
    assert "4111111111114321" not in response.json()["reply"]
    assert "[REDACTED]" in response.json()["reply"]


# Soporte de tests: con `banking` inyectado el lifespan no abre ni cierra nada · Art. 3
@pytest.mark.parametrize("use_context", [True, False], ids=["with_lifespan", "without_lifespan"])
def test_chat_api__injected_banking__lifespan_does_not_touch_it(use_context: bool) -> None:
    class _NoLifecycleBanking(FakeBankingTools):
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"el lifespan no debe tocar la banca inyectada: {name}")

    llm = FakeLLM([LLMResponse(text="ok")])
    app = create_app(_settings(), banking=_NoLifecycleBanking(), llm=llm)
    if use_context:
        with TestClient(app) as client:
            assert client.post("/api/chat", json={"message": "hola"}).status_code == 200
    else:
        assert TestClient(app).post("/api/chat", json={"message": "hola"}).status_code == 200
