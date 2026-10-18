"""Soporte de tests: fakes y builder de disputas (feature 004)."""

from datetime import UTC, datetime

import pytest
from tests.fakes.dispute_builder import DisputeBuilder
from tests.fakes.failing_dispute_repository import FailingDisputeRepository
from tests.fakes.fake_dispute_repository import FakeDisputeRepository
from tests.fakes.fake_transaction_repository import FakeTransactionRepository
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.errors import (
    DisputeAlreadyOpenError,
    TransactionNotDisputableError,
    TransactionNotFoundError,
)
from core_banking_mcp.application.ports.audit_log import AuditEvent
from core_banking_mcp.domain.models.dispute import Dispute, DisputeReason, DisputeStatus
from core_banking_mcp.domain.models.transaction import CustomerCard

OPENED_AT = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)


def test_fake_dispute_repository_assigns_ids_and_finds_by_key_and_open() -> None:
    """Soporte de tests: el fake asigna ids y busca por clave y por abierta · Art. 3."""
    existing = DisputeBuilder().with_id("DSP-000001").with_key("k-old").build()
    repo = FakeDisputeRepository(disputes=[existing])

    created = repo.add("C-1", "k-1", "T-9", DisputeReason.OTHER, DisputeStatus.OPEN, OPENED_AT)
    second = repo.add("C-1", "k-2", "T-8", DisputeReason.OTHER, DisputeStatus.OPEN, OPENED_AT)

    assert created.dispute_id == "DSP-000002"
    assert second.dispute_id == "DSP-000003"
    assert repo.called is True
    assert len(repo.disputes) == 3
    assert repo.find_by_idempotency_key("C-1", "k-1") == created
    assert repo.find_by_idempotency_key("OTHER-CONV", "k-1") is None
    assert repo.find_open_by_transaction("T-9") == created


def test_fake_dispute_repository_ignores_closed_and_rejected() -> None:
    """Soporte de tests: find_open_by_transaction ignora CLOSED y REJECTED · Art. 3."""
    closed = (
        DisputeBuilder().with_id("D-1").with_transaction("T-1").with_status(DisputeStatus.CLOSED)
    )
    rejected = (
        DisputeBuilder().with_id("D-2").with_transaction("T-1").with_status(DisputeStatus.REJECTED)
    )
    repo = FakeDisputeRepository(disputes=[closed.build(), rejected.build()])
    assert repo.find_open_by_transaction("T-1") is None


def test_dispute_builder_builds_valid_dispute_with_overrides() -> None:
    """Soporte de tests: el builder admite todos los overrides · Art. 3."""
    default = DisputeBuilder().build()
    assert isinstance(default, Dispute)
    built = (
        DisputeBuilder()
        .with_id("D-7")
        .with_status(DisputeStatus.CLOSED)
        .with_transaction("T-7")
        .with_conversation("C-7")
        .with_key("k-7")
        .with_reason(DisputeReason.NOT_RECEIVED)
        .with_opened_at(OPENED_AT)
        .build()
    )
    assert (built.dispute_id, built.status, built.transaction_id) == (
        "D-7",
        DisputeStatus.CLOSED,
        "T-7",
    )
    assert (built.conversation_id, built.idempotency_key, built.reason, built.opened_at) == (
        "C-7",
        "k-7",
        DisputeReason.NOT_RECEIVED,
        OPENED_AT,
    )


def test_failing_dispute_repository_fails_on_add_until_repaired() -> None:
    """Soporte de tests: add falla sin guardar; repair lo habilita · Art. 3."""
    repo = FailingDisputeRepository()
    with pytest.raises(RuntimeError):
        repo.add("C-1", "k", "T-1", DisputeReason.OTHER, DisputeStatus.OPEN, OPENED_AT)
    assert repo.disputes == []
    assert repo.find_by_idempotency_key("C-1", "k") is None
    assert repo.find_open_by_transaction("T-1") is None
    repo.repair()
    created = repo.add("C-1", "k", "T-1", DisputeReason.OTHER, DisputeStatus.OPEN, OPENED_AT)
    assert created.dispute_id == "DSP-000001"
    assert repo.find_by_idempotency_key("C-1", "k") == created


def test_fake_transaction_repository_finds_customer_transaction() -> None:
    """Soporte de tests: resuelve la transacción solo para el cliente dueño · Art. 3."""
    tx = TransactionBuilder().with_id("T-1").with_card("K-1", "1234").build()
    repo = FakeTransactionRepository(
        cards={"CU-1": [CustomerCard("K-1", "1234")], "CU-2": [CustomerCard("K-2", "9999")]},
        transactions=[tx],
    )
    assert repo.find_customer_transaction("CU-1", "T-1") == tx
    assert repo.find_customer_transaction("CU-2", "T-1") is None
    assert repo.find_customer_transaction("CU-1", "T-404") is None


def test_new_errors_and_audit_event_defaults() -> None:
    """Soporte de tests: errores nuevos y campos de auditoría opcionales · Art. 3."""
    assert issubclass(TransactionNotFoundError, Exception)
    assert issubclass(TransactionNotDisputableError, Exception)
    assert DisputeAlreadyOpenError("D-OLD").dispute_id == "D-OLD"
    event = AuditEvent(None, OPENED_AT, "t", None, "ok", None, (), None, None, None)
    assert event.transaction_id is None
    assert event.dispute_reason is None
    assert event.idempotency_key is None
    assert event.dispute_id is None
