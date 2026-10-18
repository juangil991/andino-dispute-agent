from datetime import UTC, datetime

import pytest
from tests.fakes.card_block_builder import CardBlockBuilder
from tests.fakes.failing_card_repository import FailingCardRepository
from tests.fakes.fake_card_repository import FakeCardRepository
from tests.fakes.owned_card_builder import OwnedCardBuilder

from core_banking_mcp.application.errors import CardNotBlockableError, CardNotFoundError
from core_banking_mcp.application.ports.audit_log import AuditEvent
from core_banking_mcp.domain.models.card_block import BlockReason
from core_banking_mcp.domain.models.customer import CardStatus

NOW = datetime(2026, 4, 2, 9, 0, tzinfo=UTC)


# Soporte de tests: el fake de tarjetas respeta propiedad y deja la tarjeta BLOCKED · Art. 3
def test_fake_card_repository_finds_customer_cards_and_blocks() -> None:
    """Soporte: lecturas por cliente, por clave y por tarjeta; block deja BLOCKED."""
    card = OwnedCardBuilder().build()
    existing = CardBlockBuilder().with_card("CARD-0002").build()
    repo = FakeCardRepository(cards={"C-1": [card]}, blocks=[existing])

    assert repo.find_customer_card("C-1", "CARD-0001") == card
    assert repo.find_customer_card("C-2", "CARD-0001") is None
    assert repo.find_customer_card("C-1", "nope") is None
    assert repo.find_block_by_key("conv-0001", "key-0001") == existing
    assert repo.find_block_by_key("conv-other", "key-0001") is None
    assert repo.find_block_by_card("CARD-0002") == existing
    assert repo.find_block_by_card("CARD-0001") is None
    assert repo.block_called is False

    created = repo.block("conv-9", "key-9", "CARD-0001", BlockReason.LOST_OR_STOLEN, NOW)

    assert repo.block_called is True
    assert repo.blocks[-1] == created
    assert created.blocked_at == NOW
    found = repo.find_customer_card("C-1", "CARD-0001")
    assert found is not None
    assert found.status is CardStatus.BLOCKED


# Soporte de tests: unicidad por (conversación, clave) y por tarjeta · Art. 3
def test_fake_card_repository_enforces_uniqueness() -> None:
    """Soporte: no admite dos bloqueos con la misma clave ni para la misma tarjeta."""
    repo = FakeCardRepository(cards={"C-1": [OwnedCardBuilder().build()]})
    repo.block("conv-1", "k1", "CARD-0001", BlockReason.FRAUD_SUSPECTED, NOW)

    with pytest.raises(ValueError):
        repo.block("conv-1", "k1", "CARD-0002", BlockReason.FRAUD_SUSPECTED, NOW)
    with pytest.raises(ValueError):
        repo.block("conv-1", "k2", "CARD-0001", BlockReason.FRAUD_SUSPECTED, NOW)
    assert len(repo.blocks) == 1


# Soporte de tests: el fake que falla no cambia nada hasta repararse · Art. 3
def test_failing_card_repository_fails_until_repaired() -> None:
    """Soporte: block lanza RuntimeError sin cambios; tras repair() funciona."""
    repo = FailingCardRepository(cards={"C-1": [OwnedCardBuilder().build()]})

    with pytest.raises(RuntimeError):
        repo.block("conv-1", "k1", "CARD-0001", BlockReason.FRAUD_SUSPECTED, NOW)
    assert repo.blocks == []
    card = repo.find_customer_card("C-1", "CARD-0001")
    assert card is not None
    assert card.status is CardStatus.ACTIVE

    repo.repair()
    repo.block("conv-1", "k1", "CARD-0001", BlockReason.FRAUD_SUSPECTED, NOW)
    assert len(repo.blocks) == 1


# Soporte de tests: builders con valores por defecto válidos y modificadores · Art. 3
def test_card_builders_build_valid_objects() -> None:
    """Soporte: los builders crean objetos válidos y aplican los with_*."""
    card = OwnedCardBuilder().with_id("X-1").with_last4("9999").with_status(CardStatus.BLOCKED)
    built = card.build()
    assert (built.card_id, built.last4, built.status) == ("X-1", "9999", CardStatus.BLOCKED)

    block = (
        CardBlockBuilder()
        .with_card("X-1")
        .with_conversation("c")
        .with_key("k")
        .with_reason(BlockReason.LOST_OR_STOLEN)
        .with_blocked_at(NOW)
        .build()
    )
    assert block.card_id == "X-1"
    assert block.conversation_id == "c"
    assert block.idempotency_key == "k"
    assert block.reason is BlockReason.LOST_OR_STOLEN
    assert block.blocked_at == NOW


# Soporte de tests: errores de aplicación y campos nuevos de auditoría opcionales · Art. 3
def test_card_errors_exist_and_audit_event_new_fields_default_to_none() -> None:
    """Soporte: errores definidos y AuditEvent sin card_id/block_reason por defecto."""
    assert issubclass(CardNotFoundError, Exception)
    assert issubclass(CardNotBlockableError, Exception)
    event = AuditEvent(
        conversation_id=None,
        timestamp=NOW,
        tool="t",
        input=None,
        outcome="ok",
        count=None,
        customer_ids=(),
        error_code=None,
        rule=None,
        reason=None,
    )
    assert event.card_id is None
    assert event.block_reason is None
