"""Semillas ficticias de transacciones (plan §4, Art. 1). Datos fijos, sin aleatoriedad."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core_banking_mcp.domain.models.transaction import Transaction, TransactionStatus
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_transaction_repository import (
    SqlAlchemyTransactionRepository,
)

_BOGOTA = timezone(timedelta(hours=-5))
_CONFIRMED = TransactionStatus.CONFIRMED


def _tx(
    tx_id: str,
    card_ref: str,
    last4: str,
    when: tuple[int, int, int, int, int],
    merchant: str,
    amount: str,
    currency: str,
    status: TransactionStatus,
    merchant_country: str = "CO",
) -> Transaction:
    return Transaction(
        tx_id,
        card_ref,
        last4,
        datetime(*when, tzinfo=_BOGOTA),
        merchant,
        Decimal(amount),
        currency,
        status,
        merchant_country,
    )


SEED_TRANSACTIONS: tuple[Transaction, ...] = (
    _tx("TX-000001", "CARD-0001", "4321", (2026, 9, 5, 9, 15), "Supermercado La Cosecha",
        "185000.00", "COP", _CONFIRMED),
    _tx("TX-000002", "CARD-0001", "4321", (2026, 9, 12, 20, 40), "StreamFlix Andina",
        "15.99", "USD", _CONFIRMED, "US"),
    _tx("TX-000003", "CARD-0001", "4321", (2026, 9, 20, 14, 32), "Aerolínea Cóndor del Sur",
        "1250000.00", "COP", TransactionStatus.PENDING),
    _tx("TX-000004", "CARD-0001", "4321", (2026, 9, 25, 11, 5), "Farmacia Vida Plena",
        "42000.00", "COP", TransactionStatus.REVERSED),
    _tx("TX-000005", "CARD-0001", "4321", (2026, 10, 2, 18, 20), "Café Montaña Azul",
        "12500.00", "COP", _CONFIRMED),
    _tx("TX-000006", "CARD-0002", "8765", (2026, 9, 18, 22, 10), "Tienda Online Mercurio",
        "320000.00", "COP", _CONFIRMED),
    _tx("TX-000007", "CARD-0003", "1234", (2026, 9, 8, 7, 45), "Gasolinera El Páramo",
        "98000.00", "COP", _CONFIRMED),
    _tx("TX-000008", "CARD-0003", "1234", (2026, 9, 22, 13, 0), "Librería Letras Andinas",
        "64000.00", "COP", _CONFIRMED),
    _tx("TX-000009", "CARD-0004", "5555", (2026, 8, 30, 16, 30), "Restaurante Fogón Criollo",
        "75000.00", "COP", _CONFIRMED),
    _tx("TX-000010", "CARD-0001", "4321", (2026, 6, 1, 10, 0), "Hotel Pacífico Sur",
        "300000.00", "COP", _CONFIRMED, "US"),
    _tx("TX-000011", "CARD-0001", "4321", (2026, 10, 5, 16, 45), "Electro Hogar Andes",
        "800000.00", "COP", _CONFIRMED),
)  # fmt: skip


def seed_transactions(repository: SqlAlchemyTransactionRepository) -> None:
    """Inserta las transacciones de la semilla en la tarjeta indicada por `card_id`."""
    for transaction in SEED_TRANSACTIONS:
        repository.add(transaction.card_id, transaction)
