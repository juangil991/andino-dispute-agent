"""Tests de FraudActions (spec 007: AC-007-09, 10, 19, 23; DP-007-06/07; RN-007-14…17, 21)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fixed_agent_clock import FixedAgentClock

from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolUnavailableError,
    CardBlocked,
    DisputeOpened,
    EscalationRegistered,
)
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.domain import messages
from dispute_agent.domain.models.conversation import (
    Conversation,
    ConversationStatus,
    KnownCard,
)
from dispute_agent.domain.models.decision import EscalationReason, PriorAction
from dispute_agent.domain.models.outcome import OutcomeKind
from dispute_agent.domain.models.transaction import DisputedTransaction, TransactionStatus
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_TODAY = _NOW.date()
_CARD_1 = KnownCard("CARD-L1", "4321")
_CARD_2 = KnownCard("CARD-L2", "8765")
_CARD_3 = KnownCard("CARD-L3", "4321")


def _tx(
    tx_id: str = "TX-L1",
    card_id: str = "CARD-L1",
    amount: str = "85000.00",
    days: int = 3,
    foreign: bool = False,
    status: TransactionStatus = TransactionStatus.CONFIRMED,
) -> DisputedTransaction:
    builder = (
        DisputedTransactionBuilder()
        .transaction_id(tx_id)
        .card(card_id, "**** 4321")
        .amount(amount, "COP")
        .status(status)
        .days_ago(days, _TODAY)
    )
    return (builder.foreign() if foreign else builder.national()).build()


def _blocked(already: bool = False, card_id: str = "CARD-L1") -> CardBlocked:
    return CardBlocked(
        card_id=card_id,
        masked_card="**** 4321",
        status="BLOCKED",
        blocked_at=_NOW,
        reason="FRAUD_SUSPECTED",
        already_blocked=already,
    )


def _opened(tx: DisputedTransaction) -> DisputeOpened:
    return DisputeOpened(
        dispute_id="D-0001",
        status="OPEN",
        opened_at=_NOW,
        reason="UNRECOGNIZED_CHARGE",
        transaction=tx,
    )


def _registered() -> EscalationRegistered:
    return EscalationRegistered(
        escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="FRAUD_SUSPECTED"
    )


def _banking() -> FakeBankingTools:
    return (
        FakeBankingTools()
        .respond("block_card", _blocked())
        .respond("escalate", _registered())
        .respond("open_dispute", _opened(_tx()))
    )


def _setup(
    banking: FakeBankingTools,
    transactions: tuple[DisputedTransaction, ...] = (),
    cards: tuple[KnownCard, ...] = (_CARD_1,),
    verified: bool = True,
) -> tuple[FraudActions, Conversation, FakeAgentAuditLog]:
    audit = FakeAgentAuditLog()
    clock = FixedAgentClock(_NOW)
    escalation = EscalationService(banking, audit, clock)
    dispute_actions = DisputeActions(
        DisputePolicy(Decimal(4000)), banking, escalation, audit, clock
    )
    actions = FraudActions(banking, dispute_actions, escalation, audit, clock)
    builder = ConversationBuilder()
    conv = builder.verified("C-0001", cards).build() if verified else builder.build()
    conv.remember_transactions(transactions)
    return actions, conv, audit


def _names(banking: FakeBankingTools) -> list[str]:
    return [name for name, _ in banking.calls]


def _calls(banking: FakeBankingTools, tool: str) -> list[dict[str, object]]:
    return [args for name, args in banking.calls if name == tool]


_BLOCK_AND_DISPUTE = {PriorAction.CARD_BLOCKED, PriorAction.DISPUTE_OPENED}
_BLOCK_ONLY = {PriorAction.CARD_BLOCKED}


# Regla: RN-007-14 — El fraude solo se considera cuando el cliente declara sospecharlo; lo
# interpreta el LLM a partir del mensaje y lo indica al agente. Con identidad verificada, el
# agente invoca `bloquear_tarjeta` con `reason = FRAUD_SUSPECTED` sobre la tarjeta afectada, de
# inmediato y sin pedir confirmación. Después deriva con `FRAUD_SUSPECTED`, indicando la tarjeta
# y las acciones realizadas. Si el cliente señala transacciones de esa tarjeta, cada una se
# decide con DP-007-06 o DP-007-07.
# Regla: DP-007-06 — fraude ∧ la transacción cumple las condiciones de DP-007-05: ESCALATE
# (`FRAUD_SUSPECTED`); `bloquear_tarjeta`, `iniciar_disputa`, `escalar_a_analista` (con
# `CARD_BLOCKED` y `DISPUTE_OPENED`)
# Regla: DP-007-07 — fraude ∧ la transacción no cumple las condiciones de DP-007-05: ESCALATE
# (`FRAUD_SUSPECTED`); `bloquear_tarjeta`, `escalar_a_analista` (con `CARD_BLOCKED`)
# AC-007-09 · Art. 5
@pytest.mark.parametrize(
    ("transaction", "opens_dispute", "rule"),
    [
        (_tx(amount="85000.00"), True, "DP-007-06"),
        (_tx(amount="500000.00"), True, "DP-007-06"),
        (_tx(amount="500001.00"), False, "DP-007-07"),
        (_tx(amount="100000.00", days=91, foreign=True), False, "DP-007-07"),
        (_tx(amount="85000.00", status=TransactionStatus.PENDING), False, "DP-007-07"),
    ],
    ids=["85000", "500000", "500001", "foreign_91_days", "pending"],
)
async def test_ac_007_09_fraud_actions__declared_fraud_per_transaction(
    transaction: DisputedTransaction, opens_dispute: bool, rule: str
) -> None:
    """AC-007-09: bloquea CARD-L1 primero, abre la disputa si procede y deriva por fraude."""
    banking = _banking()
    actions, conv, _ = _setup(banking, (transaction,))

    result = await actions.report(conv, None, ["TX-L1"])

    expected = ["block_card"] + (["open_dispute"] if opens_dispute else []) + ["escalate"]
    assert _names(banking) == expected
    block = _calls(banking, "block_card")[0]
    assert block["card_id"] == "CARD-L1"
    assert block["reason"] == "FRAUD_SUSPECTED"
    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    escalation = escalations[0]
    assert escalation["reason"] is EscalationReason.FRAUD_SUSPECTED
    assert escalation["transaction_id"] == "TX-L1"
    assert escalation["card_id"] == "CARD-L1"
    prior = set(escalation["prior_actions"])  # type: ignore[call-overload]
    assert prior == (_BLOCK_AND_DISPUTE if opens_dispute else _BLOCK_ONLY)
    if opens_dispute:
        assert escalation["dispute_id"] == "D-0001"
    assert result.needs_card_digits is False
    assert result.outcomes[0].kind is OutcomeKind.CARD_BLOCKED
    assert result.outcomes[-1].kind is OutcomeKind.ESCALATED
    assert result.outcomes[-1].rule == rule
    kinds = [o.kind for o in result.outcomes]
    assert (OutcomeKind.DISPUTE_OPENED in kinds) is opens_dispute
    assert conv.status is ConversationStatus.ACTIVE


# Regla: RN-007-14 — El fraude solo se considera cuando el cliente declara sospecharlo; lo
# interpreta el LLM a partir del mensaje y lo indica al agente. Con identidad verificada, el
# agente invoca `bloquear_tarjeta` con `reason = FRAUD_SUSPECTED` sobre la tarjeta afectada, de
# inmediato y sin pedir confirmación. Después deriva con `FRAUD_SUSPECTED`, indicando la tarjeta
# y las acciones realizadas. Si el cliente señala transacciones de esa tarjeta, cada una se
# decide con DP-007-06 o DP-007-07.
# Regla: RN-007-15 — La tarjeta afectada es la de la transacción señalada (`card_id` de
# `TransactionItem`) o, si no se señala ninguna, la tarjeta del cliente cuyos últimos 4 dígitos
# indica, tomada del campo `cards` de `buscar_cliente` (§7). Si el cliente tiene una sola
# tarjeta, es esa. Si no se puede determinar una única tarjeta (el cliente no indica los dígitos
# o varias tarjetas suyas terminan igual), el agente pide los últimos 4 dígitos una vez. Si
# sigue sin poder determinarla, deriva con `FRAUD_SUSPECTED` **sin bloquear** (Art. 10: no
# actuar en la duda).
# AC-007-10 · Art. 5
async def test_ac_007_10_fraud_actions__card_resolution() -> None:
    """AC-007-10: tarjeta por dígitos, única, sin dígitos o ambigua."""
    # Fila 1: una tarjeta, sin decir los dígitos.
    banking = _banking()
    actions, conv, _ = _setup(banking, cards=(_CARD_1,))
    result = await actions.report(conv, None, None)
    assert _names(banking) == ["block_card", "escalate"]
    assert _calls(banking, "block_card")[0]["card_id"] == "CARD-L1"
    escalation = _calls(banking, "escalate")[0]
    assert escalation["reason"] is EscalationReason.FRAUD_SUSPECTED
    assert escalation["card_id"] == "CARD-L1"
    assert escalation["prior_actions"] == (PriorAction.CARD_BLOCKED,)
    assert escalation["transaction_id"] is None
    assert [o.kind for o in result.outcomes] == [OutcomeKind.CARD_BLOCKED, OutcomeKind.ESCALATED]

    # Fila 2: dos tarjetas, con los dígitos de CARD-L2.
    banking = _banking()
    actions, conv, _ = _setup(banking, cards=(_CARD_1, _CARD_2))
    await actions.report(conv, "8765", None)
    assert [a["card_id"] for a in _calls(banking, "block_card")] == ["CARD-L2"]
    assert _calls(banking, "escalate")[0]["card_id"] == "CARD-L2"

    # Fila 3: dos tarjetas sin dígitos: se piden y no se escribe nada.
    banking = _banking()
    actions, conv, _ = _setup(banking, cards=(_CARD_1, _CARD_2))
    result = await actions.report(conv, None, None)
    assert result.needs_card_digits is True
    assert result.outcomes == ()
    assert banking.calls == []
    assert conv.card_digits_requested is True

    # Ruta: sin dígitos por segunda vez, se deriva sin bloquear.
    result = await actions.report(conv, None, None)
    assert result.needs_card_digits is False
    assert _names(banking) == ["escalate"]
    escalation = _calls(banking, "escalate")[0]
    assert escalation["reason"] is EscalationReason.FRAUD_SUSPECTED
    assert escalation["card_id"] is None
    assert escalation["prior_actions"] == ()
    assert [o.kind for o in result.outcomes] == [OutcomeKind.ESCALATED]

    # Fila 4: dos tarjetas con los mismos 4 dígitos: se deriva sin bloquear.
    banking = _banking()
    actions, conv, _ = _setup(banking, cards=(_CARD_1, _CARD_3))
    result = await actions.report(conv, None, None)
    assert result.needs_card_digits is True
    assert banking.calls == []
    result = await actions.report(conv, "4321", None)
    assert result.needs_card_digits is False
    assert _names(banking) == ["escalate"]
    escalation = _calls(banking, "escalate")[0]
    assert escalation["reason"] is EscalationReason.FRAUD_SUSPECTED
    assert escalation["card_id"] is None
    assert escalation["prior_actions"] == ()
    assert conv.status is ConversationStatus.ACTIVE


# Regla: RN-007-16 — Si `bloquear_tarjeta` responde `already_blocked = true`, el agente informa al
# cliente que la tarjeta ya estaba bloqueada y deriva igualmente con `FRAUD_SUSPECTED` y
# `prior_actions = ["CARD_BLOCKED"]`. Si responde `CARD_NOT_BLOCKABLE` (tarjeta cancelada),
# informa que la tarjeta está cancelada y deriva con `FRAUD_SUSPECTED` sin `CARD_BLOCKED`.
# AC-007-19 · Art. 5
@pytest.mark.parametrize(
    ("response", "kind", "prior"),
    [
        (_blocked(already=True), OutcomeKind.CARD_ALREADY_BLOCKED, (PriorAction.CARD_BLOCKED,)),
        (
            BankingToolError("CARD_NOT_BLOCKABLE", "tarjeta cancelada", False),
            OutcomeKind.CARD_NOT_BLOCKABLE,
            (),
        ),
    ],
    ids=["already_blocked", "not_blockable"],
)
async def test_ac_007_19_fraud_actions__already_blocked_or_cancelled(
    response: object, kind: OutcomeKind, prior: tuple[PriorAction, ...]
) -> None:
    """AC-007-19: informa el estado de la tarjeta y deriva con FRAUD_SUSPECTED."""
    banking = _banking().respond("block_card", response)
    actions, conv, _ = _setup(banking)

    result = await actions.report(conv, "4321", None)

    assert _names(banking) == ["block_card", "escalate"]
    assert result.outcomes[0].kind is kind
    assert result.outcomes[0].rule == "RN-007-16"
    assert result.outcomes[0].reason == messages.OUTCOME_REASONS[kind]
    assert result.outcomes[0].next_steps == messages.OUTCOME_NEXT_STEPS[kind]
    escalation = _calls(banking, "escalate")[0]
    assert escalation["reason"] is EscalationReason.FRAUD_SUSPECTED
    assert escalation["card_id"] == "CARD-L1"
    assert escalation["prior_actions"] == prior
    assert result.outcomes[-1].kind is OutcomeKind.ESCALATED


# Regla: RN-007-21 — Si `consultar_transacciones`, `iniciar_disputa` o `bloquear_tarjeta`
# devuelven `INTERNAL`, no responden dentro del tiempo límite o devuelven una respuesta que no
# cumple su esquema, el agente no da la acción por realizada. Deriva con
# `UNRECOVERABLE_SYSTEM_FAILURE`, con la transacción o la tarjeta afectada si la identidad está
# verificada, informa al cliente sin detalles técnicos y cierra la conversación. Solo se
# reintenta un error con `retryable = true`.
# AC-007-23 · Art. 5
@pytest.mark.parametrize(
    "error",
    [
        BankingToolError("INTERNAL", "detalle interno", False),
        BankingToolUnavailableError("tiempo límite"),
    ],
    ids=["internal", "unavailable"],
)
async def test_ac_007_23_fraud_actions__block_failure(error: Exception) -> None:
    """AC-007-23 (fila de bloquear_tarjeta): deriva por falla del sistema y cierra."""
    banking = _banking().respond("block_card", error)
    actions, conv, audit = _setup(banking, (_tx(),))

    result = await actions.report(conv, None, ["TX-L1"])

    assert _names(banking) == ["block_card", "escalate"]
    assert OutcomeKind.CARD_BLOCKED not in [o.kind for o in result.outcomes]
    escalation = _calls(banking, "escalate")[0]
    assert escalation["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    assert escalation["card_id"] == "CARD-L1"
    assert PriorAction.CARD_BLOCKED not in escalation["prior_actions"]  # type: ignore[operator]
    note = str(escalation["note"])
    assert "bloquear_tarjeta" in note
    assert "detalle interno" not in note
    assert conv.status is ConversationStatus.ESCALATED
    assert any(
        e.event_type == "conversation_closed" and e.rule == "RN-007-21" for e in audit.events
    )


# Soporte de tests: una tarjeta se bloquea una sola vez por conversación · Art. 3
async def test_fraud_actions__same_card_several_transactions__blocks_once() -> None:
    banking = _banking()
    txs = (_tx("TX-L1"), _tx("TX-L2", amount="800000.00"))
    actions, conv, _ = _setup(banking, txs)

    result = await actions.report(conv, None, ["TX-L1", "TX-L2"])

    assert len(_calls(banking, "block_card")) == 1
    assert len(_calls(banking, "escalate")) == 2
    assert _names(banking)[0] == "block_card"
    assert [o.kind for o in result.outcomes].count(OutcomeKind.CARD_BLOCKED) == 1
    assert conv.blocked_cards == {"CARD-L1"}


# Soporte de tests: cada tarjeta distinta se bloquea una vez · Art. 3
async def test_fraud_actions__different_cards__blocks_each_once() -> None:
    banking = _banking().respond("block_card", _blocked(), _blocked(card_id="CARD-L2"))
    txs = (_tx("TX-L1"), _tx("TX-L2", card_id="CARD-L2", amount="800000.00"))
    actions, conv, _ = _setup(banking, txs, cards=(_CARD_1, _CARD_2))

    await actions.report(conv, None, ["TX-L1", "TX-L2"])

    assert [a["card_id"] for a in _calls(banking, "block_card")] == ["CARD-L1", "CARD-L2"]
    assert _names(banking)[:2] == ["block_card", "block_card"]
    assert conv.blocked_cards == {"CARD-L1", "CARD-L2"}


# Soporte de tests: sin identidad verificada no se bloquea (RN-007-17) · Art. 3
async def test_fraud_actions__not_verified__escalates_limited_and_closes() -> None:
    banking = _banking()
    actions, conv, audit = _setup(banking, verified=False)

    result = await actions.report(conv, "4321", None)

    assert _names(banking) == ["escalate"]
    escalation = _calls(banking, "escalate")[0]
    assert escalation["reason"] is EscalationReason.FRAUD_SUSPECTED
    assert escalation["transaction_id"] is None
    assert escalation["card_id"] is None
    assert escalation["prior_actions"] == ()
    assert str(escalation["note"]).startswith("RN-007-17")
    assert [o.kind for o in result.outcomes] == [OutcomeKind.ESCALATED]
    assert result.outcomes[0].rule == "RN-007-17"
    assert conv.status is ConversationStatus.ESCALATED
    assert any(e.event_type == "conversation_closed" for e in audit.events)


# Soporte de tests: la nota humana viaja en la derivación sin transacciones · Art. 3
async def test_fraud_actions__human_note__propagates_to_escalation() -> None:
    banking = _banking()
    actions, conv, _ = _setup(banking)

    await actions.report(conv, None, None, human_note=messages.HUMAN_REQUEST_NOTE)

    assert _calls(banking, "escalate")[0]["note"] == messages.HUMAN_REQUEST_NOTE


# Soporte de tests: auditoría del bloqueo con RN-007-14 · Art. 3
async def test_fraud_actions__block_card__audits_tool_call() -> None:
    banking = _banking()
    actions, conv, audit = _setup(banking)

    await actions.report(conv, None, None)

    events = [e for e in audit.events if e.event_type == "tool_call"]
    assert [(e.tool, e.rule) for e in events] == [("bloquear_tarjeta", "RN-007-14")]
    assert events[0].input is not None
    assert events[0].input["card_id"] == "CARD-L1"
