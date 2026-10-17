"""Semillas ficticias (plan §4, Art. 1). Datos fijos, sin aleatoriedad."""

from datetime import date

from core_banking_mcp.domain.models.customer import Card, CardStatus, Customer
from core_banking_mcp.domain.models.identity import IdentityRecord
from core_banking_mcp.domain.models.search import SearchCriteria
from core_banking_mcp.infrastructure.outbound.persistence.seeds.transactions import (
    seed_transactions,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_transaction_repository import (
    SqlAlchemyTransactionRepository,
)

# Cada semilla: (cliente, PAN completo ficticio por last4, identidad ficticia).
SEED_CUSTOMERS: tuple[tuple[Customer, dict[str, str], IdentityRecord], ...] = (
    (
        Customer(
            "C-0001",
            "Laura Méndez",
            "D-1001",
            (Card("4321", CardStatus.ACTIVE), Card("8765", CardStatus.BLOCKED)),
        ),
        {"4321": "4111111111114321", "8765": "5500000000008765"},
        IdentityRecord(date(1990, 3, 15), date(2008, 4, 20)),
    ),
    (
        Customer("C-0002", "Pedro Ríos", "D-1002", (Card("1234", CardStatus.ACTIVE),)),
        {"1234": "4000000000001234"},
        IdentityRecord(date(1985, 7, 2), date(2003, 8, 10)),
    ),
    (
        Customer("C-0003", "Ana Torres", "D-2001", ()),
        {},
        IdentityRecord(date(1992, 11, 30), date(2010, 12, 1)),
    ),
    (
        Customer("C-0004", "Ana Torres", "D-2002", ()),
        {},
        IdentityRecord(date(1988, 1, 9), date(2006, 2, 14)),
    ),
    (
        Customer("C-0005", "José Álvarez", "D-3001", ()),
        {},
        IdentityRecord(date(1979, 5, 21), date(1997, 6, 30)),
    ),
    (
        Customer("C-0006", "José Álvarez Pérez", "D-3002", ()),
        {},
        IdentityRecord(date(1995, 9, 12), date(2013, 10, 5)),
    ),
    (
        Customer("C-0007", "Marta Gil", "AB12", (Card("5555", CardStatus.CANCELLED),)),
        {"5555": "6011000000005555"},
        IdentityRecord(date(2000, 2, 29), date(2018, 3, 12)),
    ),
)


def seed_database(
    repository: SqlAlchemyCustomerRepository, transactions: SqlAlchemyTransactionRepository
) -> None:
    """Inserta las semillas (clientes y transacciones) solo si la base está vacía.

    "Vacía" se detecta buscando el primer cliente de la semilla por su documento
    (el repositorio no expone contar/listar); así se evita tocar el repositorio.
    """
    first = SEED_CUSTOMERS[0][0]
    if repository.find_matching(SearchCriteria.create(first.document, None, None), 1):
        return
    for customer, pans, identity in SEED_CUSTOMERS:
        repository.add(customer, pans, identity=identity)
    seed_transactions(transactions)
