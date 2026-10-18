"""Tests de la auditoría de EscalateToAnalyst (spec 006, AC-006-20)."""

# ruff: noqa: E501  (los enunciados de RN de la trazabilidad se citan en una sola línea)

import dataclasses
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from tests.fakes.dispute_builder import DisputeBuilder
from tests.fakes.escalation_builder import EscalationBuilder
from tests.fakes.failing_escalation_repository import FailingEscalationRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_card_repository import FakeCardRepository
from tests.fakes.fake_dispute_repository import FakeDisputeRepository
from tests.fakes.fake_escalation_repository import FakeEscalationRepository
from tests.fakes.fake_transaction_repository import FakeTransactionRepository
from tests.fakes.fake_verification_store import FakeVerificationStore
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.owned_card_builder import OwnedCardBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.ports.audit_log import AuditEvent
from core_banking_mcp.application.use_cases.escalate_to_analyst import (
    EscalateCommand,
    EscalateToAnalyst,
)
from core_banking_mcp.domain.models.customer import CardStatus
from core_banking_mcp.domain.models.dispute import DisputeStatus
from core_banking_mcp.domain.models.escalation import EscalationReason, PriorAction
from core_banking_mcp.domain.models.transaction import CustomerCard

CONVERSATION = "A"
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
FULL_NUMBER = "4111111111114321"
MASKED = "**** 4321"


def _cmd(**overrides: object) -> EscalateCommand:
    values: dict[str, object] = {
        "conversation_id": CONVERSATION,
        "reason": "FRAUD_SUSPECTED",
        "idempotency_key": "K-1",
        "transaction_id": None,
        "card_id": None,
        "prior_actions": None,
        "dispute_id": None,
        "note": None,
    }
    values.update(overrides)
    return EscalateCommand(**values)  # type: ignore[arg-type]


def _existing() -> FakeEscalationRepository:
    escalation = (
        EscalationBuilder()
        .with_conversation(CONVERSATION)
        .with_key("K-1")
        .with_reason(EscalationReason.FRAUD_SUSPECTED)
        .verified_for("C-0001")
        .with_card("CARD-L1")
        .build()
    )
    return FakeEscalationRepository([escalation])


@dataclass(frozen=True)
class Case:
    command: EscalateCommand
    repository: str = "fake"  # "fake" | "replay" | "failing"
    # Esperado
    outcome: str = "escalated"
    error_code: str | None = None
    rule: str = "RN-006-08"
    escalation_reason: str | None = "FRAUD_SUSPECTED"
    idempotency_key: str | None = "K-1"
    transaction_id: str | None = None
    card_id: str | None = None
    note: str | None = None
    masked_card: str | None = None
    identity_verified: bool | None = True
    customer_id: str | None = "C-0001"
    escalation_id: str | None = "ESC-000001"
    conversation_id: str = CONVERSATION


CASES = {
    "una_derivacion_nueva": Case(_cmd(card_id="CARD-L1"), card_id="CARD-L1", masked_card=MASKED),
    "una_repeticion": Case(
        _cmd(card_id="CARD-L1"),
        repository="replay",
        outcome="replayed",
        rule="RN-006-09",
        card_id="CARD-L1",
        masked_card=MASKED,
    ),
    "sin_identidad_verificada": Case(
        _cmd(conversation_id="B"),
        conversation_id="B",
        identity_verified=False,
        customer_id=None,
    ),
    "transaccion_no_encontrada": Case(
        _cmd(transaction_id="TX-P1"),
        outcome="error",
        error_code="NOT_FOUND",
        rule="RN-006-04",
        transaction_id="TX-P1",
        escalation_id=None,
    ),
    "datos_invalidos_reason_fraud": Case(
        _cmd(reason="FRAUD"),
        outcome="error",
        error_code="INVALID_INPUT",
        rule="RN-006-10",
        escalation_reason=None,
        identity_verified=None,
        customer_id=None,
        escalation_id=None,
    ),
    "datos_del_cliente_sin_verificacion": Case(
        _cmd(conversation_id="B", card_id="CARD-L1"),
        conversation_id="B",
        outcome="error",
        error_code="IDENTITY_NOT_VERIFIED",
        rule="RN-006-03",
        card_id="CARD-L1",
        identity_verified=False,
        customer_id=None,
        escalation_id=None,
    ),
    "numero_de_tarjeta_en_card_id": Case(
        _cmd(card_id=FULL_NUMBER),
        outcome="error",
        error_code="NOT_FOUND",
        rule="RN-006-04",
        card_id="[REDACTED]",
        escalation_id=None,
    ),
    "numero_de_tarjeta_en_note": Case(
        _cmd(note=f"tarjeta {FULL_NUMBER}"),
        note="tarjeta [REDACTED]",
    ),
    "falla_inesperada": Case(
        _cmd(card_id="CARD-L1"),
        repository="failing",
        outcome="error",
        error_code="INTERNAL",
        rule="RN-006-15",
        card_id="CARD-L1",
        masked_card=MASKED,
        escalation_id=None,
    ),
}


