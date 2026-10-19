"""Guarda de identificación de HandleCustomerMessage en `evaluar_disputa`.

Spec 007 0.3.0: AC-007-50 (fila 2); RN-007-01, RN-007-37.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.banking_tools import (
    EscalationRegistered,
    VerificationResult,
)
from dispute_agent.application.ports.llm import LLMResponse, ToolCall
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import HandleCustomerMessage
from dispute_agent.domain.models.conversation import Conversation, KnownCard
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 17)
_CARD = KnownCard("CARD-L1", "4321")
_VERIFY_ARGS = {"birth_date": "1990-05-17", "document_issue_date": "2010-06-01"}


class _Repo:
    def __init__(self, *conversations: Conversation) -> None:
        self.items = {c.conversation_id: c for c in conversations}

    def get(self, conversation_id: str) -> Conversation | None:
        return self.items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self.items[conversation.conversation_id] = conversation


def _call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def _build(
    script: list[LLMResponse], banking: FakeBankingTools, conv: Conversation
) -> tuple[HandleCustomerMessage, FakeAgentAuditLog]:
    audit = FakeAgentAuditLog()
    clock = FixedAgentClock(_NOW)
    escalation = EscalationService(banking, audit, clock)
    dispute_actions = DisputeActions(
        DisputePolicy(Decimal(4000)), banking, escalation, audit, clock
    )
    use_case = HandleCustomerMessage(
        FakeLLM(script),
        banking,
        _Repo(conv),
        dispute_actions,
        FraudActions(banking, dispute_actions, escalation, audit, clock),
        escalation,
        audit,
        clock,
        SequentialIdGenerator(),
        8,
    )
    return use_case, audit


def _located_conv() -> Conversation:
    conv = ConversationBuilder().located("C-0001", (_CARD,)).build()
    tx = (
        DisputedTransactionBuilder()
        .transaction_id("TX-L1")
        .card("CARD-L1", "**** 4321")
        .amount("85000.00", "COP")
        .days_ago(7, _TODAY)
        .national()
        .build()
    )
    conv.remember_transactions([tx])
    return conv


def _banking() -> FakeBankingTools:
    registered = EscalationRegistered(
        escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="OTHER"
    )
    return (
        FakeBankingTools()
        .respond("escalate", registered)
        .respond("verify_identity", VerificationResult(True, 3, False))
    )


# Regla: RN-007-37 — La guarda se evalúa **en cada petición**, con el estado de verificación de
# ese momento: si la cliente queda verificada a mitad del turno, las peticiones posteriores de
# ese turno se atienden con normalidad.
# AC-007-50 · Art. 7
async def test_ac_007_50_handle_message__evaluate_before_verify__blocked_by_guard() -> None:
    """AC-007-50: evaluar_disputa antes de verificar en la misma respuesta queda bloqueada."""
    conv = _located_conv()
    banking = _banking()
    use_case, audit = _build(
        [
            LLMResponse(
                tool_calls=(
                    _call("c1", "evaluar_disputa", transaction_id="TX-L1"),
                    _call("c2", "verificar_identidad", **_VERIFY_ARGS),
                )
            ),
            LLMResponse(text="Texto del guion."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "No reconozco TX-L1")

    blocked = [(e.tool, e.rule) for e in audit.events if e.event_type == "tool_blocked"]
    assert blocked == [("evaluar_disputa", "RN-007-01")]
    assert conv.decisions == {}
    assert "open_dispute" not in [name for name, _ in banking.calls]
    assert conv.verified_customer_id == "C-0001"
    assert result.reply == "Texto del guion."


# Soporte de tests: el rastro de herramientas bloqueadas es por turno · Art. 7
async def test_handle_message__blocked_tools__recorded_per_turn() -> None:
    """RN-007-37: `turn_blocked_tools` anota los bloqueos del turno y se vacía en el siguiente."""
    conv = ConversationBuilder().located("C-0001", (_CARD,)).build()
    use_case, _ = _build(
        [
            LLMResponse(tool_calls=(_call("c1", "evaluar_disputa", transaction_id="TX-L1"),)),
            LLMResponse(text="Uno."),
            LLMResponse(text="Dos."),
        ],
        _banking(),
        conv,
    )

    await use_case.handle(conv.conversation_id, "uno")
    assert conv.turn_blocked_tools == ["evaluar_disputa"]

    await use_case.handle(conv.conversation_id, "dos")
    assert conv.turn_blocked_tools == []
