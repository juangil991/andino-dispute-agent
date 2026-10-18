"""Tests de la auditoría de BlockCard (spec 005, AC-005-15)."""

# ruff: noqa: E501  (los enunciados de RN de la trazabilidad se citan en una sola línea)

import dataclasses
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from tests.fakes.card_block_builder import CardBlockBuilder
from tests.fakes.failing_card_repository import FailingCardRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_card_repository import FakeCardRepository
from tests.fakes.fake_verification_store import FakeVerificationStore
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.owned_card_builder import OwnedCardBuilder

from core_banking_mcp.application.ports.audit_log import AuditEvent
from core_banking_mcp.application.use_cases.block_card import BlockCard, BlockCardCommand
from core_banking_mcp.domain.models.card_block import BlockReason, CardBlock, OwnedCard
from core_banking_mcp.domain.models.customer import CardStatus

CONVERSATION = "conv-1"
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
FULL_NUMBER = "4111111111114321"
MASKED = "**** 4321"


def _card(status: CardStatus = CardStatus.ACTIVE) -> OwnedCard:
    return OwnedCardBuilder().with_id("CARD-0001").with_last4("4321").with_status(status).build()


def _existing(key: str = "K-1") -> CardBlock:
    return (
        CardBlockBuilder()
        .with_card("CARD-0001")
        .with_conversation(CONVERSATION)
        .with_key(key)
        .with_reason(BlockReason.FRAUD_SUSPECTED)
        .build()
    )


def _cmd(
    card_id: str | None = "CARD-0001",
    reason: str | None = "FRAUD_SUSPECTED",
    idempotency_key: str | None = "K-1",
    conversation_id: str | None = CONVERSATION,
) -> BlockCardCommand:
    return BlockCardCommand(conversation_id, card_id, reason, idempotency_key)


@dataclass(frozen=True)
class Case:
    command: BlockCardCommand
    verified: bool = True
    card: OwnedCard = field(default_factory=_card)
    blocks: tuple[CardBlock, ...] = ()
    failing: bool = False
    # Esperado
    outcome: str = "blocked"
    error_code: str | None = None
    rule: str = "RN-005-06"
    card_id: str | None = "CARD-0001"
    block_reason: str | None = "FRAUD_SUSPECTED"
    idempotency_key: str | None = "K-1"
    masked_card: str | None = MASKED
    customer_id: str | None = "C-0001"


CASES = {
    "un_bloqueo_nuevo": Case(_cmd()),
    "una_repeticion": Case(
        _cmd(),
        card=_card(CardStatus.BLOCKED),
        blocks=(_existing(),),
        outcome="replayed",
        rule="RN-005-07",
    ),
    "tarjeta_ya_bloqueada": Case(
        _cmd(idempotency_key="K-2"),
        card=_card(CardStatus.BLOCKED),
        blocks=(_existing(),),
        outcome="already_blocked",
        rule="RN-005-05",
        idempotency_key="K-2",
    ),
    "tarjeta_cancelada": Case(
        _cmd(),
        card=_card(CardStatus.CANCELLED),
        outcome="error",
        error_code="CARD_NOT_BLOCKABLE",
        rule="RN-005-05",
    ),
    "tarjeta_no_encontrada": Case(
        _cmd(card_id="CARD-9999"),
        outcome="error",
        error_code="NOT_FOUND",
        rule="RN-005-04",
        card_id="CARD-9999",
        masked_card=None,
    ),
    "datos_invalidos_reason_stolen": Case(
        _cmd(reason="STOLEN"),
        outcome="error",
        error_code="INVALID_INPUT",
        rule="RN-005-08",
        block_reason=None,
        masked_card=None,
        customer_id=None,
    ),
    "numero_de_tarjeta_en_card_id": Case(
        _cmd(card_id=FULL_NUMBER),
        outcome="error",
        error_code="NOT_FOUND",
        rule="RN-005-04",
        card_id="[REDACTED]",
        masked_card=None,
    ),
    "numero_de_tarjeta_en_idempotency_key": Case(
        _cmd(idempotency_key=f"bloqueo-{FULL_NUMBER}"),
        idempotency_key="bloqueo-[REDACTED]",
    ),
    "sin_verificacion": Case(
        _cmd(),
        verified=False,
        outcome="error",
        error_code="IDENTITY_NOT_VERIFIED",
        rule="RN-005-03",
        masked_card=None,
        customer_id=None,
    ),
    "falla_inesperada": Case(
        _cmd(),
        failing=True,
        outcome="error",
        error_code="INTERNAL",
        rule="RN-005-13",
    ),
}


def _run(case: Case) -> FakeAuditLog:
    store = FakeVerificationStore()
    if case.verified:
        store.with_verified(CONVERSATION, "C-0001")
    repository_type = FailingCardRepository if case.failing else FakeCardRepository
    cards = repository_type({"C-0001": [case.card]}, case.blocks)
    audit_log = FakeAuditLog()
    use_case = BlockCard(cards, store, audit_log, FixedClock(NOW))
    with suppress(Exception):
        use_case.execute(case.command)
    return audit_log


# Regla: RN-005-14 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "bloquear_tarjeta"`; el `card_id`, el `reason` y la `idempotency_key` recibidos (cada uno vacío si no es válido según RN-005-08, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); y el resultado. El resultado es `blocked`, `replayed`, `already_blocked` o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `CARD_NOT_BLOCKABLE`, `INTERNAL`). Como `card_id` e `idempotency_key` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente.
# AC-005-15 · Art. 8
@pytest.mark.parametrize("case", list(CASES.values()), ids=list(CASES))
def test_ac_005_15_each_invocation_records_exactly_one_event(case: Case) -> None:
    """AC-005-15: queda exactamente 1 registro con los datos del caso y sin el PAN ni D-1001."""
    audit_log = _run(case)

    assert len(audit_log.events) == 1
    event: AuditEvent = audit_log.events[0]
    assert event.conversation_id == CONVERSATION
    assert event.timestamp == NOW
    assert event.tool == "bloquear_tarjeta"
    assert event.input is None
    assert event.card_id == case.card_id
    assert event.block_reason == case.block_reason
    assert event.idempotency_key == case.idempotency_key
    assert event.masked_card == case.masked_card
    assert event.outcome == case.outcome
    assert event.error_code == case.error_code
    assert event.rule == case.rule
    assert event.reason
    assert event.customer_id == case.customer_id
    assert FULL_NUMBER not in str(dataclasses.asdict(event))
    assert FULL_NUMBER not in repr(event)
    assert "D-1001" not in str(dataclasses.asdict(event))
    assert "D-1001" not in repr(event)


# Regla: RN-005-14 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "bloquear_tarjeta"`; el `card_id`, el `reason` y la `idempotency_key` recibidos (cada uno vacío si no es válido según RN-005-08, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); y el resultado. El resultado es `blocked`, `replayed`, `already_blocked` o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `CARD_NOT_BLOCKABLE`, `INTERNAL`). Como `card_id` e `idempotency_key` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente.
# AC-005-15 · Art. 8
def test_ac_005_15_missing_conversation_id_is_recorded_as_empty() -> None:
    """AC-005-15: sin `conversation_id` el registro lleva la cadena vacía (RN-005-14)."""
    audit_log = FakeAuditLog()
    use_case = BlockCard(FakeCardRepository(), FakeVerificationStore(), audit_log, FixedClock(NOW))
    with suppress(Exception):
        use_case.execute(_cmd(conversation_id=None))

    assert len(audit_log.events) == 1
    assert audit_log.events[0].conversation_id == ""
    assert audit_log.events[0].error_code == "INVALID_INPUT"
