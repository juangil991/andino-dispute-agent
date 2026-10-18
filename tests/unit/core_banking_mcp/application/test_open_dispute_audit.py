"""Tests de la auditoría de OpenDispute (spec 004, AC-004-17)."""

# ruff: noqa: E501  (los enunciados de RN de la trazabilidad se citan en una sola línea)

import dataclasses
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

import pytest
from tests.fakes.dispute_builder import DisputeBuilder
from tests.fakes.failing_dispute_repository import FailingDisputeRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_dispute_repository import FakeDisputeRepository
from tests.fakes.fake_transaction_repository import FakeTransactionRepository
from tests.fakes.fake_verification_store import FakeVerificationStore
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.ports.audit_log import AuditEvent
from core_banking_mcp.application.use_cases.open_dispute import OpenDispute, OpenDisputeCommand
from core_banking_mcp.domain.models.dispute import Dispute, DisputeStatus
from core_banking_mcp.domain.models.transaction import CustomerCard, Transaction, TransactionStatus

CONVERSATION = "conv-1"
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
BOGOTA = timezone(timedelta(hours=-5))
CARD = CustomerCard("K-0001", "4321")
FULL_NUMBER = "4111111111114321"
EXISTING_ID = "DSP-000007"


def _tx(
    transaction_id: str = "TX-L1", status: TransactionStatus = TransactionStatus.CONFIRMED
) -> Transaction:
    return (
        TransactionBuilder()
        .with_id(transaction_id)
        .with_card(CARD.card_id, CARD.last4)
        .with_occurred_at(datetime(2026, 10, 10, 12, 0, tzinfo=BOGOTA))
        .with_status(status)
        .build()
    )


def _existing(key: str = "K-1") -> Dispute:
    return (
        DisputeBuilder()
        .with_id(EXISTING_ID)
        .with_conversation(CONVERSATION)
        .with_key(key)
        .with_transaction("TX-L1")
        .with_status(DisputeStatus.OPEN)
        .build()
    )


def _cmd(
    transaction_id: str | None = "TX-L1",
    reason: str | None = "UNRECOGNIZED_CHARGE",
    idempotency_key: str | None = "K-1",
    conversation_id: str | None = CONVERSATION,
) -> OpenDisputeCommand:
    return OpenDisputeCommand(conversation_id, transaction_id, reason, idempotency_key)


@dataclass(frozen=True)
class Case:
    command: OpenDisputeCommand
    verified: bool = True
    transactions: tuple[Transaction, ...] = field(default_factory=lambda: (_tx(),))
    disputes: tuple[Dispute, ...] = ()
    failing: bool = False
    # Esperado
    outcome: str = "opened"
    error_code: str | None = None
    rule: str = "RN-004-11"
    transaction_id: str | None = "TX-L1"
    dispute_reason: str | None = "UNRECOGNIZED_CHARGE"
    idempotency_key: str | None = "K-1"
    dispute_id: str | None = "DSP-000001"
    customer_id: str | None = "C-0001"


CASES = {
    "una_disputa_abierta": Case(_cmd()),
    "una_repeticion": Case(
        _cmd(),
        disputes=(_existing(),),
        outcome="replayed",
        rule="RN-004-08",
        dispute_id=EXISTING_ID,
    ),
    "una_disputa_duplicada": Case(
        _cmd(idempotency_key="K-2"),
        disputes=(_existing(),),
        outcome="error",
        error_code="DISPUTE_ALREADY_OPEN",
        rule="RN-004-07",
        idempotency_key="K-2",
        dispute_id=EXISTING_ID,
    ),
    "transaccion_no_disputable": Case(
        _cmd(),
        transactions=(_tx(status=TransactionStatus.PENDING),),
        outcome="error",
        error_code="TRANSACTION_NOT_DISPUTABLE",
        rule="RN-004-05",
        dispute_id=None,
    ),
    "transaccion_no_encontrada": Case(
        _cmd(),
        transactions=(),
        outcome="error",
        error_code="NOT_FOUND",
        rule="RN-004-04",
        dispute_id=None,
    ),
    "datos_invalidos_reason_fraud": Case(
        _cmd(reason="FRAUD"),
        outcome="error",
        error_code="INVALID_INPUT",
        rule="RN-004-09",
        dispute_reason=None,
        dispute_id=None,
        customer_id=None,
    ),
    "numero_de_tarjeta_en_transaction_id": Case(
        _cmd(transaction_id=FULL_NUMBER),
        outcome="error",
        error_code="NOT_FOUND",
        rule="RN-004-04",
        transaction_id="[REDACTED]",
        dispute_id=None,
    ),
    "numero_de_tarjeta_en_idempotency_key": Case(
        _cmd(idempotency_key=f"pago-{FULL_NUMBER}"),
        idempotency_key="pago-[REDACTED]",
    ),
    "sin_verificacion": Case(
        _cmd(),
        verified=False,
        outcome="error",
        error_code="IDENTITY_NOT_VERIFIED",
        rule="RN-004-03",
        dispute_id=None,
        customer_id=None,
    ),
    "falla_inesperada": Case(
        _cmd(),
        failing=True,
        outcome="error",
        error_code="INTERNAL",
        rule="RN-004-15",
        dispute_id=None,
    ),
}


