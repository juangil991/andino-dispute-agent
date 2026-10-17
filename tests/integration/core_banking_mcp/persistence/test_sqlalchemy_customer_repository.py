"""Integración del repositorio SQLAlchemy sobre SQLite en memoria (AC-001-02, AC-001-03)."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.fakes.customer_builder import CustomerBuilder

from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.search import SearchCriteria
from core_banking_mcp.domain.normalization import normalize_document, normalize_name
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    CardRow,
    CustomerRow,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    return session_factory(engine)()


@pytest.fixture
def repo(session: Session) -> SqlAlchemyCustomerRepository:
    return SqlAlchemyCustomerRepository(session)


# Regla: RN-001-02 - el documento se compara recortado y sin distinguir mayúsculas.
# AC-001-02 · Art. 3
def test_ac_001_02_document_match_is_trimmed_and_case_insensitive(
    repo: SqlAlchemyCustomerRepository,
) -> None:
    """AC-001-02: el documento coincide sin importar espacios ni mayúsculas (RN-001-02)."""
    customer = CustomerBuilder().with_id("C-010").with_document("ab-123 x").build()
    repo.add(customer)
    repo.add(CustomerBuilder().with_id("C-011").with_document("ZZ-999").build())

    criteria = SearchCriteria.create("  AB-123 X ", None, None)
    found = repo.find_matching(criteria, 6)

    assert found == [customer]


# Regla: RN-001-04 - la tarjeta coincide por últimos 4 sin importar su estado.
# AC-001-03 · Art. 3
@pytest.mark.parametrize("status", [CardStatus.ACTIVE, CardStatus.BLOCKED, CardStatus.CANCELLED])
def test_ac_001_03_card_last4_matches_any_card_status(
    repo: SqlAlchemyCustomerRepository, status: CardStatus
) -> None:
    """AC-001-03: los últimos 4 dígitos coinciden con tarjeta activa, bloqueada o cancelada."""
    customer = (
        CustomerBuilder()
        .with_id("C-020")
        .with_document("DOC-0001")
        .with_cards(Card("4321", status), Card("1111", status))
        .build()
    )
    repo.add(customer)
    other = (
        CustomerBuilder()
        .with_id("C-021")
        .with_document("DOC-0002")
        .with_cards(Card("9999", status))
        .build()
    )
    repo.add(other)

    found = repo.find_matching(SearchCriteria.create(None, None, "4321"), 6)

    assert found == [customer]


# Regla: RN-001-02 - columnas normalizadas calculadas con el dominio (riesgo plan §7).
# AC-001-02 · Art. 4
def test_ac_001_03_add_fills_normalized_columns_with_domain_functions(
    repo: SqlAlchemyCustomerRepository, session: Session
) -> None:
    """AC-001-02: add calcula las columnas normalizadas con las funciones del dominio."""
    customer = (
        CustomerBuilder()
        .with_id("C-030")
        .with_name("José Álvarez")
        .with_document(" ab-77 ")
        .with_cards(Card("2468", CardStatus.ACTIVE))
        .build()
    )
    repo.add(customer, {"2468": "4000000000002468"})

    row = session.scalars(select(CustomerRow)).one()
    assert row.full_name_normalized == normalize_name("José Álvarez")
    assert row.document_normalized == normalize_document(" ab-77 ")
    card = session.scalars(select(CardRow)).one()
    assert card.pan == "4000000000002468"
    assert card.last4 == "2468"


# Regla: RN-001-04 - el PAN no vive en el dominio; se usa uno sintético por defecto.
# AC-001-03 · Art. 1
def test_ac_001_03_add_uses_synthetic_pan_when_not_given(
    repo: SqlAlchemyCustomerRepository, session: Session
) -> None:
    """AC-001-03: sin PAN explícito se guarda uno sintético 000000000000 + last4."""
    repo.add(CustomerBuilder().with_cards(Card("5555", CardStatus.BLOCKED)).build())

    assert session.scalars(select(CardRow)).one().pan == "0000000000005555"


# Regla: RN-001-03 - el nombre debe coincidir completo (normalizado), no por prefijo ni parcial.
# AC-001-05 · Art. 3
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("José Álvarez", 1),
        ("jose alvarez", 1),
        ("JOSÉ ÁLVAREZ", 1),
        ("  José   Álvarez  ", 1),
        ("José", 0),
        ("José Álvarez2", 0),
        ("José Álvarez Pérez", 1),
    ],
    ids=[
        "exact",
        "no-accents-lowercase",
        "uppercase",
        "extra-spaces",
        "partial-first-name",
        "extra-suffix",
        "other-customer-full-name",
    ],
)
def test_ac_001_05_full_name_must_equal_registered_name(
    repo: SqlAlchemyCustomerRepository, query: str, expected: int
) -> None:
    """AC-001-05: el nombre completo debe ser igual al registrado, normalizado (RN-001-03)."""
    repo.add(
        CustomerBuilder().with_id("C-050").with_name("José Álvarez").with_document("D-5").build()
    )
    repo.add(
        CustomerBuilder()
        .with_id("C-051")
        .with_name("José Álvarez Pérez")
        .with_document("D-6")
        .build()
    )

    found = repo.find_matching(SearchCriteria.create(None, query, None), 6)

    assert len(found) == expected


# Regla: RN-001-11 - los criterios presentes se combinan con AND.
# AC-001-08 · Art. 3
def test_ac_001_08_criteria_are_combined_with_and(repo: SqlAlchemyCustomerRepository) -> None:
    """AC-001-08: documento de un cliente + nombre de otro no devuelve resultados."""
    repo.add(
        CustomerBuilder().with_id("C-081").with_name("Ana Ruiz").with_document("D-1001").build()
    )
    repo.add(
        CustomerBuilder().with_id("C-082").with_name("Luis Mora").with_document("D-1002").build()
    )

    mismatch = repo.find_matching(SearchCriteria.create("D-1001", "Luis Mora", None), 6)
    match = repo.find_matching(SearchCriteria.create("D-1002", "Luis Mora", None), 6)

    assert mismatch == []
    assert [c.customer_id for c in match] == ["C-082"]


# Regla: RN-001-01 - los resultados se ordenan por customer_id (caracterización).
# AC-001-04 · Art. 3
def test_ac_001_04_results_are_ordered_by_customer_id(repo: SqlAlchemyCustomerRepository) -> None:
    """AC-001-04: los resultados salen ordenados por customer_id ascendente."""
    for cid in ("C-093", "C-091", "C-092"):
        repo.add(
            CustomerBuilder().with_id(cid).with_name("Mismo Nombre").with_document(cid).build()
        )

    found = repo.find_matching(SearchCriteria.create(None, "Mismo Nombre", None), 6)

    assert [c.customer_id for c in found] == ["C-091", "C-092", "C-093"]


# Regla: RN-001-01 - el límite recorta el número de resultados (caracterización).
# AC-001-04 · Art. 3
def test_ac_001_04_limit_is_applied(repo: SqlAlchemyCustomerRepository) -> None:
    """AC-001-04: find_matching devuelve como máximo `limit` clientes, los primeros por id."""
    for cid in ("C-103", "C-101", "C-102"):
        repo.add(
            CustomerBuilder().with_id(cid).with_name("Mismo Nombre").with_document(cid).build()
        )

    found = repo.find_matching(SearchCriteria.create(None, "Mismo Nombre", None), 2)

    assert [c.customer_id for c in found] == ["C-101", "C-102"]
