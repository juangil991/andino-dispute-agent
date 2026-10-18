"""Integración del repositorio de disputas sobre SQLite en memoria (AC-004-07, 08, 16)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.dispute import DisputeReason, DisputeStatus
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_dispute_repository import (
    SqlAlchemyDisputeRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_transaction_repository import (
    SqlAlchemyTransactionRepository,
)

_BOGOTA = timezone(timedelta(hours=-5))
_OPENED_AT = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
_REASON = DisputeReason.UNRECOGNIZED_CHARGE


@pytest.fixture
def session() -> Session:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    session = session_factory(engine)()
    customers = SqlAlchemyCustomerRepository(session)
    customer = CustomerBuilder().with_cards(Card("1234", CardStatus.ACTIVE)).build()
    customers.add(customer, identity=IdentityBuilder().build())
    card_ref = (
        SqlAlchemyTransactionRepository(session)
        .find_customer_cards(customer.customer_id, "1234")[0]
        .card_id
    )
    transactions = SqlAlchemyTransactionRepository(session)
    for transaction_id in ("T-0001", "T-0002"):
        transactions.add(
            card_ref,
            TransactionBuilder().with_id(transaction_id).with_card(card_ref, "1234").build(),
        )
    return session


@pytest.fixture
def repo(session: Session) -> SqlAlchemyDisputeRepository:
    return SqlAlchemyDisputeRepository(session)


def _add(
    repo: SqlAlchemyDisputeRepository,
    conversation: str = "A",
    key: str = "K-1",
    transaction: str = "T-0001",
    status: DisputeStatus = DisputeStatus.OPEN,
    opened_at: datetime = _OPENED_AT,
):  # type: ignore[no-untyped-def]
    return repo.add(conversation, key, transaction, _REASON, status, opened_at)


# Regla: RN-004-07 — una sola disputa vigente (OPEN) por transacción.
# AC-004-07 · Art. 10 (ante la duda, escalar)
def test_ac_004_07_partial_index_rejects_second_open_dispute(
    repo: SqlAlchemyDisputeRepository,
) -> None:
    """AC-004-07: el índice parcial rechaza una segunda OPEN sobre la misma transacción."""
    first = _add(repo, key="K-1")

    with pytest.raises(Exception):  # noqa: B017, PT011 - IntegrityError de SQLAlchemy
        _add(repo, conversation="B", key="K-2")

    found = repo.find_open_by_transaction("T-0001")
    assert found is not None
    assert found.dispute_id == first.dispute_id


# Regla: RN-004-07 — una disputa CLOSED o REJECTED no bloquea una nueva OPEN.
# AC-004-07 · Art. 10 (ante la duda, escalar)
@pytest.mark.parametrize("previous", [DisputeStatus.CLOSED, DisputeStatus.REJECTED])
def test_ac_004_07_open_allowed_when_previous_is_not_open(
    repo: SqlAlchemyDisputeRepository, previous: DisputeStatus
) -> None:
    """AC-004-07: con la previa CLOSED/REJECTED, un nuevo add OPEN funciona."""
    _add(repo, key="K-1", status=previous)
    assert repo.find_open_by_transaction("T-0001") is None

    reopened = _add(repo, conversation="B", key="K-2")

    found = repo.find_open_by_transaction("T-0001")
    assert found is not None
    assert found.dispute_id == reopened.dispute_id
    assert found.status is DisputeStatus.OPEN


# Regla: RN-004-08, RN-004-10 — la pareja (conversación, clave) identifica la disputa.
# AC-004-08 · Art. 10 (ante la duda, escalar)
def test_ac_004_08_find_by_idempotency_key_is_scoped_to_conversation(
    repo: SqlAlchemyDisputeRepository,
) -> None:
    """AC-004-08: búsqueda por clave dentro de la conversación; la pareja es única."""
    created = _add(repo, conversation="A", key="K-1")

    found = repo.find_by_idempotency_key("A", "K-1")
    assert found == created
    assert found.transaction_id == "T-0001"
    assert found.reason is _REASON
    assert repo.find_by_idempotency_key("B", "K-1") is None

    with pytest.raises(Exception):  # noqa: B017, PT011 - IntegrityError de SQLAlchemy
        _add(repo, conversation="A", key="K-1", transaction="T-0002")


# Regla: RN-004-15 — si el registro falla, no queda nada registrado.
# AC-004-16 · Art. 10 (ante la duda, escalar)
@pytest.mark.parametrize(
    ("conversation", "key", "transaction"),
    [("B", "K-2", "T-0001"), ("A", "K-1", "T-0002")],
    ids=["open_index_violation", "duplicate_key"],
)
def test_ac_004_16_failed_add_rolls_back_and_session_stays_usable(
    repo: SqlAlchemyDisputeRepository, conversation: str, key: str, transaction: str
) -> None:
    """AC-004-16: tras un add fallido, rollback: sin fila y sesión usable."""
    _add(repo, conversation="A", key="K-1", transaction="T-0001")

    with pytest.raises(Exception):  # noqa: B017, PT011 - IntegrityError de SQLAlchemy
        _add(repo, conversation=conversation, key=key, transaction=transaction)

    assert repo.find_by_idempotency_key("B", "K-2") is None
    assert repo.find_open_by_transaction("T-0002") is None
    valid = _add(repo, conversation="C", key="K-3", transaction="T-0002")
    assert repo.find_by_idempotency_key("C", "K-3") == valid


# Soporte de tests: identificadores DSP-NNNNNN consecutivos e instante de apertura
# guardado en UTC · Art. 3
# Regla: RN-004-11 — Una disputa nueva queda con `status = OPEN`, un `dispute_id` opaco y
# único que no se deriva del número de la tarjeta, y `opened_at` igual al instante del reloj
# inyectado expresado en ISO 8601 con la zona de Bogotá (`−05:00`).
# AC-004-01 · Art. 3
def test_support_add_assigns_sequential_ids_and_stores_utc(
    repo: SqlAlchemyDisputeRepository,
) -> None:
    """Soporte: ids DSP-000001, DSP-000002; opened_at -05:00 vuelve en UTC."""
    local = datetime(2026, 4, 1, 5, 0, tzinfo=_BOGOTA)
    first = _add(repo, key="K-1", opened_at=local)
    second = _add(repo, key="K-2", transaction="T-0002")

    assert (first.dispute_id, second.dispute_id) == ("DSP-000001", "DSP-000002")
    found = repo.find_by_idempotency_key("A", "K-1")
    assert found is not None
    assert found.opened_at == datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    assert found.opened_at.tzinfo is UTC
