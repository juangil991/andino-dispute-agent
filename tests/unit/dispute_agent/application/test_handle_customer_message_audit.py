"""Tests de la auditoría completa del turno de HandleCustomerMessage.

Spec 007: AC-007-30 (unit), RN-007-28, RN-007-29. Incluye tests de soporte de `RedactingAuditLog`
y del evento `tool_call` de `iniciar_disputa`.
"""

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import get_args

import pytest
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.audit_log import AgentAuditEvent, AuditEventType
from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    CardBlocked,
    CardRef,
    CustomerMatch,
    CustomerSearch,
    DisputeOpened,
    EscalationRegistered,
    TransactionPage,
    VerificationResult,
)
from dispute_agent.application.ports.llm import LLMResponse, ToolCall
from dispute_agent.application.redacting_audit_log import RedactingAuditLog
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import HandleCustomerMessage
from dispute_agent.domain.models.conversation import Conversation, KnownCard
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 17)
_PAN = "4111111111114321"
_DOCUMENT = "D-1001"
_CARD = KnownCard("CARD-L1", "4321")
_LIST_ARGS: dict[str, object] = {
    "card_last4": _PAN,
    "date_from": "2026-09-01",
    "date_to": "2026-10-17",
}


class _Repo:
    """Repositorio de conversaciones en memoria, local al test."""

    def __init__(self, *conversations: Conversation) -> None:
        self.items = {c.conversation_id: c for c in conversations}

    def get(self, conversation_id: str) -> Conversation | None:
        return self.items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self.items[conversation.conversation_id] = conversation


def _tx(tx_id: str, amount: str, currency: str = "COP", foreign_days: int | None = None):  # type: ignore[no-untyped-def]
    builder = (
        DisputedTransactionBuilder()
        .transaction_id(tx_id)
        .card("CARD-L1", "**** 4321")
        .amount(amount, currency)
    )
    if foreign_days is None:
        return builder.days_ago(7, _TODAY).national().build()
    return builder.days_ago(foreign_days, _TODAY).foreign().build()


def _verified(*transactions: object) -> Conversation:
    conv = ConversationBuilder().verified("C-0001", (_CARD,)).with_documents(_DOCUMENT).build()
    conv.remember_transactions(transactions)  # type: ignore[arg-type]
    return conv