def _run(case: Case) -> FakeAuditLog:
    store = FakeVerificationStore()
    if case.verified:
        store.with_verified(CONVERSATION, "C-0001")
    disputes: FakeDisputeRepository = (
        FailingDisputeRepository() if case.failing else FakeDisputeRepository(case.disputes)
    )
    audit_log = FakeAuditLog()
    use_case = OpenDispute(
        FakeTransactionRepository({"C-0001": [CARD]}, list(case.transactions)),
        disputes,
        store,
        audit_log,
        FixedClock(NOW),
    )
    with suppress(Exception):
        use_case.execute(case.command)
    return audit_log


# Regla: RN-004-16 — Cada invocación genera exactamente un registro de auditoría con `conversation_id` (o vacío si no llegó), fecha y hora del reloj inyectado, `tool = "iniciar_disputa"`, `transaction_id`, `reason` e `idempotency_key` recibidos (cada uno vacío si no es válido según RN-004-09) y resultado: `opened`, `replayed` o el código de error. `transaction_id` e `idempotency_key` se registran con toda secuencia de 13 a 19 dígitos sustituida por `[REDACTED]`. El registro nunca contiene el número completo de una tarjeta ni el documento del cliente.
# AC-004-17 · Art. 8
@pytest.mark.parametrize("case", list(CASES.values()), ids=list(CASES))
def test_ac_004_17_each_invocation_records_exactly_one_event(case: Case) -> None:
    """AC-004-17: queda exactamente 1 registro con los datos del caso y sin el PAN ni D-1001."""
    audit_log = _run(case)

    assert len(audit_log.events) == 1
    event: AuditEvent = audit_log.events[0]
    assert event.conversation_id == CONVERSATION
    assert event.timestamp == NOW
    assert event.tool == "iniciar_disputa"
    assert event.input is None
    assert event.transaction_id == case.transaction_id
    assert event.dispute_reason == case.dispute_reason
    assert event.idempotency_key == case.idempotency_key
    assert event.outcome == case.outcome
    assert event.error_code == case.error_code
    assert event.dispute_id == case.dispute_id
    assert event.rule == case.rule
    assert event.reason
    assert event.customer_id == case.customer_id
    assert FULL_NUMBER not in str(dataclasses.asdict(event))
    assert FULL_NUMBER not in repr(event)
    assert "D-1001" not in str(dataclasses.asdict(event))
    assert "D-1001" not in repr(event)


# Regla: RN-004-16 — Cada invocación genera exactamente un registro de auditoría con `conversation_id` (o vacío si no llegó), fecha y hora del reloj inyectado, `tool = "iniciar_disputa"`.
# AC-004-17 · Art. 8
def test_ac_004_17_missing_conversation_id_is_recorded_as_empty() -> None:
    """AC-004-17: sin `conversation_id` el registro lleva la cadena vacía (RN-004-16)."""
    audit_log = _run(Case(_cmd(conversation_id=None)))

    assert len(audit_log.events) == 1
    assert audit_log.events[0].conversation_id == ""
    assert audit_log.events[0].error_code == "INVALID_INPUT"