def _run(
    command: EscalateCommand,
    repository: str = "fake",
    blocked: bool = False,
    disputes: tuple[str, ...] = (),
) -> FakeAuditLog:
    store = FakeVerificationStore()
    store.with_verified(CONVERSATION, "C-0001")
    transactions = FakeTransactionRepository(
        {
            "C-0001": [CustomerCard("CARD-L1", "4321")],
            "C-0002": [CustomerCard("CARD-P1", "1234")],
        },
        [
            TransactionBuilder().with_id("TX-L1").with_card("CARD-L1", "4321").build(),
            TransactionBuilder().with_id("TX-P1").with_card("CARD-P1", "1234").build(),
        ],
    )
    status = CardStatus.BLOCKED if blocked else CardStatus.ACTIVE
    cards = FakeCardRepository(
        {
            "C-0001": [
                OwnedCardBuilder().with_id("CARD-L1").with_last4("4321").with_status(status).build()
            ],
            "C-0002": [OwnedCardBuilder().with_id("CARD-P1").with_last4("1234").build()],
        }
    )
    dispute_list = [
        DisputeBuilder()
        .with_id(d)
        .with_transaction("TX-L1")
        .with_status(DisputeStatus.OPEN)
        .build()
        for d in disputes
    ]
    escalations: FakeEscalationRepository
    if repository == "replay":
        escalations = _existing()
    elif repository == "failing":
        escalations = FailingEscalationRepository()
    else:
        escalations = FakeEscalationRepository()
    audit_log = FakeAuditLog()
    use_case = EscalateToAnalyst(
        transactions,
        cards,
        FakeDisputeRepository(dispute_list),
        escalations,
        store,
        audit_log,
        FixedClock(NOW),
    )
    with suppress(Exception):
        use_case.execute(command)
    return audit_log


# Regla: RN-006-16 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "escalar_a_analista"`; el `reason`, la `idempotency_key`, el `transaction_id`, el `card_id`, el `dispute_id`, las `prior_actions` y la `note` recibidos (cada uno vacío si no llegó o no es válido según RN-006-10, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); `identity_verified` (si la conversación estaba verificada); y el resultado. El resultado es `escalated` con el `escalation_id` creado, `replayed` con el `escalation_id` existente, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INTERNAL`). Como `idempotency_key`, `transaction_id`, `card_id`, `dispute_id` y `note` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente.
# AC-006-20 · Art. 8
@pytest.mark.parametrize("case", list(CASES.values()), ids=list(CASES))
def test_ac_006_20_each_invocation_records_exactly_one_event(case: Case) -> None:
    """AC-006-20: queda exactamente 1 registro con los datos del caso y sin el PAN ni D-1001."""
    audit_log = _run(case.command, case.repository)

    assert len(audit_log.events) == 1
    event: AuditEvent = audit_log.events[0]
    assert event.conversation_id == case.conversation_id
    assert event.timestamp == NOW
    assert event.tool == "escalar_a_analista"
    assert event.input is None
    assert event.escalation_reason == case.escalation_reason
    assert event.idempotency_key == case.idempotency_key
    assert event.transaction_id == case.transaction_id
    assert event.card_id == case.card_id
    assert event.dispute_id is None
    assert event.prior_actions == ()
    assert event.note == case.note
    assert event.masked_card == case.masked_card
    assert event.identity_verified == case.identity_verified
    assert event.outcome == case.outcome
    assert event.error_code == case.error_code
    assert event.escalation_id == case.escalation_id
    assert event.rule == case.rule
    assert event.reason
    assert event.customer_id == case.customer_id
    assert FULL_NUMBER not in str(dataclasses.asdict(event))
    assert FULL_NUMBER not in repr(event)
    assert "D-1001" not in str(dataclasses.asdict(event))
    assert "D-1001" not in repr(event)


