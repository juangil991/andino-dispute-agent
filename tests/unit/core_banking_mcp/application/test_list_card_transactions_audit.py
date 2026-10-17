"""Tests de la auditoría de ListCardTransactions (spec 003, AC-003-17)."""

# ruff: noqa: E501  (los enunciados de RN de la trazabilidad se citan en una sola línea)

import dataclasses
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest
from tests.fakes.failing_transaction_repository import FailingTransactionRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_transaction_repository import FakeTransactionRepository
from tests.fakes.fake_verification_store import FakeVerificationStore
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.ports.audit_log import AuditEvent
from core_banking_mcp.application.ports.transaction_repository import TransactionRepository
from core_banking_mcp.application.use_cases.list_card_transactions import (
    ListCardTransactions,
    ListCardTransactionsCommand,
)
from core_banking_mcp.domain.models.transaction import CustomerCard, Transaction

CONVERSATION = "conv-1"
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
BOGOTA = timezone(timedelta(hours=-5))
CARD = CustomerCard("K-0001", "4321")
FULL_NUMBER = "4111111111114321"


def _tx(transaction_id: str, day: int = 10) -> Transaction:
    return (
        TransactionBuilder()
        .with_id(transaction_id)
        .with_card(CARD.card_id, CARD.last4)
        .with_occurred_at(datetime(2026, 9, day, 10, 0, tzinfo=BOGOTA))
        .build()
    )


@dataclass(frozen=True)
class Case:
    command: ListCardTransactionsCommand
    verified: bool = True
    cards: tuple[CustomerCard, ...] = (CARD,)
    transactions: tuple[Transaction, ...] = ()
    failing: bool = False
    # Esperado
    outcome: str = "found"
    count: int | None = 0
    transaction_ids: tuple[str, ...] = ()
    error_code: str | None = None
    rule: str = "RN-003-05"
    masked_card: str | None = "**** 4321"
    customer_id: str | None = "C-0001"


def _cmd(
    card_last4: str | None = "4321",
    date_from: str | None = "2026-09-01",
    date_to: str | None = "2026-09-30",
    conversation_id: str | None = CONVERSATION,
) -> ListCardTransactionsCommand:
    return ListCardTransactionsCommand(conversation_id, card_last4, date_from, date_to)


CASES = {
    "transacciones_encontradas": Case(
        _cmd(),
        transactions=(_tx("T-1", 5), _tx("T-2", 12)),
        count=2,
        transaction_ids=("T-2", "T-1"),
    ),
    "ninguna_transaccion": Case(_cmd()),
    "mas_de_50": Case(
        _cmd(),
        transactions=tuple(_tx(f"T-{i:03d}") for i in range(51)),
        outcome="refinement_required",
        rule="RN-003-10",
    ),
    "datos_invalidos": Case(
        _cmd(date_from="2026-09-30", date_to="2026-09-01"),
        outcome="error",
        count=None,
        error_code="INVALID_INPUT",
        rule="RN-003-06",
        customer_id=None,
    ),
    "numero_completo_en_card_last4": Case(
        _cmd(card_last4=FULL_NUMBER),
        outcome="error",
        count=None,
        error_code="INVALID_INPUT",
        rule="RN-003-06",
        masked_card=None,
        customer_id=None,
    ),
    "sin_verificacion": Case(
        _cmd(),
        verified=False,
        outcome="error",
        count=None,
        error_code="IDENTITY_NOT_VERIFIED",
        rule="RN-003-02",
        customer_id=None,
    ),
    "tarjeta_no_encontrada": Case(
        _cmd(),
        cards=(),
        outcome="error",
        count=None,
        error_code="NOT_FOUND",
        rule="RN-003-04",
    ),
    "falla_inesperada": Case(
        _cmd(),
        failing=True,
        outcome="error",
        count=None,
        error_code="INTERNAL",
        rule="RN-003-16",
    ),
}


def _run(case: Case) -> FakeAuditLog:
    store = FakeVerificationStore()
    if case.verified:
        store.with_verified(CONVERSATION, "C-0001")
    repository: TransactionRepository = (
        FailingTransactionRepository()
        if case.failing
        else FakeTransactionRepository({"C-0001": list(case.cards)}, list(case.transactions))
    )
    audit_log = FakeAuditLog()
    use_case = ListCardTransactions(repository, store, audit_log, FixedClock(NOW))
    with suppress(Exception):
        use_case.execute(case.command)
    return audit_log


# Regla: RN-003-15 — Cada invocación genera exactamente un registro de auditoría con `conversation_id` (o vacío si no llegó), fecha y hora del reloj inyectado, `tool = "consultar_transacciones"`, tarjeta enmascarada (`**** NNNN`; vacía si `card_last4` no es válido, para no registrar lo que se haya escrito en ese campo), rango consultado (`date_from` y `date_to` recibidos) y resultado: `found` con la cantidad y los `transaction_id` devueltos (cantidad 0 si no hubo), `refinement_required`, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INTERNAL`). El registro **nunca** contiene el número completo de una tarjeta.
# AC-003-17 · Art. 8
@pytest.mark.parametrize("case", list(CASES.values()), ids=list(CASES))
def test_ac_003_17_each_invocation_records_exactly_one_event(case: Case) -> None:
    """AC-003-17: queda exactamente 1 registro con los datos del caso y sin el número completo."""
    audit_log = _run(case)

    assert len(audit_log.events) == 1
    event: AuditEvent = audit_log.events[0]
    assert event.conversation_id == CONVERSATION
    assert event.timestamp == NOW
    assert event.tool == "consultar_transacciones"
    assert event.input is None
    assert event.masked_card == case.masked_card
    assert event.date_from == case.command.date_from
    assert event.date_to == case.command.date_to
    assert event.outcome == case.outcome
    assert event.count == case.count
    assert event.transaction_ids == case.transaction_ids
    assert event.error_code == case.error_code
    assert event.rule == case.rule
    assert event.reason
    assert event.customer_id == case.customer_id
    assert FULL_NUMBER not in str(dataclasses.asdict(event))
    assert FULL_NUMBER not in repr(event)


# Regla: RN-003-15 — Cada invocación genera exactamente un registro de auditoría con `conversation_id` (o vacío si no llegó), fecha y hora del reloj inyectado, `tool = "consultar_transacciones"`, tarjeta enmascarada (`**** NNNN`; vacía si `card_last4` no es válido, para no registrar lo que se haya escrito en ese campo), rango consultado (`date_from` y `date_to` recibidos) y resultado: `found` con la cantidad y los `transaction_id` devueltos (cantidad 0 si no hubo), `refinement_required`, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INTERNAL`). El registro **nunca** contiene el número completo de una tarjeta.
# AC-003-17 · Art. 8
def test_ac_003_17_missing_conversation_id_is_recorded_as_empty() -> None:
    """AC-003-17: sin `conversation_id` el registro lleva la cadena vacía (RN-003-15)."""
    audit_log = _run(Case(_cmd(conversation_id=None), verified=False))

    assert len(audit_log.events) == 1
    assert audit_log.events[0].conversation_id == ""
    assert audit_log.events[0].error_code == "INVALID_INPUT"
