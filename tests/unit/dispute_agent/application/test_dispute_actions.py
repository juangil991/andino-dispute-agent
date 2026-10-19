"""Tests de DisputeActions (spec 007: AC-007-01, 03, 05, 17, 18, 23; DP-007-01…07)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.banking_errors import invalid_input
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fixed_agent_clock import FixedAgentClock

from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolUnavailableError,
    DisputeOpened,
    EscalationRegistered,
)
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.domain import messages
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus
from dispute_agent.domain.models.decision import EscalationReason, PriorAction
from dispute_agent.domain.models.outcome import OutcomeKind
from dispute_agent.domain.models.transaction import DisputedTransaction, TransactionStatus
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_TODAY = _NOW.date()


def _tx(
    tx_id: str = "TX-L1",
    amount: str = "85000.00",
    currency: str = "COP",
    status: TransactionStatus = TransactionStatus.CONFIRMED,
) -> DisputedTransaction:
    return (
        DisputedTransactionBuilder()
        .transaction_id(tx_id)
        .card("CARD-L1", "**** 4321")
        .national()
        .amount(amount, currency)
        .status(status)
        .days_ago(7, _TODAY)
        .build()
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
        escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="X"
    )


def _setup(
    banking: FakeBankingTools, tx: DisputedTransaction
) -> tuple[DisputeActions, Conversation, FakeAgentAuditLog]:
    audit = FakeAgentAuditLog()
    clock = FixedAgentClock(_NOW)
    escalation = EscalationService(banking, audit, clock)
    actions = DisputeActions(DisputePolicy(Decimal(4000)), banking, escalation, audit, clock)
    conv = ConversationBuilder().verified("C-0001").build()
    conv.remember_transactions([tx])
    return actions, conv, audit


def _names(banking: FakeBankingTools) -> list[str]:
    return [name for name, _ in banking.calls]


# Regla: DP-007-05 — ¬fraude ∧ CONFIRMED ∧ monto equivalente ≤ 500.000 COP ∧
# (comercio nacional ∨ antigüedad ≤ 90 días) → RESOLVE
# Regla: RN-007-06 — decisión determinista por transacción
# AC-007-01 · Art. 5
async def test_ac_007_01_dispute_actions__low_amount__opens_dispute() -> None:
    """AC-007-01: 85.000 COP nacional abre la disputa sin derivar."""
    tx = _tx()
    banking = FakeBankingTools().respond("open_dispute", _opened(tx))
    actions, conv, audit = _setup(banking, tx)

    outcomes = await actions.evaluate(conv, "TX-L1")

    assert _names(banking) == ["open_dispute"]
    args = banking.calls[0][1]
    assert args["transaction_id"] == "TX-L1"
    assert args["reason"] == "UNRECOGNIZED_CHARGE"
    assert str(args["idempotency_key"]).startswith("dispute-")
    assert len(outcomes) == 1
    assert outcomes[0].kind is OutcomeKind.DISPUTE_OPENED
    assert outcomes[0].rule == "DP-007-05"
    assert outcomes[0].reference == "D-0001"
    assert outcomes[0].reason == messages.DP_REASONS["DP-007-05"]
    assert conv.decisions["TX-L1"].rule == "DP-007-05"
    decisions = [e for e in audit.events if e.event_type == "decision"]
    assert [e.rule for e in decisions] == ["DP-007-05"]


# Regla: DP-007-03 — monto equivalente > 500.000 COP: escalar
# AC-007-03 · Art. 5
async def test_ac_007_03_dispute_actions__over_threshold__escalates() -> None:
    """AC-007-03 (fila 500.001): no abre disputa y deriva por monto."""
    tx = _tx(amount="500001.00")
    banking = FakeBankingTools().respond("escalate", _registered())
    actions, conv, audit = _setup(banking, tx)

    outcomes = await actions.evaluate(conv, "TX-L1")

    assert _names(banking) == ["escalate"]
    assert banking.calls[0][1]["reason"] is EscalationReason.AMOUNT_OVER_THRESHOLD
    assert [o.kind for o in outcomes] == [OutcomeKind.ESCALATED]
    assert outcomes[0].rule == "DP-007-03"
    assert [e.rule for e in audit.events if e.event_type == "decision"] == ["DP-007-03"]


# Regla: DP-007-02 — ¬fraude ∧ CONFIRMED ∧ currency ∉ {COP, USD} →
# ESCALATE (INCONCLUSIVE_RULES) con escalar_a_analista
# AC-007-03 · Art. 10
async def test_ac_007_03_dispute_actions__unsupported_currency__escalates_inconclusive_rules() -> (
    None
):
    """AC-007-03 (fila 10.00 EUR): deriva con INCONCLUSIVE_RULES y la nota de DP-007-02."""
    tx = _tx(amount="10.00", currency="EUR")
    banking = FakeBankingTools().respond("escalate", _registered())
    actions, conv, _ = _setup(banking, tx)

    outcomes = await actions.evaluate(conv, "TX-L1")

    assert _names(banking) == ["escalate"]
    args = banking.calls[0][1]
    assert args["reason"] is EscalationReason.INCONCLUSIVE_RULES
    assert args["transaction_id"] == "TX-L1"
    assert args["card_id"] == "CARD-L1"
    assert args["prior_actions"] == ()
    assert str(args["note"]).startswith("DP-007-02:")
    assert outcomes[0].rule == "DP-007-02"
    assert outcomes[0].reason == messages.DP_REASONS["DP-007-02"]
    assert outcomes[0].next_steps == messages.DP_NEXT_STEPS["DP-007-02"]


# Regla: DP-007-04 — ¬fraude ∧ CONFIRMED ∧ monto equivalente ≤ 500.000 COP ∧
# comercio del exterior ∧ antigüedad > 90 días → ESCALATE (INCONCLUSIVE_RULES)
# AC-007-06 · Art. 10
async def test_ac_007_06_dispute_actions__foreign_over_90_days__escalates_inconclusive_rules() -> (
    None
):
    """AC-007-06 (91 días, exterior): deriva con INCONCLUSIVE_RULES y la nota de DP-007-04."""
    tx = (
        DisputedTransactionBuilder()
        .transaction_id("TX-L1")
        .card("CARD-L1", "**** 4321")
        .foreign()
        .amount("100000.00", "COP")
        .status(TransactionStatus.CONFIRMED)
        .days_ago(91, _TODAY)
        .build()
    )
    banking = FakeBankingTools().respond("escalate", _registered())
    actions, conv, _ = _setup(banking, tx)

    outcomes = await actions.evaluate(conv, "TX-L1")

    assert _names(banking) == ["escalate"]
    args = banking.calls[0][1]
    assert args["reason"] is EscalationReason.INCONCLUSIVE_RULES
    assert args["transaction_id"] == "TX-L1"
    assert args["card_id"] == "CARD-L1"
    assert args["prior_actions"] == ()
    assert str(args["note"]).startswith("DP-007-04:")
    assert outcomes[0].rule == "DP-007-04"
    assert outcomes[0].reason == messages.DP_REASONS["DP-007-04"]
    assert outcomes[0].next_steps == messages.DP_NEXT_STEPS["DP-007-04"]


# Regla: DP-007-03 — monto equivalente > 500.000 COP: escalar
# AC-007-05 · Art. 5
async def test_ac_007_05_dispute_actions__escalation_payload() -> None:
    """AC-007-05: la derivación lleva la transacción, la tarjeta y la nota de la regla."""
    tx = _tx(tx_id="TX-L2", amount="800000.00")
    banking = FakeBankingTools().respond("escalate", _registered())
    actions, conv, _ = _setup(banking, tx)

    await actions.evaluate(conv, "TX-L2")

    args = banking.calls[0][1]
    assert args["transaction_id"] == "TX-L2"
    assert args["card_id"] == "CARD-L1"
    assert args["prior_actions"] == ()
    assert str(args["note"]).startswith("DP-007-03:")


# Regla: DP-007-01 — transacción no confirmada: rechazar
# AC-007-17 · Art. 5
@pytest.mark.parametrize(
    "status",
    [TransactionStatus.PENDING, TransactionStatus.REVERSED],
    ids=["pending", "reversed"],
)
async def test_ac_007_17_dispute_actions__not_disputable(status: TransactionStatus) -> None:
    """AC-007-17: PENDING y REVERSED dan NOT_DISPUTABLE sin escrituras."""
    tx = _tx(status=status)
    banking = FakeBankingTools()
    actions, conv, audit = _setup(banking, tx)

    outcomes = await actions.evaluate(conv, "TX-L1")

    assert banking.calls == []
    assert [o.kind for o in outcomes] == [OutcomeKind.NOT_DISPUTABLE]
    assert outcomes[0].rule == "DP-007-01"
    assert outcomes[0].reason == messages.DP_REASONS["DP-007-01"]
    assert outcomes[0].next_steps == messages.DP_NEXT_STEPS["DP-007-01"]
    assert conv.status is ConversationStatus.ACTIVE
    assert [e.rule for e in audit.events if e.event_type == "decision"] == ["DP-007-01"]


# Regla: RN-007-12 — disputa ya abierta: informar sin derivar
# AC-007-18 · Art. 5
async def test_ac_007_18_dispute_actions__dispute_already_open() -> None:
    """AC-007-18: DISPUTE_ALREADY_OPEN informa la disputa previa sin derivar."""
    tx = _tx()
    error = BankingToolError(
        "DISPUTE_ALREADY_OPEN", "Ya existe una disputa abierta: D-OLD.", False, "D-OLD"
    )
    banking = FakeBankingTools().respond("open_dispute", error)
    actions, conv, _ = _setup(banking, tx)

    outcomes = await actions.evaluate(conv, "TX-L1")

    assert _names(banking) == ["open_dispute"]
    assert [o.kind for o in outcomes] == [OutcomeKind.DISPUTE_ALREADY_OPEN]
    assert outcomes[0].reference == "D-OLD"
    assert outcomes[0].rule == "RN-007-12"
    assert outcomes[0].reason == messages.OUTCOME_REASONS[OutcomeKind.DISPUTE_ALREADY_OPEN]
    assert outcomes[0].next_steps == messages.OUTCOME_NEXT_STEPS[OutcomeKind.DISPUTE_ALREADY_OPEN]
    assert conv.status is ConversationStatus.ACTIVE


# Regla: RN-007-21 — falla irrecuperable de una herramienta: derivar y cerrar
# AC-007-23 · Art. 5
@pytest.mark.parametrize(
    "error",
    [
        BankingToolError("INTERNAL", "detalle interno", False),
        BankingToolUnavailableError("tiempo límite"),
        BankingToolUnavailableError("salida inválida"),
    ],
    ids=["internal", "timeout", "invalid_output"],
)
async def test_ac_007_23_dispute_actions__open_dispute_failure(error: Exception) -> None:
    """AC-007-23: falla en iniciar_disputa deriva por falla del sistema y cierra."""
    tx = _tx()
    banking = FakeBankingTools().respond("open_dispute", error).respond("escalate", _registered())
    actions, conv, audit = _setup(banking, tx)

    outcomes = await actions.evaluate(conv, "TX-L1")

    assert _names(banking) == ["open_dispute", "escalate"]
    assert OutcomeKind.DISPUTE_OPENED not in [o.kind for o in outcomes]
    args = banking.calls[1][1]
    assert args["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    assert args["transaction_id"] == "TX-L1"
    note = str(args["note"])
    assert "iniciar_disputa" in note
    assert "detalle interno" not in note
    assert conv.status is ConversationStatus.ESCALATED
    assert any(
        e.event_type == "conversation_closed" and e.rule == "RN-007-21" for e in audit.events
    )


# Regla: RN-010-08 — la falla irrecuperable por entrada inválida nombra el campo
# AC-010-10, AC-010-11 · Art. 10
async def test_ac_010_10_open_dispute__invalid_input_with_field__audits_field_and_still_escalates() -> (  # noqa: E501
    None
):
    """AC-010-10/11: INVALID_INPUT con campo se audita, consta en la nota y deriva y cierra."""
    tx = _tx()
    banking = (
        FakeBankingTools()
        .respond("open_dispute", invalid_input("transaction_id"))
        .respond("escalate", _registered())
    )
    actions, conv, audit = _setup(banking, tx)

    await actions.evaluate(conv, "TX-L1")

    call = next(e for e in audit.events if e.event_type == "tool_call")
    assert call.output == {"error": "INVALID_INPUT", "field": "transaction_id"}
    assert call.rule == "RN-007-21"
    types = [e.event_type for e in audit.events]
    assert types.index("tool_call") < types.index("escalation") < types.index("conversation_closed")
    args = banking.calls[1][1]
    assert args["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    assert args["note"] == (
        "RN-007-21: falla irrecuperable en iniciar_disputa (INVALID_INPUT, campo: transaction_id)"
    )
    closed = next(e for e in audit.events if e.event_type == "conversation_closed")
    assert (
        closed.reason
        == "falla irrecuperable en iniciar_disputa (INVALID_INPUT, campo: transaction_id)"
    )
    assert conv.status is ConversationStatus.ESCALATED


# Regla: RN-010-08 — el tool_call de la falla lleva la regla RN-007-21
# AC-010-10 · Art. 8
async def test_ac_010_10_open_dispute__timeout__audits_tool_call_with_failure_rule() -> None:
    """AC-010-10: el tiempo límite se audita con salida UNAVAILABLE y regla RN-007-21."""
    tx = _tx()
    banking = (
        FakeBankingTools()
        .respond("open_dispute", BankingToolUnavailableError("tiempo límite"))
        .respond("escalate", _registered())
    )
    actions, conv, audit = _setup(banking, tx)

    await actions.evaluate(conv, "TX-L1")

    call = next(e for e in audit.events if e.event_type == "tool_call")
    assert call.output == {"error": "UNAVAILABLE"}
    assert call.rule == "RN-007-21"


# Regla: RN-010-08 — éxito y DISPUTE_ALREADY_OPEN conservan la regla de la decisión
# AC-010-10 · Art. 8
async def test_ac_010_10_open_dispute__success_and_already_open__keeps_decision_rule() -> None:
    """AC-010-10: solo la falla cambia la regla; éxito y ya abierta usan la de la decisión."""
    tx = _tx()
    ok_actions, ok_conv, ok_audit = _setup(
        FakeBankingTools().respond("open_dispute", _opened(tx)), tx
    )
    await ok_actions.evaluate(ok_conv, "TX-L1")
    error = BankingToolError("DISPUTE_ALREADY_OPEN", "Ya existe: D-OLD.", False, "D-OLD")
    dup_banking = FakeBankingTools().respond("open_dispute", error)
    dup_actions, dup_conv, dup_audit = _setup(dup_banking, tx)
    await dup_actions.evaluate(dup_conv, "TX-L1")

    for audit in (ok_audit, dup_audit):
        call = next(e for e in audit.events if e.event_type == "tool_call")
        assert call.rule != "RN-007-21"
        assert call.rule.startswith("DP-007-")


# Regla: DP-007-06 — fraude con transacción disputable: disputa y derivación
# AC-007-09 · Art. 5
async def test_dispute_actions__fraud_resolvable__opens_then_escalates_with_prior_actions() -> None:
    """DP-007-06: abre la disputa y deriva con prior_actions y dispute_id."""
    tx = _tx()
    banking = (
        FakeBankingTools().respond("open_dispute", _opened(tx)).respond("escalate", _registered())
    )
    actions, conv, _ = _setup(banking, tx)

    outcomes = await actions.evaluate(conv, "TX-L1", fraud=True, prior_block=True)

    assert _names(banking) == ["open_dispute", "escalate"]
    args = banking.calls[1][1]
    assert set(args["prior_actions"]) == {PriorAction.CARD_BLOCKED, PriorAction.DISPUTE_OPENED}  # type: ignore[call-overload]
    assert args["dispute_id"] == "D-0001"
    assert [(o.kind, o.rule) for o in outcomes] == [
        (OutcomeKind.DISPUTE_OPENED, "DP-007-06"),
        (OutcomeKind.ESCALATED, "DP-007-06"),
    ]


@pytest.mark.parametrize("prior_block", [False, True], ids=["no_block", "with_block"])
async def test_dispute_actions__fraud_with_dispute_already_open__escalates_with_existing_id(
    prior_block: bool,
) -> None:
    """RN-007-12 en DP-007-06: deriva con dispute_id existente y DISPUTE_OPENED (spec 007 §5)."""
    tx = _tx()
    error = BankingToolError("DISPUTE_ALREADY_OPEN", "abierta: D-OLD.", False, "D-OLD")
    banking = FakeBankingTools().respond("open_dispute", error).respond("escalate", _registered())
    actions, conv, _ = _setup(banking, tx)

    outcomes = await actions.evaluate(conv, "TX-L1", fraud=True, prior_block=prior_block)

    args = banking.calls[1][1]
    assert args["dispute_id"] == "D-OLD"
    expected = {PriorAction.DISPUTE_OPENED}
    if prior_block:
        expected.add(PriorAction.CARD_BLOCKED)
    assert set(args["prior_actions"]) == expected  # type: ignore[call-overload]
    assert [o.kind for o in outcomes] == [OutcomeKind.DISPUTE_ALREADY_OPEN, OutcomeKind.ESCALATED]


async def test_dispute_actions__transaction_not_seen__raises_value_error() -> None:
    """Precondición: la transacción debe haberse listado antes."""
    tx = _tx()
    actions, conv, _ = _setup(FakeBankingTools(), tx)

    with pytest.raises(ValueError):
        await actions.evaluate(conv, "TX-NOPE")
