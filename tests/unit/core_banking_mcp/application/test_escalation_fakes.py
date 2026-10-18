from datetime import UTC, datetime

import pytest
from tests.fakes.dispute_builder import DisputeBuilder
from tests.fakes.escalation_builder import EscalationBuilder
from tests.fakes.failing_dispute_repository import FailingDisputeRepository
from tests.fakes.failing_escalation_repository import FailingEscalationRepository
from tests.fakes.fake_dispute_repository import FakeDisputeRepository
from tests.fakes.fake_escalation_repository import FakeEscalationRepository

from core_banking_mcp.application.errors import EscalationDataNotFoundError
from core_banking_mcp.application.ports.audit_log import AuditEvent
from core_banking_mcp.domain.models.escalation import (
    EscalationReason,
    EscalationStatus,
    PriorAction,
)

NOW = datetime(2026, 4, 2, 9, 0, tzinfo=UTC)


def _add(repo: FakeEscalationRepository, conversation: str = "conv-1", key: str = "key-1"):  # type: ignore[no-untyped-def]
    return repo.add(
        conversation,
        key,
        EscalationReason.OTHER,
        NOW,
        False,
        None,
        None,
        None,
        frozenset(),
        None,
        None,
    )


# Soporte de tests: el fake de derivaciones busca por (conversación, clave) y asigna ids · Art. 3
def test_fake_escalation_repository_finds_by_key_and_adds() -> None:
    """Soporte: find_by_key aísla la conversación; add numera ESC-000001… y guarda."""
    repo = FakeEscalationRepository()
    assert repo.add_called is False
    assert repo.find_by_key("conv-1", "key-1") is None

    first = _add(repo)
    second = _add(repo, key="key-2")

    assert repo.add_called is True
    assert first.escalation_id == "ESC-000001"
    assert second.escalation_id == "ESC-000002"
    assert first.status is EscalationStatus.PENDING
    assert repo.escalations == [first, second]
    assert repo.find_by_key("conv-1", "key-1") == first
    assert repo.find_by_key("conv-2", "key-1") is None
    with pytest.raises(ValueError):
        _add(repo)


# Soporte de tests: el builder de derivaciones produce entidades válidas · Art. 3
def test_escalation_builder_builds_valid_escalations() -> None:
    """Soporte: valores por defecto válidos y todos los with_* aplicados."""
    default = EscalationBuilder().build()
    assert default.identity_verified is False
    assert default.customer_id is None

    built = (
        EscalationBuilder()
        .with_id("ESC-000009")
        .with_conversation("conv-9")
        .with_key("key-9")
        .with_reason(EscalationReason.FRAUD_SUSPECTED)
        .with_escalated_at(NOW)
        .verified_for("C-1")
        .with_transaction("TX-1")
        .with_card("CARD-1")
        .with_prior_actions(PriorAction.DISPUTE_OPENED, PriorAction.CARD_BLOCKED)
        .with_dispute("DSP-1")
        .with_note("nota")
        .build()
    )

    assert built.escalation_id == "ESC-000009"
    assert built.conversation_id == "conv-9"
    assert built.idempotency_key == "key-9"
    assert built.reason is EscalationReason.FRAUD_SUSPECTED
    assert built.escalated_at == NOW
    assert built.identity_verified is True
    assert built.customer_id == "C-1"
    assert built.transaction_id == "TX-1"
    assert built.card_id == "CARD-1"
    assert built.prior_actions == {PriorAction.DISPUTE_OPENED, PriorAction.CARD_BLOCKED}
    assert built.dispute_id == "DSP-1"
    assert built.note == "nota"


# Soporte de tests: la escritura falla hasta repair() y no registra nada · Art. 3
def test_failing_escalation_repository_fails_until_repaired() -> None:
    """Soporte: add lanza RuntimeError sin guardar; find_by_key funciona; repair habilita add."""
    repo = FailingEscalationRepository()

    with pytest.raises(RuntimeError):
        _add(repo)
    assert repo.escalations == []
    assert repo.find_by_key("conv-1", "key-1") is None

    repo.repair()
    created = _add(repo)

    assert repo.escalations == [created]


# Soporte de tests: los fakes de disputas implementan find_by_id · Art. 3
def test_fake_dispute_repositories_find_by_id() -> None:
    """Soporte: find_by_id devuelve la disputa o None, también en el fake que falla."""
    dispute = DisputeBuilder().build()
    for repo in (FakeDisputeRepository([dispute]), FailingDisputeRepository()):
        if isinstance(repo, FailingDisputeRepository):
            assert repo.find_by_id("DSP-000001") is None
        else:
            assert repo.find_by_id(dispute.dispute_id) == dispute
            assert repo.find_by_id("nope") is None


# Soporte de tests: el error de datos de derivación inexistentes existe · Art. 3
def test_escalation_data_not_found_error_exists() -> None:
    """Soporte: EscalationDataNotFoundError es una excepción."""
    assert issubclass(EscalationDataNotFoundError, Exception)


# Soporte de tests: AuditEvent admite los campos nuevos como opcionales · Art. 3
def test_audit_event_new_fields_default() -> None:
    """Soporte: sin los campos de derivación, valen None y prior_actions es ()."""
    event = AuditEvent(
        conversation_id=None,
        timestamp=NOW,
        tool="escalar_a_analista",
        input=None,
        outcome="escalated",
        count=None,
        customer_ids=(),
        error_code=None,
        rule=None,
        reason=None,
    )

    assert event.escalation_reason is None
    assert event.escalation_id is None
    assert event.note is None
    assert event.prior_actions == ()
    assert event.identity_verified is None
