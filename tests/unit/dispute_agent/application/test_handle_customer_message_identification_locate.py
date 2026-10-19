"""Localización de HandleCustomerMessage: ASK_DATES, ASK_MORE_DATA y NOT_FOUND.

Spec 007 0.3.1: AC-007-46, AC-007-48, AC-007-51; RN-007-02, RN-007-05, RN-007-37, RN-007-38,
RN-007-41. Los textos fijos se comparan con el literal de spec §7.4, nunca con la constante.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.banking_tools import (
    CardRef,
    CustomerMatch,
    CustomerSearch,
    EscalationRegistered,
)
from dispute_agent.application.ports.llm import LLMResponse, ToolCall
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import HandleCustomerMessage
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus
from dispute_agent.domain.models.decision import EscalationReason
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_SCRIPT_TEXT = "Claro, ya reviso eso por ti."

# Literales de spec §7.4
_ASK_DATES = (
    "Gracias. Para confirmar tu identidad, indícame tu fecha de nacimiento y la fecha de "
    "expedición de tu documento."
)
_ASK_MORE_DATA = (
    "Necesito un dato adicional para identificarte. Indícame tu número de documento o los "
    "últimos 4 dígitos de tu tarjeta."
)
_NOT_FOUND = (
    "No pudimos identificarte con esos datos. Revísalos e intenta con otro dato: tu número "
    "de documento, tu nombre completo o los últimos 4 dígitos de tu tarjeta."
)
_CLOSED_ESCALATED = (
    "Tu caso requiere la revisión de una persona. Una persona continuará la atención."
)

_ONE_MATCH = CustomerSearch((CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 4321"),)),), False)
_TWO_MATCHES = CustomerSearch(
    (
        CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 4321"),)),
        CustomerMatch("C-0003", (CardRef("CARD-L3", "**** 5555"),)),
    ),
    False,
)
_NO_MATCH = CustomerSearch((), False)


class _Repo:
    def __init__(self, *conversations: Conversation) -> None:
        self.items = {c.conversation_id: c for c in conversations}

    def get(self, conversation_id: str) -> Conversation | None:
        return self.items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self.items[conversation.conversation_id] = conversation


def _call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def _banking(*searches: CustomerSearch) -> FakeBankingTools:
    registered = EscalationRegistered(
        escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="OTHER"
    )
    return FakeBankingTools().respond("escalate", registered).respond("search_customer", *searches)


def _build(
    script: list[LLMResponse], banking: FakeBankingTools, repo: _Repo
) -> tuple[HandleCustomerMessage, FakeAgentAuditLog]:
    audit = FakeAgentAuditLog()
    clock = FixedAgentClock(_NOW)
    escalation = EscalationService(banking, audit, clock)
    dispute_actions = DisputeActions(
        DisputePolicy(Decimal(500000)), banking, escalation, audit, clock
    )
    use_case = HandleCustomerMessage(
        FakeLLM(script),
        banking,
        repo,
        dispute_actions,
        FraudActions(banking, dispute_actions, escalation, audit, clock),
        escalation,
        audit,
        clock,
        SequentialIdGenerator(),
        8,
    )
    return use_case, audit


def _search_script(**arguments: object) -> list[LLMResponse]:
    return [
        LLMResponse(tool_calls=(_call("c1", "buscar_cliente", **arguments),)),
        LLMResponse(text=_SCRIPT_TEXT),
    ]


def _names(banking: FakeBankingTools) -> list[str]:
    return [name for name, _ in banking.calls]


# Regla: RN-007-38 (2) — una sola coincidencia sin refinamiento localiza y pide las fechas.
# AC-007-46 · Art. 7
@pytest.mark.parametrize(
    ("message", "arguments"),
    [
        pytest.param("mi documento es D-1001", {"document": "D-1001"}, id="document"),
        pytest.param("soy Laura Méndez", {"full_name": "Laura Méndez"}, id="full_name"),
        pytest.param("mi tarjeta termina en 4321", {"card_last4": "4321"}, id="card_last4"),
    ],
)
async def test_ac_007_46_handle_message__located_customer__asks_for_dates(
    message: str, arguments: dict[str, object]
) -> None:
    """AC-007-46: con una coincidencia el reply es ASK_DATES y no revela datos de la cliente."""
    banking = _banking(_ONE_MATCH)
    repo = _Repo()
    use_case, _ = _build(_search_script(**arguments), banking, repo)

    result = await use_case.handle(None, message)

    assert result.reply == _ASK_DATES
    outcomes_text = json.dumps([o.__dict__ for o in result.outcomes], default=str)
    for datum in ("C-0001", "Laura Méndez", "****01", "**** 4321", "CARD-L1"):
        assert datum not in result.reply
        assert datum not in outcomes_text
    assert "verify_identity" not in _names(banking)
    assert repo.items[result.conversation_id].located_customer_id == "C-0001"


# Regla: RN-007-05 y RN-007-38 — sin coincidencias: NOT_FOUND y, a la 2.ª búsqueda, cierre.
# AC-007-48 · Art. 10
async def test_ac_007_48_handle_message__no_match__not_found_then_escalates() -> None:
    """AC-007-48: 0 búsquedas previas da NOT_FOUND; 1 previa deriva con el cierre ESCALATED."""
    banking = _banking(_NO_MATCH)
    repo = _Repo()
    use_case, _ = _build(_search_script(document="D-9999"), banking, repo)
    first = await use_case.handle(None, "mi documento es D-9999")
    assert first.reply == _NOT_FOUND
    assert first.status is ConversationStatus.ACTIVE
    assert [n for n in _names(banking) if n == "escalate"] == []

    conv = repo.items[first.conversation_id]
    assert conv.failed_searches == 1
    banking = _banking(_NO_MATCH)
    use_case, _ = _build(_search_script(document="D-9998"), banking, repo)
    second = await use_case.handle(conv.conversation_id, "mi documento es D-9998")

    escalations = [args for name, args in banking.calls if name == "escalate"]
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.INSUFFICIENT_OR_CONTRADICTORY_INFO
    assert escalations[0]["card_id"] is None
    assert escalations[0]["transaction_id"] is None
    assert second.reply == _CLOSED_ESCALATED
    assert second.status is ConversationStatus.ESCALATED


# Regla: RN-007-05 y RN-007-41 — varias coincidencias entre dos vacías no cuentan como vacía.
# AC-007-48 · Art. 10
async def test_ac_007_48_handle_message__multiple_between_empty__stays_active() -> None:
    """AC-007-48: tras 0 -> varias -> 0 fallos acumulados la conversación sigue ACTIVE."""
    repo = _Repo()
    use_case, _ = _build(_search_script(full_name="Laura"), _banking(_TWO_MATCHES), repo)
    first = await use_case.handle(None, "soy Laura")
    assert first.reply == _ASK_MORE_DATA
    conv = repo.items[first.conversation_id]
    assert conv.failed_searches == 0

    banking = _banking(_NO_MATCH)
    use_case, _ = _build(_search_script(document="D-9999"), banking, repo)
    second = await use_case.handle(conv.conversation_id, "mi documento es D-9999")

    assert second.reply == _NOT_FOUND
    assert second.status is ConversationStatus.ACTIVE
    assert "escalate" not in _names(banking)
    assert conv.failed_searches == 1


# Regla: RN-007-37 y RN-007-38 — localizar y pedir otra cosa en un mensaje solo identifica.
# AC-007-51 · Art. 7
async def test_ac_007_51_handle_message__locate_and_dispute_in_one_message__only_identification() -> (  # noqa: E501
    None
):
    """AC-007-51: buscar_cliente localiza, evaluar_disputa se bloquea y el reply es ASK_DATES."""
    banking = _banking(_ONE_MATCH)
    repo = _Repo()
    use_case, audit = _build(
        [
            LLMResponse(
                tool_calls=(
                    _call("c1", "buscar_cliente", document="D-1001"),
                    _call("c2", "evaluar_disputa", transaction_id="TX-L1"),
                )
            ),
            LLMResponse(text=_SCRIPT_TEXT),
        ],
        banking,
        repo,
    )

    result = await use_case.handle(None, "mi documento es D-1001 y no reconozco TX-L1")

    conv = repo.items[result.conversation_id]
    assert conv.located_customer_id == "C-0001"
    assert conv.verified_customer_id is None
    assert [(e.tool, e.rule) for e in audit.events if e.event_type == "tool_blocked"] == [
        ("evaluar_disputa", "RN-007-01")
    ]
    assert conv.decisions == {}
    assert "open_dispute" not in _names(banking)
    assert result.reply == _ASK_DATES
    assert result.outcomes == ()