# Regla: RN-006-16 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "escalar_a_analista"`; el `reason`, la `idempotency_key`, el `transaction_id`, el `card_id`, el `dispute_id`, las `prior_actions` y la `note` recibidos (cada uno vacío si no llegó o no es válido según RN-006-10, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); `identity_verified` (si la conversación estaba verificada); y el resultado. El resultado es `escalated` con el `escalation_id` creado, `replayed` con el `escalation_id` existente, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INTERNAL`). Como `idempotency_key`, `transaction_id`, `card_id`, `dispute_id` y `note` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente.
# AC-006-20 · Art. 8
def test_ac_006_20_missing_conversation_id_is_recorded_as_empty() -> None:
    """AC-006-20: sin `conversation_id` el registro lleva la cadena vacía (RN-006-16)."""
    audit_log = _run(_cmd(conversation_id=None))

    assert len(audit_log.events) == 1
    assert audit_log.events[0].conversation_id == ""
    assert audit_log.events[0].error_code == "INVALID_INPUT"


# Regla: RN-006-16 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "escalar_a_analista"`; el `reason`, la `idempotency_key`, el `transaction_id`, el `card_id`, el `dispute_id`, las `prior_actions` y la `note` recibidos (cada uno vacío si no llegó o no es válido según RN-006-10, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); `identity_verified` (si la conversación estaba verificada); y el resultado. El resultado es `escalated` con el `escalation_id` creado, `replayed` con el `escalation_id` existente, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INTERNAL`). Como `idempotency_key`, `transaction_id`, `card_id`, `dispute_id` y `note` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente.
# AC-006-20 · Art. 8
def test_ac_006_20_records_dispute_id_and_prior_actions_received() -> None:
    """AC-006-20: el `dispute_id` y las `prior_actions` recibidos quedan en el registro."""
    audit_log = _run(
        _cmd(
            transaction_id="TX-L1",
            card_id="CARD-L1",
            dispute_id="DSP-000001",
            prior_actions=["CARD_BLOCKED", "DISPUTE_OPENED"],
        ),
        blocked=True,
        disputes=("DSP-000001",),
    )

    assert len(audit_log.events) == 1
    event = audit_log.events[0]
    assert event.outcome == "escalated"
    assert event.dispute_id == "DSP-000001"
    assert event.prior_actions == (
        PriorAction.DISPUTE_OPENED.value,
        PriorAction.CARD_BLOCKED.value,
    )
    assert event.masked_card == MASKED


# Regla: RN-006-16 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "escalar_a_analista"`; el `reason`, la `idempotency_key`, el `transaction_id`, el `card_id`, el `dispute_id`, las `prior_actions` y la `note` recibidos (cada uno vacío si no llegó o no es válido según RN-006-10, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); `identity_verified` (si la conversación estaba verificada); y el resultado. El resultado es `escalated` con el `escalation_id` creado, `replayed` con el `escalation_id` existente, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INTERNAL`). Como `idempotency_key`, `transaction_id`, `card_id`, `dispute_id` y `note` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente.
# AC-006-20 · Art. 8
def test_ac_006_20_invalid_prior_actions_are_recorded_empty() -> None:
    """AC-006-20: unas `prior_actions` inválidas se registran vacías (RN-006-16)."""
    audit_log = _run(_cmd(prior_actions=["DISPUTE_OPENED", "<script>"]))

    assert len(audit_log.events) == 1
    event = audit_log.events[0]
    assert event.error_code == "INVALID_INPUT"
    assert event.prior_actions == ()
    assert "<script>" not in repr(event)
