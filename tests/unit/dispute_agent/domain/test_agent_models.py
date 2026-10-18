"""Value objects del dominio del agente (T-007-05): transacción, decisión, resultado y textos."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from dispute_agent.domain import messages
from dispute_agent.domain.errors import (
    DomainError,
    InvalidDecisionError,
    InvalidOutcomeError,
    InvalidTransactionDataError,
)
from dispute_agent.domain.models.decision import (
    AgentAction,
    Decision,
    DisputeDecision,
    EscalationReason,
    PriorAction,
)
from dispute_agent.domain.models.outcome import Outcome, OutcomeKind
from dispute_agent.domain.models.transaction import DisputedTransaction, TransactionStatus

BOGOTA = timezone(timedelta(hours=-5))


def _tx(**overrides: Any) -> DisputedTransaction:
    data: dict[str, Any] = {
        "transaction_id": "TX-L1",
        "card_id": "CARD-L1",
        "masked_card": "**** 4321",
        "occurred_at": datetime(2026, 10, 10, 12, 0, tzinfo=BOGOTA),
        "merchant": "Tienda Ficticia",
        "amount": Decimal("85000.00"),
        "currency": "COP",
        "merchant_country": "CO",
        "status": TransactionStatus.CONFIRMED,
    }
    data.update(overrides)
    return DisputedTransaction(**data)


# Soporte de tests: vista de dominio inmutable de la transacción · Art. 3
# Invariante: Art. 4 — el dominio no depende de infraestructura y sus modelos son inmutables
def test_disputed_transaction_accepts_valid_data() -> None:
    """La vista del dominio de una transacción válida se construye y es inmutable."""
    tx = _tx()
    assert tx.amount == Decimal("85000.00")
    with pytest.raises(FrozenInstanceError):
        tx.currency = "USD"  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"occurred_at": datetime(2026, 10, 10, 12, 0)},
        {"amount": Decimal("0")},
        {"amount": Decimal("-1.00")},
        {"amount": Decimal("10.001")},
        {"currency": "cop"},
        {"currency": "CO"},
        {"currency": ""},
        {"merchant_country": "co"},
        {"merchant_country": "COL"},
        {"merchant_country": ""},
    ],
)
# Soporte de tests: invariantes de DisputedTransaction · Art. 3
def test_disputed_transaction_rejects_invalid_data(overrides: dict[str, Any]) -> None:
    """Plan §4: invariantes de DisputedTransaction."""
    with pytest.raises(InvalidTransactionDataError):
        _tx(**overrides)


def test_invalid_transaction_error_is_domain_error() -> None:
    """Plan §2: los errores del dominio comparten la base DomainError."""
    assert issubclass(InvalidTransactionDataError, DomainError)


def test_transaction_status_values() -> None:
    """Plan §4: estados de una transacción del core."""
    assert {s.value for s in TransactionStatus} == {"PENDING", "CONFIRMED", "REVERSED"}


def test_escalation_enums_match_rn_006() -> None:
    """RN-006-02 y RN-006-05: motivos cerrados y orden canónico de acciones previas."""
    assert {r.value for r in EscalationReason} == {
        "FRAUD_SUSPECTED",
        "AMOUNT_OVER_THRESHOLD",
        "INSUFFICIENT_OR_CONTRADICTORY_INFO",
        "INCONCLUSIVE_RULES",
        "UNRECOVERABLE_SYSTEM_FAILURE",
        "IDENTITY_VERIFICATION_FAILED",
        "OTHER",
    }
    assert [p.value for p in PriorAction] == ["DISPUTE_OPENED", "CARD_BLOCKED"]
    assert {d.value for d in Decision} == {"RESOLVE", "REJECT", "ESCALATE"}
    assert {a.name for a in AgentAction} == {"OPEN_DISPUTE", "BLOCK_CARD", "ESCALATE"}


def _decision(**overrides: Any) -> DisputeDecision:
    data: dict[str, Any] = {
        "decision": Decision.RESOLVE,
        "rule": "DP-007-05",
        "escalation_reason": None,
        "allowed_actions": frozenset({AgentAction.OPEN_DISPUTE}),
        "customer_reason": "motivo",
        "next_steps": "pasos",
    }
    data.update(overrides)
    return DisputeDecision(**data)


def test_dispute_decision_accepts_valid_combinations() -> None:
    """Plan §4: combinaciones válidas de DisputeDecision."""
    assert _decision().decision is Decision.RESOLVE
    assert _decision(decision=Decision.REJECT, allowed_actions=frozenset()).allowed_actions == set()
    escalate = _decision(
        decision=Decision.ESCALATE,
        escalation_reason=EscalationReason.AMOUNT_OVER_THRESHOLD,
        allowed_actions=frozenset({AgentAction.ESCALATE}),
    )
    assert escalate.escalation_reason is EscalationReason.AMOUNT_OVER_THRESHOLD


@pytest.mark.parametrize(
    "overrides",
    [
        {"escalation_reason": EscalationReason.OTHER},
        {"allowed_actions": frozenset()},
        {"allowed_actions": frozenset({AgentAction.OPEN_DISPUTE, AgentAction.ESCALATE})},
        {"decision": Decision.REJECT},
        {"decision": Decision.ESCALATE, "allowed_actions": frozenset({AgentAction.ESCALATE})},
        {
            "decision": Decision.REJECT,
            "allowed_actions": frozenset(),
            "escalation_reason": EscalationReason.OTHER,
        },
    ],
)
def test_dispute_decision_rejects_invariant_violations(overrides: dict[str, Any]) -> None:
    """Plan §4: ESCALATE <=> motivo; RESOLVE => {OPEN_DISPUTE}; REJECT => vacío."""
    with pytest.raises(InvalidDecisionError):
        _decision(**overrides)


def test_outcome_requires_reason_and_next_steps() -> None:
    """Plan §4: Outcome exige reason y next_steps no vacíos (RN-007-25)."""
    ok = Outcome(kind=OutcomeKind.DISPUTE_OPENED, rule="DP-007-05", reason="r", next_steps="n")
    assert ok.transaction_id is None and ok.masked_card is None and ok.reference is None
    for reason, steps in (("", "n"), ("r", ""), ("  ", "n"), ("r", " ")):
        with pytest.raises(InvalidOutcomeError):
            Outcome(kind=OutcomeKind.ESCALATED, rule="RN-007-18", reason=reason, next_steps=steps)


def test_outcome_kinds_cover_spec_7_3() -> None:
    """Spec §7.3: tipos distintos de Outcome (ESCALATED se repite con y sin transacción)."""
    assert {k.value for k in OutcomeKind} == {
        "DISPUTE_OPENED",
        "NOT_DISPUTABLE",
        "ESCALATED",
        "CARD_BLOCKED",
        "CARD_ALREADY_BLOCKED",
        "CARD_NOT_BLOCKABLE",
        "DISPUTE_ALREADY_OPEN",
        "NO_TRANSACTIONS_FOUND",
        "REFINEMENT_REQUIRED",
        "ITERATION_LIMIT",
        "LLM_FAILURE",
        "ESCALATION_FAILED",
    }


def test_messages_dp_texts_match_spec_5() -> None:
    """RN-007-25: textos fijos de spec §5 para DP-007-01..07."""
    assert set(messages.DP_REASONS) == {f"DP-007-0{n}" for n in range(1, 8)}
    assert set(messages.DP_NEXT_STEPS) == set(messages.DP_REASONS)
    assert messages.DP_REASONS["DP-007-03"] == (
        "El monto supera el límite para abrir disputas automáticamente."
    )
    assert messages.DP_NEXT_STEPS["DP-007-05"] == (
        "Tu disputa quedó abierta; el banco la gestionará y te informará el resultado."
    )
    assert messages.DP_REASONS["DP-007-07"] == (
        "Por la sospecha de fraude bloqueamos tu tarjeta; este cobro lo revisará un analista."
    )


def test_messages_outcome_texts_match_spec_7_3() -> None:
    """RN-007-25: textos fijos de spec §7.3 para cada OutcomeKind sin texto de §5."""
    for kind in OutcomeKind:
        if kind in (
            OutcomeKind.DISPUTE_OPENED,
            OutcomeKind.NOT_DISPUTABLE,
        ):
            continue
        assert messages.OUTCOME_REASONS[kind].strip()
        assert messages.OUTCOME_NEXT_STEPS[kind].strip()
    assert messages.OUTCOME_REASONS[OutcomeKind.CARD_BLOCKED] == (
        "Bloqueamos tu tarjeta por la sospecha de fraude que reportaste."
    )
    assert messages.OUTCOME_REASONS[OutcomeKind.LLM_FAILURE] == (
        "Tuvimos un problema al procesar tu solicitud."
    )
    assert messages.OUTCOME_NEXT_STEPS[OutcomeKind.ESCALATION_FAILED] == (
        "Por favor, vuelve a contactar al banco más tarde."
    )
    assert messages.ESCALATED_NO_TX_REASON == "Tu caso requiere la revisión de una persona."
    assert messages.ESCALATED_NO_TX_NEXT_STEPS == "Una persona continuará la atención."
    assert messages.CONVERSATION_CLOSED_MESSAGE == (
        "Tu caso ya fue derivado a un analista. Una persona continuará la atención."
    )
    assert messages.HUMAN_REQUEST_NOTE == "Cliente solicitó atención humana"


def test_decision_and_outcome_are_immutable() -> None:
    """Plan §4: value objects inmutables."""
    with pytest.raises(FrozenInstanceError):
        _decision().rule = "X"  # type: ignore[misc]
