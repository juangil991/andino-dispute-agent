"""Tests de EscalationService (spec 007: RN-007-20, RN-007-22, AC-007-24)."""

from datetime import UTC, datetime

from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fixed_agent_clock import FixedAgentClock

from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolUnavailableError,
    EscalationRegistered,
)
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.domain import messages
from dispute_agent.domain.models.conversation import Conversation
from dispute_agent.domain.models.decision import EscalationReason, PriorAction
from dispute_agent.domain.models.outcome import OutcomeKind

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)


def _registered() -> EscalationRegistered:
    return EscalationRegistered(
        escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="FRAUD_SUSPECTED"
    )


def _service(
    banking: FakeBankingTools,
) -> tuple[EscalationService, FakeAgentAuditLog]:
    audit = FakeAgentAuditLog()
    return EscalationService(banking, audit, FixedAgentClock(_NOW)), audit


def _verified() -> Conversation:
    return ConversationBuilder().verified("C-0001").build()


# Regla: RN-007-22 — Si `escalar_a_analista` devuelve `INTERNAL` o falla, el agente no reintenta
# automáticamente. Informa al cliente que su caso no pudo derivarse y que vuelva a contactar al
# banco, lo audita y cierra la conversación. Si devuelve `IDENTITY_NOT_VERIFIED`, repite la
# solicitud sin datos del cliente.
# AC-007-24 · Art. 10 (ante la duda, escalar)
async def test_ac_007_24_escalation_service__internal__returns_escalation_failed_without_retry() -> (  # noqa: E501
    None
):
    """AC-007-24: INTERNAL en escalar_a_analista no se reintenta y da ESCALATION_FAILED."""
    banking = FakeBankingTools().respond(
        "escalate", BankingToolError("INTERNAL", "falla", retryable=False)
    )
    service, audit = _service(banking)
    conv = _verified()

    outcome = await service.escalate(conv, EscalationReason.OTHER, "RN-007-20")

    assert len(banking.calls) == 1
    assert outcome.kind is OutcomeKind.ESCALATION_FAILED
    assert outcome.rule == "RN-007-22"
    assert outcome.reason == messages.OUTCOME_REASONS[OutcomeKind.ESCALATION_FAILED]
    assert outcome.next_steps == messages.OUTCOME_NEXT_STEPS[OutcomeKind.ESCALATION_FAILED]
    assert audit.events
    assert conv.status.value == "ACTIVE"


async def test_escalation_service__unavailable_or_unexpected__returns_failed() -> None:
    """RN-007-22: indisponibilidad o excepción inesperada no se reintenta."""
    for error in (BankingToolUnavailableError("caído"), RuntimeError("boom")):
        banking = FakeBankingTools().respond("escalate", error)
        service, _ = _service(banking)
        outcome = await service.escalate(_verified(), EscalationReason.OTHER, "RN-007-20")
        assert len(banking.calls) == 1
        assert outcome.kind is OutcomeKind.ESCALATION_FAILED


async def test_escalation_service__identity_not_verified__retries_without_customer_data() -> None:
    """RN-007-22: ante IDENTITY_NOT_VERIFIED repite sin datos del cliente."""
    banking = FakeBankingTools().respond(
        "escalate",
        BankingToolError("IDENTITY_NOT_VERIFIED", "no verificada", retryable=False),
        _registered(),
    )
    service, _ = _service(banking)
    tx = DisputedTransactionBuilder().build()

    outcome = await service.escalate(
        _verified(),
        EscalationReason.FRAUD_SUSPECTED,
        "DP-007-07",
        transaction=tx,
        prior_actions=(PriorAction.CARD_BLOCKED,),
        dispute_id="D-1",
    )

    assert len(banking.calls) == 2
    retry = banking.calls[1][1]
    assert retry["transaction_id"] is None
    assert retry["card_id"] is None
    assert retry["dispute_id"] is None
    assert retry["prior_actions"] == ()
    assert outcome.kind is OutcomeKind.ESCALATED


async def test_escalation_service__builds_full_and_limited_summaries() -> None:
    """RN-006-08: verificada envía datos y nota; no verificada, ninguno."""
    banking = FakeBankingTools().respond("escalate", _registered())
    service, audit = _service(banking)
    tx = DisputedTransactionBuilder().card("K-9", "**** 9999").build()
    conv = _verified()

    outcome = await service.escalate(
        conv,
        EscalationReason.FRAUD_SUSPECTED,
        "DP-007-07",
        transaction=tx,
        prior_actions=(PriorAction.CARD_BLOCKED,),
        dispute_id="D-1",
    )

    sent = banking.calls[0][1]
    assert sent["transaction_id"] == "T-0001"
    assert sent["card_id"] == "K-9"
    assert sent["prior_actions"] == (PriorAction.CARD_BLOCKED,)
    assert sent["dispute_id"] == "D-1"
    assert sent["note"] == f"DP-007-07: {messages.DP_REASONS['DP-007-07']}"
    assert outcome.kind is OutcomeKind.ESCALATED
    assert outcome.reason == messages.DP_REASONS["DP-007-07"]
    assert outcome.next_steps == messages.DP_NEXT_STEPS["DP-007-07"]
    assert outcome.transaction_id == "T-0001"
    assert outcome.masked_card == "**** 9999"
    assert outcome.reference == "E-0001"
    assert conv.escalated_keys == {sent["idempotency_key"]}
    event = audit.events[-1]
    assert event.event_type == "escalation"
    assert event.rule == "DP-007-07"
    assert event.reason == "FRAUD_SUSPECTED"

    limited_banking = FakeBankingTools().respond("escalate", _registered())
    limited, _ = _service(limited_banking)
    unverified = ConversationBuilder().located("C-0001").build()
    result = await limited.escalate(
        unverified,
        EscalationReason.OTHER,
        "RN-007-20",
        note="nota libre",
        transaction=tx,
        prior_actions=(PriorAction.CARD_BLOCKED,),
        dispute_id="D-1",
    )
    sent = limited_banking.calls[0][1]
    assert sent["transaction_id"] is None
    assert sent["card_id"] is None
    assert sent["prior_actions"] == ()
    assert sent["dispute_id"] is None
    assert sent["note"] == "nota libre"
    assert result.reason == messages.ESCALATED_NO_TX_REASON
    assert result.next_steps == messages.ESCALATED_NO_TX_NEXT_STEPS


async def test_escalation_service__deterministic_idempotency_key() -> None:
    """RN-006-09: la clave depende solo del contenido de la solicitud."""
    banking = FakeBankingTools().respond("escalate", _registered())
    service, _ = _service(banking)

    async def key(**overrides: object) -> str:
        args: dict[str, object] = {
            "reason": EscalationReason.OTHER,
            "rule": "RN-007-20",
            "note": "n",
        }
        args.update(overrides)
        await service.escalate(_verified(), **args)  # type: ignore[arg-type]
        return str(banking.calls[-1][1]["idempotency_key"])

    base = await key()
    assert await key() == base
    assert len(base) <= 64
    assert base.startswith("esc-")
    variants = {
        await key(reason=EscalationReason.FRAUD_SUSPECTED),
        await key(rule="RN-007-12"),
        await key(note="m"),
        await key(dispute_id="D-1"),
        await key(card_id="K-2"),
        await key(prior_actions=(PriorAction.CARD_BLOCKED,)),
        await key(transaction=DisputedTransactionBuilder().build()),
    }
    assert base not in variants
    assert len(variants) == 7
