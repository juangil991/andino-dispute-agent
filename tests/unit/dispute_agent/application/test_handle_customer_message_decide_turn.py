"""Tests de `decide_turn`, `complete_turn` y `fail_turn` de HandleCustomerMessage.

Spec 009 (T-009-04): refactor sin cambio de comportamiento; habilita AC-009-02, AC-009-03,
AC-009-07 y AC-009-09.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM, end_turn_response
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.banking_tools import EscalationRegistered
from dispute_agent.application.ports.llm import LLMResponse
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import (
    ConversationNotFoundError,
    HandleCustomerMessage,
)
from dispute_agent.domain import messages
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus, KnownCard
from dispute_agent.domain.models.outcome import Outcome, OutcomeKind
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_CARD = KnownCard("CARD-L1", "4321")


class _Repo:
    def __init__(self, *conversations: Conversation) -> None:
        self.items = {c.conversation_id: c for c in conversations}
        self.saves = 0

    def get(self, conversation_id: str) -> Conversation | None:
        return self.items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self.saves += 1
        self.items[conversation.conversation_id] = conversation


def _build(
    script: list[LLMResponse], conv: Conversation
) -> tuple[HandleCustomerMessage, _Repo, FakeBankingTools]:
    banking = FakeBankingTools().respond(
        "escalate",
        EscalationRegistered(
            escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="OTHER"
        ),
    )
    audit = FakeAgentAuditLog()
    clock = FixedAgentClock(_NOW)
    escalation = EscalationService(banking, audit, clock)
    dispute_actions = DisputeActions(
        DisputePolicy(Decimal(4000)), banking, escalation, audit, clock
    )
    fraud_actions = FraudActions(banking, dispute_actions, escalation, audit, clock)
    repo = _Repo(conv)
    use_case = HandleCustomerMessage(
        FakeLLM(list(script)),
        banking,
        repo,
        dispute_actions,
        fraud_actions,
        escalation,
        audit,
        clock,
        SequentialIdGenerator(),
        8,
    )
    return use_case, repo, banking


def _verified_conv() -> Conversation:
    return ConversationBuilder().verified("C-0001", (_CARD,)).build()


def _failure_text() -> str:
    kind = OutcomeKind.LLM_FAILURE
    return f"{messages.OUTCOME_REASONS[kind]} {messages.OUTCOME_NEXT_STEPS[kind]}"


# Regla: RN-009-02 — el ciclo de decisión se ejecuta sin enviar texto a la cliente.
# AC-009-02 · Art. 5
async def test_decide_turn__loop_ends_with_end_turn__returns_outcomes_without_saving_reply() -> (
    None
):
    """AC-009-02: end_turn deja `drafted=True` y no añade ni guarda la respuesta."""
    conv = _verified_conv()
    use_case, repo, _ = _build([end_turn_response("Hola, ¿en qué te ayudo?")], conv)

    decision = await use_case.decide_turn(conv.conversation_id, "Hola")

    assert decision.drafted is True
    assert decision.text == "Hola, ¿en qué te ayudo?"
    assert decision.outcomes == ()
    assert decision.conversation is conv
    assert [m.role for m in conv.history] == ["user"]
    assert repo.saves == 0


# Regla: RN-009-04 — con `max_tokens` el `reply` es texto fijo, sin llamada de redacción.
# AC-009-07 · Art. 5
async def test_decide_turn__loop_ends_with_max_tokens__returns_fixed_failure_text() -> None:
    """AC-009-07: una razón de parada inválida deriva y devuelve el texto fijo sin redactar."""
    conv = _verified_conv()
    use_case, _, _ = _build([LLMResponse(text="parcial", stop_reason="max_tokens")], conv)

    decision = await use_case.decide_turn(conv.conversation_id, "Hola")

    assert decision.drafted is False
    assert decision.text == _failure_text()
    assert [o.kind for o in decision.outcomes] == [OutcomeKind.LLM_FAILURE]
    assert conv.status is ConversationStatus.ESCALATED


# Regla: RN-009-10 — ante una interrupción se deriva una vez con `UNRECOVERABLE_SYSTEM_FAILURE` y
#   se devuelve el texto fijo.
# AC-009-09 · Art. 10
async def test_fail_turn__rule_rn_009_10__escalates_closes_and_returns_fixed_text() -> None:
    """AC-009-09: `fail_turn` deriva, cierra y devuelve el texto fijo con la regla RN-009-10."""
    conv = _verified_conv()
    use_case, _, banking = _build([], conv)
    outcomes: list[Outcome] = []

    text = await use_case.fail_turn(conv, outcomes, rule="RN-009-10")

    assert text.startswith(messages.OUTCOME_REASONS[OutcomeKind.LLM_FAILURE])
    assert [(o.kind, o.rule) for o in outcomes] == [(OutcomeKind.LLM_FAILURE, "RN-009-10")]
    assert outcomes[0].reference == "E-0001"
    assert conv.status is ConversationStatus.ESCALATED
    assert [name for name, _ in banking.calls] == ["escalate"]


# Regla: RN-009-04 — conversación ya cerrada: texto fijo sin redacción (RN-007-24: sin LLM ni
#   herramientas).
# AC-009-07 · Art. 10
async def test_decide_turn__closed_conversation__returns_closed_message_unchanged() -> None:
    """AC-009-03: conversación cerrada devuelve el mensaje fijo, sin LLM ni cambios."""
    conv = _verified_conv()
    conv.close()
    use_case, repo, _ = _build([], conv)

    decision = await use_case.decide_turn(conv.conversation_id, "Hola otra vez")
    result = use_case.complete_turn(decision, decision.text)

    assert decision.drafted is False
    assert decision.text == messages.CONVERSATION_CLOSED_MESSAGE
    assert conv.history == []
    assert repo.saves == 0
    assert result.reply == messages.CONVERSATION_CLOSED_MESSAGE
    assert result.outcomes == ()
    assert result.status is ConversationStatus.ESCALATED


# Regla: RN-009-03 — la redacción sustituye el texto del ciclo; `complete_turn` guarda la
#   respuesta definitiva.
# AC-009-03 · Art. 5
async def test_complete_turn__drafted_reply__appends_redacted_reply_and_saves() -> None:
    """AC-009-02: `complete_turn` guarda la respuesta definitiva en el historial."""
    conv = _verified_conv()
    use_case, repo, _ = _build([end_turn_response("Listo")], conv)
    decision = await use_case.decide_turn(conv.conversation_id, "Hola")

    result = use_case.complete_turn(decision, "Respuesta final")

    assert result.reply == "Respuesta final"
    assert [m.role for m in conv.history] == ["user", "assistant"]
    assert conv.history[-1].text == "Respuesta final"  # type: ignore[union-attr]
    assert repo.saves == 1


# Regla: RN-009-01 — la conversación desconocida falla como error (404) antes de transmitir nada
#   (hereda RN-007-25).
# AC-009-08 · Art. 5
async def test_decide_turn__unknown_conversation__raises_not_found() -> None:
    """`ConversationNotFoundError` sigue lanzándose desde `decide_turn`."""
    use_case, _, _ = _build([], _verified_conv())

    with pytest.raises(ConversationNotFoundError):
        await use_case.decide_turn("NO-EXISTE", "Hola")
