"""Integración del repositorio de transacciones sobre SQLite en memoria (AC-003-*)."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.domain.models.customer import Card, CardStatus, Customer
from core_banking_mcp.domain.models.transaction import BogotaDateRange
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_transaction_repository import (
    SqlAlchemyTransactionRepository,
)

_BOGOTA = timezone(timedelta(hours=-5))
_SEPTEMBER = BogotaDateRange(date(2026, 9, 1), date(2026, 9, 30))
_FAR_PAST = datetime(2000, 1, 1, tzinfo=UTC)
_FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    return session_factory(engine)()


@pytest.fixture
def customers(session: Session) -> SqlAlchemyCustomerRepository:
    return SqlAlchemyCustomerRepository(session)


@pytest.fixture
def repo(session: Session) -> SqlAlchemyTransactionRepository:
    return SqlAlchemyTransactionRepository(session)


def _customer(
    customers: SqlAlchemyCustomerRepository,
    customer_id: str,
    document: str,
    *cards: Card,
) -> Customer:
    customer = CustomerBuilder().with_id(customer_id).with_document(document).with_cards(*cards)
    built = customer.build()
    customers.add(built, identity=IdentityBuilder().build())
    return built


def _tx(card_ref: str, last4: str, transaction_id: str = "T-0001") -> TransactionBuilder:
    return TransactionBuilder().with_id(transaction_id).with_card(card_ref, last4)


# Regla: RN-003-01 — La solicitud indica la tarjeta por sus últimos 4 dígitos (`card_last4`) y el rango con `date_from` y `date_to` en formato ISO `AAAA-MM-DD`, ambos incluidos.  # noqa: E501
# Regla: RN-003-05 — Cada transacción tiene un instante `occurred_at` (fecha y hora con zona). Entra en el rango si su **fecha local en `America/Bogota`** está entre `date_from` y `date_to`, ambos incluidos.  # noqa: E501
# AC-003-02 · Art. 3
@pytest.mark.parametrize(
    ("occurred_at", "appears"),
    [
        pytest.param(datetime(2026, 9, 1, 0, 0, 0, tzinfo=_BOGOTA), True, id="sep-1-start"),
        pytest.param(datetime(2026, 9, 30, 23, 59, 59, tzinfo=_BOGOTA), True, id="sep-30-end"),
        pytest.param(datetime(2026, 8, 31, 23, 59, 59, tzinfo=_BOGOTA), False, id="aug-31-out"),
        pytest.param(datetime(2026, 10, 1, 0, 0, 0, tzinfo=_BOGOTA), False, id="oct-1-out"),
        pytest.param(datetime(2026, 10, 1, 3, 30, tzinfo=UTC), True, id="utc-oct-1-is-sep-30"),
        pytest.param(datetime(2026, 9, 1, 4, 30, tzinfo=UTC), False, id="utc-sep-1-is-aug-31"),
    ],
)
def test_ac_003_02_find_transactions_uses_bogota_day_bounds(
    customers: SqlAlchemyCustomerRepository,
    repo: SqlAlchemyTransactionRepository,
    occurred_at: datetime,
    appears: bool,
) -> None:
    """AC-003-02: los días extremos se incluyen según la fecha de Bogotá (RN-003-01, RN-003-05)."""
    _customer(customers, "C-0001", "DOC-1", Card("4321", CardStatus.ACTIVE))
    repo.add("CARD-0001", _tx("CARD-0001", "4321").with_occurred_at(occurred_at).build())

    start, end = _SEPTEMBER.utc_bounds()
    found = repo.find_transactions(["CARD-0001"], start, end, 51)

    assert [t.transaction_id for t in found] == (["T-0001"] if appears else [])


# Regla: RN-003-03 — Se consultan **todas** las tarjetas del cliente verificado en la conversación que terminan en `card_last4`, **sea cual sea su estado** (activa, bloqueada, cancelada); sus transacciones se devuelven juntas en una sola lista.  # noqa: E501
# AC-003-04 · Art. 3
@pytest.mark.parametrize("status", [CardStatus.ACTIVE, CardStatus.BLOCKED, CardStatus.CANCELLED])
def test_ac_003_04_find_customer_cards_matches_any_card_status(
    customers: SqlAlchemyCustomerRepository,
    repo: SqlAlchemyTransactionRepository,
    status: CardStatus,
) -> None:
    """AC-003-04: la tarjeta 4321 se encuentra activa, bloqueada o cancelada (RN-003-03)."""
    _customer(customers, "C-0001", "DOC-1", Card("4321", status))
    repo.add("CARD-0001", _tx("CARD-0001", "4321", "T-0001").build())
    repo.add("CARD-0001", _tx("CARD-0001", "4321", "T-0002").build())

    cards = repo.find_customer_cards("C-0001", "4321")
    found = repo.find_transactions([c.card_id for c in cards], _FAR_PAST, _FAR_FUTURE, 51)

    assert [(c.card_id, c.last4) for c in cards] == [("CARD-0001", "4321")]
    assert len(found) == 2


# Regla: RN-003-03 — Se consultan **todas** las tarjetas del cliente verificado en la conversación que terminan en `card_last4`, **sea cual sea su estado** (activa, bloqueada, cancelada); sus transacciones se devuelven juntas en una sola lista.  # noqa: E501
# Regla: RN-003-12 — Cada transacción devuelta contiene **solo**: `transaction_id`, `occurred_at`, `merchant`, `amount`, `currency`, `status`, `card_id` (identificador opaco de la tarjeta en el core, no derivado de su número) y `masked_card`.  # noqa: E501
# AC-003-05 · Art. 3
def test_ac_003_05_two_cards_same_last4_return_distinct_card_ids(
    customers: SqlAlchemyCustomerRepository,
    repo: SqlAlchemyTransactionRepository,
) -> None:
    """AC-003-05: dos tarjetas 4321 del cliente dan dos card_id y sus transacciones juntas."""
    _customer(
        customers,
        "C-0001",
        "DOC-1",
        Card("4321", CardStatus.ACTIVE),
        Card("4321", CardStatus.BLOCKED),
    )
    repo.add("CARD-0001", _tx("CARD-0001", "4321", "T-0001").build())
    repo.add("CARD-0002", _tx("CARD-0002", "4321", "T-0002").build())

    cards = repo.find_customer_cards("C-0001", "4321")
    found = repo.find_transactions([c.card_id for c in cards], _FAR_PAST, _FAR_FUTURE, 51)

    assert len(cards) == 2
    assert cards[0].card_id != cards[1].card_id
    assert {t.card_id for t in found} == {c.card_id for c in cards}
    assert {t.card_last4 for t in found} == {"4321"}


# Regla: RN-003-04 — Si el cliente verificado no tiene ninguna tarjeta terminada en `card_last4` (porque la tarjeta es de otro cliente o porque no existe), se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en ambos casos, sin datos de ningún cliente.  # noqa: E501
# AC-003-13 · Art. 7
@pytest.mark.parametrize(
    "last4",
    [pytest.param("8765", id="card-of-another-customer"), pytest.param("0000", id="nonexistent")],
)
def test_ac_003_13_find_customer_cards_ignores_foreign_or_missing_card(
    customers: SqlAlchemyCustomerRepository,
    repo: SqlAlchemyTransactionRepository,
    last4: str,
) -> None:
    """AC-003-13: una tarjeta ajena o inexistente no devuelve tarjetas del cliente (RN-003-04)."""
    _customer(customers, "C-0001", "DOC-1", Card("4321", CardStatus.ACTIVE))
    _customer(customers, "C-0002", "DOC-2", Card("8765", CardStatus.ACTIVE))
    repo.add("CARD-0002", _tx("CARD-0002", "8765").build())

    assert repo.find_customer_cards("C-0001", last4) == []


# Regla: RN-003-11 — Las transacciones se ordenan de la más reciente a la más antigua por `occurred_at`; si dos tienen el mismo instante, por `transaction_id` ascendente (resultado determinista).  # noqa: E501
# AC-003-15 · Art. 3
def test_ac_003_15_find_transactions_orders_desc_then_by_id_and_limits(
    customers: SqlAlchemyCustomerRepository,
    repo: SqlAlchemyTransactionRepository,
) -> None:
    """AC-003-15: orden por occurred_at desc y transaction_id asc; el límite se aplica."""
    _customer(customers, "C-0001", "DOC-1", Card("4321", CardStatus.ACTIVE))
    same_instant = datetime(2026, 9, 15, 10, 0, tzinfo=_BOGOTA)
    repo.add("CARD-0001", _tx("CARD-0001", "4321", "T-0003").with_occurred_at(same_instant).build())
    repo.add("CARD-0001", _tx("CARD-0001", "4321", "T-0002").with_occurred_at(same_instant).build())
    latest = datetime(2026, 9, 16, 8, 0, tzinfo=_BOGOTA)
    repo.add("CARD-0001", _tx("CARD-0001", "4321", "T-0009").with_occurred_at(latest).build())

    start, end = _SEPTEMBER.utc_bounds()
    found = repo.find_transactions(["CARD-0001"], start, end, 51)
    limited = repo.find_transactions(["CARD-0001"], start, end, 2)

    assert [t.transaction_id for t in found] == ["T-0009", "T-0002", "T-0003"]
    assert [t.transaction_id for t in limited] == ["T-0009", "T-0002"]


# Regla: RN-003-12 — Cada transacción devuelta contiene **solo**: `transaction_id`, `occurred_at`, `merchant`, `amount` (texto decimal positivo con exactamente 2 decimales, p. ej. `"125000.00"`), `currency` (código ISO 4217, p. ej. `COP`, `USD`), `status`, `card_id` y `masked_card`.  # noqa: E501
# AC-003-16 · Art. 3
@pytest.mark.parametrize(
    ("amount", "currency"),
    [
        pytest.param(Decimal("125000.00"), "COP", id="cop-integer"),
        pytest.param(Decimal("49.90"), "USD", id="usd-one-decimal"),
        pytest.param(Decimal("0.05"), "USD", id="usd-cents"),
    ],
)
def test_ac_003_16_amount_and_currency_roundtrip(
    customers: SqlAlchemyCustomerRepository,
    repo: SqlAlchemyTransactionRepository,
    amount: Decimal,
    currency: str,
) -> None:
    """AC-003-16: el monto (unidades menores) y la moneda se conservan (RN-003-12)."""
    _customer(customers, "C-0001", "DOC-1", Card("4321", CardStatus.ACTIVE))
    repo.add(
        "CARD-0001",
        _tx("CARD-0001", "4321").with_amount(amount).with_currency(currency).build(),
    )

    (found,) = repo.find_transactions(["CARD-0001"], _FAR_PAST, _FAR_FUTURE, 51)

    assert found.amount == amount
    assert str(found.amount) == str(amount)
    assert found.currency == currency


# Soporte de tests: ida y vuelta de occurred_at con offset -05:00 (se guarda en UTC) · Art. 3
# Regla: RN-003-05 — cada transacción tiene un instante `occurred_at` (fecha y hora con zona); entra en el rango si su fecha local en `America/Bogota` está entre `date_from` y `date_to`, ambos incluidos.  # noqa: E501
# AC-003-02 · Art. 3
def test_support_occurred_at_roundtrips_as_utc(
    customers: SqlAlchemyCustomerRepository,
    repo: SqlAlchemyTransactionRepository,
) -> None:
    _customer(customers, "C-0001", "DOC-1", Card("4321", CardStatus.ACTIVE))
    local = datetime(2026, 9, 15, 10, 0, tzinfo=_BOGOTA)
    repo.add("CARD-0001", _tx("CARD-0001", "4321").with_occurred_at(local).build())

    (found,) = repo.find_transactions(["CARD-0001"], _FAR_PAST, _FAR_FUTURE, 51)

    assert found.occurred_at == local
    assert found.occurred_at.tzinfo is UTC
    assert found.occurred_at.hour == 15
