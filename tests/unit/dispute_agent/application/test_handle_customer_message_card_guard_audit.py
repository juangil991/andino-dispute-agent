"""Tests de auditoría de los rechazos de tarjeta corregibles de HandleCustomerMessage.

Spec 011: AC-011-10, RN-011-09.
"""

from datetime import UTC, datetime
from decimal import Decimal

from tests.fakes.banking_errors import not_found
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.llm import LLMResponse, ToolCall
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import HandleCustomerMessage
from dispute_agent.domain.models.conversation import Conversation, KnownCard
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
_CARD = KnownCard("CARD-L1", "4321")
_DATES: dict[str, object] = {"date_from": "2026-09-01", "date_to": "2026-10-17"}


class _Repo:
    """Repositorio de conversaciones en memoria, local al test."""

    def __init__(self, *conversations: Conversation) -> None:
        self.items = {c.conversation_id: c for c in conversations}

    def get(self, conversation_id: str) -> Conversation | None:
        return self.items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self.items[conversation.conversation_id] = conversation


def _build(
    script: list[LLMResponse], banking: FakeBankingTools, conv: Conversation
) -> tuple[HandleCustomerMessage, FakeAgentAuditLog]:
    audit = FakeAgentAuditLog()
    clock = FixedAgentClock(_NOW)
    escalation = EscalationService(banking, audit, clock)
    dispute_actions = DisputeActions(
        DisputePolicy(Decimal(4000)), banking, escalation, audit, clock
    )
    fraud_actions = FraudActions(banking, dispute_actions, escalation, audit, clock)
    use_case = HandleCustomerMessage(
        FakeLLM(script),
        banking,
        _Repo(conv),
        dispute_actions,
        fraud_actions,
        escalation,
        audit,
        clock,
        SequentialIdGenerator(),
        8,
    )
    return use_case, audit


def _list_call(call_id: str, last4: str) -> LLMResponse:
    args = {"card_last4": last4, **_DATES}
    return LLMResponse(tool_calls=(ToolCall(call_id, "consultar_transacciones", args),))


# Regla: RN-011-09 — Cada rechazo corregible genera un `tool_call` con la herramienta, la salida
# `{error, correction, of}`, la regla (RN-011-03 o RN-011-05) y el motivo fijo de §7.3.
# AC-011-10 · Art. 8
async def test_ac_011_10_audit__foreign_card_first_rejection__tool_call_rn_011_03() -> None:
    """AC-011-10: la tarjeta ajena deja un tool_call sin los 4 dígitos pedidos."""
    conv = ConversationBuilder().verified("C-0001", (_CARD,)).build()
    use_case, audit = _build(
        [_list_call("c1", "9999"), LLMResponse(text="Esa tarjeta no es tuya.")],
        FakeBankingTools(),
        conv,
    )

    await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    events = [e for e in audit.events if e.event_type == "tool_call"]
    assert len(events) == 1
    event = events[0]
    assert event.conversation_id == conv.conversation_id
    assert event.at == _NOW
    assert event.tool == "consultar_transacciones"
    assert event.input == {"fields": sorted(["card_last4", "date_from", "date_to"])}
    assert event.output == {"error": "UNKNOWN_CARD", "correction": 1, "of": 2}
    assert event.rule == "RN-011-03"
    assert event.reason == "la tarjeta no es de la clienta; se devuelve al LLM para corregirla"
    assert "9999" not in str(event)


# Regla: RN-011-09 — el NOT_FOUND corregible se audita con RN-011-05 y sin el texto del servidor.
# AC-011-10 · Art. 8
async def test_ac_011_10_audit__not_found_second_rejection__tool_call_rn_011_05() -> None:
    """AC-011-10: el NOT_FOUND corregible deja un tool_call sin el texto del servidor."""
    conv = ConversationBuilder().verified("C-0001", (_CARD,)).build()
    banking = FakeBankingTools().respond("list_transactions", not_found("texto del servidor"))
    use_case, audit = _build(
        [
            _list_call("c1", "9999"),
            _list_call("c2", "4321"),
            LLMResponse(text="Revisa los dígitos."),
        ],
        banking,
        conv,
    )

    await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    events = [e for e in audit.events if e.event_type == "tool_call"]
    assert len(events) == 2
    event = events[1]
    assert event.conversation_id == conv.conversation_id
    assert event.at == _NOW
    assert event.tool == "consultar_transacciones"
    assert event.input == {"card_last4": "4321", **_DATES}
    assert event.output == {"error": "NOT_FOUND", "correction": 2, "of": 2}
    assert event.rule == "RN-011-05"
    assert event.reason == (
        "tarjeta no encontrada por el core; se devuelve al LLM para que la clienta "
        "revise los dígitos"
    )
    assert "texto del servidor" not in str(event)
    assert "conversation_closed" not in [e.event_type for e in audit.events]