def _call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def _tools(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(tool_calls=tuple(calls))


def _final(text: str = "Listo.") -> LLMResponse:
    return LLMResponse(text=text)


def _registered() -> EscalationRegistered:
    return EscalationRegistered("E-0001", "PENDING", _NOW, "OTHER")


def _page(*transactions: object) -> TransactionPage:
    return TransactionPage(transactions, False)  # type: ignore[arg-type]


def _opened(tx: object) -> DisputeOpened:
    return DisputeOpened("D-0001", "OPEN", _NOW, "UNRECOGNIZED_CHARGE", tx)  # type: ignore[arg-type]


def _blocked_card() -> CardBlocked:
    return CardBlocked("CARD-L1", "**** 4321", "BLOCKED", _NOW, "FRAUD_SUSPECTED", False)


def _audit_for(repo: _Repo) -> tuple[RedactingAuditLog, FakeAgentAuditLog]:
    inner = FakeAgentAuditLog()
    log = RedactingAuditLog(
        inner, lambda cid: repo.items[cid].provided_documents if cid in repo.items else ()
    )
    return log, inner


def _build(
    script: list[LLMResponse], banking: FakeBankingTools, conv: Conversation
) -> tuple[HandleCustomerMessage, FakeAgentAuditLog]:
    repo = _Repo(conv)
    audit, store = _audit_for(repo)
    clock = FixedAgentClock(_NOW)
    escalation = EscalationService(banking, audit, clock)
    dispute_actions = DisputeActions(
        DisputePolicy(Decimal(4000)), banking, escalation, audit, clock
    )
    fraud_actions = FraudActions(banking, dispute_actions, escalation, audit, clock)
    use_case = HandleCustomerMessage(
        FakeLLM(script),
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
    return use_case, store


def _case_auto_dispute() -> tuple[Conversation, FakeBankingTools, list[LLMResponse]]:
    tx = _tx("TX-L1", "85000.00")
    banking = (
        FakeBankingTools()
        .respond("list_transactions", _page(tx))
        .respond("open_dispute", _opened(tx))
    )
    script = [
        _tools(_call("c1", "consultar_transacciones", **_LIST_ARGS)),
        _tools(_call("c2", "evaluar_disputa", transaction_id="TX-L1")),
        _final(),
    ]
    return _verified(), banking, script


def _case_over_threshold() -> tuple[Conversation, FakeBankingTools, list[LLMResponse]]:
    tx = _tx("TX-L2", "800000.00")
    banking = (
        FakeBankingTools()
        .respond("list_transactions", _page(tx))
        .respond("escalate", _registered())
    )
    script = [
        _tools(_call("c1", "consultar_transacciones", **_LIST_ARGS)),
        _tools(_call("c2", "evaluar_disputa", transaction_id="TX-L2")),
        _final(),
    ]
    return _verified(), banking, script


def _case_outside_policy() -> tuple[Conversation, FakeBankingTools, list[LLMResponse]]:
    tx = _tx("TX-L3", "100.00", "USD", foreign_days=100)
    banking = (
        FakeBankingTools()
        .respond("list_transactions", _page(tx))
        .respond("escalate", _registered())
    )
    script = [
        _tools(_call("c1", "consultar_transacciones", **_LIST_ARGS)),
        _tools(_call("c2", "evaluar_disputa", transaction_id="TX-L3")),
        _final(),
    ]
    return _verified(), banking, script


def _case_fraud_block() -> tuple[Conversation, FakeBankingTools, list[LLMResponse]]:
    tx = _tx("TX-L1", "85000.00")
    banking = (
        FakeBankingTools()
        .respond("list_transactions", _page(tx))
        .respond("block_card", _blocked_card())
        .respond("open_dispute", _opened(tx))
        .respond("escalate", _registered())
    )
    script = [
        _tools(_call("c1", "consultar_transacciones", **_LIST_ARGS)),
        _tools(_call("c2", "reportar_fraude", transaction_ids=["TX-L1"])),
        _final(),
    ]
    return _verified(), banking, script


def _case_human_request() -> tuple[Conversation, FakeBankingTools, list[LLMResponse]]:
    banking = FakeBankingTools().respond("escalate", _registered())
    script = [_tools(_call("c1", "solicitar_atencion_humana")), _final()]
    return _verified(), banking, script


def _case_identity_exhausted() -> tuple[Conversation, FakeBankingTools, list[LLMResponse]]:
    found = CustomerSearch((CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 4321"),)),), False)
    banking = (
        FakeBankingTools()
        .respond("search_customer", found)
        .respond("verify_identity", VerificationResult(False, 0, True))
        .respond("escalate", _registered())
    )
    script = [
        _tools(_call("c1", "buscar_cliente", document=_DOCUMENT, card_last4=_PAN)),
        _tools(
            _call(
                "c2",
                "verificar_identidad",
                birth_date="1990-01-01",
                document_issue_date="2010-01-01",
            )
        ),
        _final(),
    ]
    return ConversationBuilder().build(), banking, script


def _case_system_failure() -> tuple[Conversation, FakeBankingTools, list[LLMResponse]]:
    banking = (
        FakeBankingTools()
        .respond("list_transactions", BankingToolError("INTERNAL", "falla", False))
        .respond("escalate", _registered())
    )
    script = [_tools(_call("c1", "consultar_transacciones", **_LIST_ARGS)), _final()]
    return _verified(), banking, script


def _case_blocked_without_identity() -> tuple[Conversation, FakeBankingTools, list[LLMResponse]]:
    conv = ConversationBuilder().located("C-0001", (_CARD,)).with_documents(_DOCUMENT).build()
    script = [_tools(_call("c1", "consultar_transacciones", **_LIST_ARGS)), _final()]
    return conv, FakeBankingTools(), script


_CaseFactory = Callable[[], tuple[Conversation, FakeBankingTools, list[LLMResponse]]]


# Regla: RN-007-28 — Cada evento genera un registro de auditoría en `AuditLogPort`, en JSON. Hay
# tres tipos de evento: llamada a herramienta (incluidas las bloqueadas), decisión de
# `DisputePolicy` y derivación o cierre. Cada registro lleva `conversation_id`, marca de tiempo del
# reloj inyectado, tipo de evento, entrada, salida, regla aplicada (`DP-007-XX` o `RN-007-XX`) y
# motivo. Ningún registro contiene un número completo de tarjeta ni un documento completo: se
# aplica el filtro de RN-007-26.
# Regla: RN-007-29 — "Hoy" y las marcas de tiempo salen de un `Clock` inyectado en
# `America/Bogota`. El LLM se inyecta por `LLMPort`; la suite por defecto usa un `FakeLLM`
# guionizado (§5.3.1).
# AC-007-30 · Art. 8
@pytest.mark.parametrize(
    ("factory", "expected_rule"),
    [
        (_case_auto_dispute, "DP-007-05"),
        (_case_over_threshold, "DP-007-03"),
        (_case_outside_policy, "DP-007-04"),
        (_case_fraud_block, "DP-007-06"),
        (_case_human_request, "RN-007-18"),
        (_case_identity_exhausted, "RN-007-04"),
        (_case_system_failure, "RN-007-21"),
        (_case_blocked_without_identity, "RN-007-01"),
    ],
    ids=[
        "auto_dispute",
        "amount_over_threshold",
        "outside_policy",
        "fraud_card_block",
        "human_request",
        "identity_attempts_exhausted",
        "system_failure",
        "blocked_without_identity",
    ],
)
async def test_ac_007_30_handle_message__every_case_audited(
    factory: _CaseFactory, expected_rule: str
) -> None:
    """AC-007-30: cada caso deja registros completos con la regla esperada, sin PAN ni documento."""
    conv, banking, script = factory()
    use_case, store = _build(script, banking, conv)

    await use_case.handle(conv.conversation_id, f"Mi tarjeta {_PAN} y mi documento {_DOCUMENT}")

    events = [e for e in store.events if e.conversation_id == conv.conversation_id]
    assert events
    valid_types = set(get_args(AuditEventType))
    for event in events:
        assert event.conversation_id == conv.conversation_id
        assert event.at == _NOW
        assert event.event_type in valid_types
        assert event.input is not None, event
        assert event.output is not None, event
        assert event.rule, event
        assert event.reason, event
    assert expected_rule in {event.rule for event in events}
    dumped = json.dumps([asdict(event) for event in events], default=str)
    assert _PAN not in dumped
    assert _DOCUMENT not in dumped


# Soporte de tests: RedactingAuditLog redacta de forma recursiva y delega en inner · Art. 3
async def test_redacting_audit_log__redacts_nested_values_and_delegates() -> None:
    """RedactingAuditLog redacta str en input/output (dict, lista, tupla), reason, rule y tool."""
    inner = FakeAgentAuditLog()
    log = RedactingAuditLog(inner, lambda _cid: [_DOCUMENT])
    original = AgentAuditEvent(
        conversation_id="conv-0001",
        at=_NOW,
        event_type="tool_call",
        tool=f"t-{_PAN}",
        input={"a": [f"x {_PAN}", {"b": (_DOCUMENT, 3)}], "n": 1},
        output={"c": f"doc {_DOCUMENT}", "d": None},
        rule=f"R {_DOCUMENT}",
        reason=f"motivo {_PAN}",
    )

    log.record(original)

    assert len(inner.events) == 1
    recorded = inner.events[0]
    assert recorded.tool == "t-[REDACTED]"
    assert recorded.input == {"a": ["x [REDACTED]", {"b": ("****01", 3)}], "n": 1}
    assert recorded.output == {"c": "doc ****01", "d": None}
    assert recorded.rule == "R ****01"
    assert recorded.reason == "motivo [REDACTED]"
    assert recorded.at == _NOW
    assert recorded.event_type == "tool_call"
    assert recorded.conversation_id == "conv-0001"


# Soporte de tests: RedactingAuditLog no muta el evento original · Art. 3
async def test_redacting_audit_log__does_not_mutate_original_event() -> None:
    """El evento original queda intacto; se delega una copia nueva."""
    inner = FakeAgentAuditLog()
    log = RedactingAuditLog(inner, lambda _cid: [_DOCUMENT])
    payload: dict[str, object] = {"k": [_PAN]}
    original = AgentAuditEvent("conv-0001", _NOW, "decision", input=payload, reason=_PAN)

    log.record(original)

    assert original.reason == _PAN
    assert payload == {"k": [_PAN]}
    assert inner.events[0] is not original


# Soporte de tests: DisputeActions audita un tool_call por iniciar_disputa · Art. 3
@pytest.mark.parametrize("fails", [False, True], ids=["success", "error"])
async def test_dispute_actions__open_dispute__audits_tool_call(fails: bool) -> None:
    """DisputeActions emite un tool_call de iniciar_disputa con input, output, regla y motivo."""
    tx = _tx("TX-L1", "85000.00")
    conv = _verified(tx)
    banking = FakeBankingTools().respond("escalate", _registered())
    if fails:
        banking.respond("open_dispute", BankingToolError("INTERNAL", "falla", False))
    else:
        banking.respond("open_dispute", _opened(tx))
    audit = FakeAgentAuditLog()
    clock = FixedAgentClock(_NOW)
    actions = DisputeActions(
        DisputePolicy(Decimal(4000)),
        banking,
        EscalationService(banking, audit, clock),
        audit,
        clock,
    )

    await actions.evaluate(conv, "TX-L1")

    calls = [e for e in audit.events if e.event_type == "tool_call"]
    assert len(calls) == 1
    event = calls[0]
    assert event.tool == "iniciar_disputa"
    assert event.input is not None
    assert event.input["transaction_id"] == "TX-L1"
    assert event.input["reason"] == "UNRECOGNIZED_CHARGE"
    assert event.output == ({"error": "INTERNAL"} if fails else {"dispute_id": "D-0001"})
    assert event.rule == "DP-007-05"
    assert event.reason
    assert event.at == _NOW
