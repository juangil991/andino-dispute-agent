"""Integración del repositorio SQLAlchemy sobre SQLite en memoria (AC-001-02, AC-001-03)."""

from datetime import date

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.identity_builder import IdentityBuilder

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
    repo.add(customer, identity=IdentityBuilder().build())
    repo.add(
        CustomerBuilder().with_id("C-011").with_document("ZZ-999").build(),
        identity=IdentityBuilder().build(),
    )

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
    repo.add(customer, identity=IdentityBuilder().build())
    other = (
        CustomerBuilder()
        .with_id("C-021")
        .with_document("DOC-0002")
        .with_cards(Card("9999", status))
        .build()
    )
    repo.add(other, identity=IdentityBuilder().build())

    found = repo.find_matching(SearchCriteria.create(None, None, "4321"), 6)

    assert [(c.customer_id, [(k.last4, k.status) for k in c.cards]) for c in found] == [
        (customer.customer_id, [(k.last4, k.status) for k in customer.cards])
    ]


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
    repo.add(customer, {"2468": "4000000000002468"}, identity=IdentityBuilder().build())

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
    repo.add(
        CustomerBuilder().with_cards(Card("5555", CardStatus.BLOCKED)).build(),
        identity=IdentityBuilder().build(),
    )

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
        CustomerBuilder().with_id("C-050").with_name("José Álvarez").with_document("D-5").build(),
        identity=IdentityBuilder().build(),
    )
    repo.add(
        CustomerBuilder()
        .with_id("C-051")
        .with_name("José Álvarez Pérez")
        .with_document("D-6")
        .build(),
        identity=IdentityBuilder().build(),
    )

    found = repo.find_matching(SearchCriteria.create(None, query, None), 6)

    assert len(found) == expected


# Regla: RN-001-11 - los criterios presentes se combinan con AND.
# AC-001-08 · Art. 3
def test_ac_001_08_criteria_are_combined_with_and(repo: SqlAlchemyCustomerRepository) -> None:
    """AC-001-08: documento de un cliente + nombre de otro no devuelve resultados."""
    repo.add(
        CustomerBuilder().with_id("C-081").with_name("Ana Ruiz").with_document("D-1001").build(),
        identity=IdentityBuilder().build(),
    )
    repo.add(
        CustomerBuilder().with_id("C-082").with_name("Luis Mora").with_document("D-1002").build(),
        identity=IdentityBuilder().build(),
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
            CustomerBuilder().with_id(cid).with_name("Mismo Nombre").with_document(cid).build(),
            identity=IdentityBuilder().build(),
        )

    found = repo.find_matching(SearchCriteria.create(None, "Mismo Nombre", None), 6)

    assert [c.customer_id for c in found] == ["C-091", "C-092", "C-093"]


# Regla: RN-001-01 - el límite recorta el número de resultados (caracterización).
# AC-001-04 · Art. 3
def test_ac_001_04_limit_is_applied(repo: SqlAlchemyCustomerRepository) -> None:
    """AC-001-04: find_matching devuelve como máximo `limit` clientes, los primeros por id."""
    for cid in ("C-103", "C-101", "C-102"):
        repo.add(
            CustomerBuilder().with_id(cid).with_name("Mismo Nombre").with_document(cid).build(),
            identity=IdentityBuilder().build(),
        )

    found = repo.find_matching(SearchCriteria.create(None, "Mismo Nombre", None), 2)

    assert [c.customer_id for c in found] == ["C-101", "C-102"]


# Regla: RN-002-01 - las dos fechas registradas se guardan y se recuperan tal cual.
# AC-002-01 · Art. 3
def test_ac_002_01_find_identity_returns_registered_dates(
    repo: SqlAlchemyCustomerRepository,
) -> None:
    """AC-002-01: find_identity devuelve las fechas registradas del cliente."""
    identity = (
        IdentityBuilder()
        .with_birth_date(date(1990, 3, 15))
        .with_issue_date(date(2008, 4, 20))
        .build()
    )
    repo.add(CustomerBuilder().with_id("C-001").build(), identity=identity)

    assert repo.find_identity("C-001") == identity


# Regla: RN-002-03 - un customer_id inexistente no tiene fechas registradas que comparar.
# AC-002-04 · Art. 3
def test_ac_002_04_find_identity_unknown_customer_returns_none(
    repo: SqlAlchemyCustomerRepository,
) -> None:
    """AC-002-04: find_identity de un customer_id inexistente devuelve None."""
    repo.add(CustomerBuilder().with_id("C-001").build(), identity=IdentityBuilder().build())

    assert repo.find_identity("C-999") is None


# Regla: RN-003-03 — Se consultan **todas** las tarjetas del cliente verificado en la conversación que terminan en `card_last4`, **sea cual sea su estado** (activa, bloqueada, cancelada); sus transacciones se devuelven juntas en una sola lista.  # noqa: E501
# Regla: RN-003-12 — Cada transacción devuelta contiene **solo**: `transaction_id`, `occurred_at`, `merchant`, `amount`, `currency`, `status`, `card_id` (identificador opaco de la tarjeta en el core, no derivado de su número) y `masked_card`.  # noqa: E501
# AC-003-05 · Art. 3
def test_ac_003_05_add_assigns_distinct_card_refs_to_same_last4_cards(
    repo: SqlAlchemyCustomerRepository, session: Session
) -> None:
    """AC-003-05: dos tarjetas con el mismo last4 reciben card_ref distintos y consecutivos."""
    repo.add(
        CustomerBuilder()
        .with_id("C-0001")
        .with_document("D-3001")
        .with_cards(Card("4321", CardStatus.ACTIVE), Card("4321", CardStatus.BLOCKED))
        .build(),
        identity=IdentityBuilder().build(),
    )
    repo.add(
        CustomerBuilder()
        .with_id("C-0002")
        .with_document("D-3002")
        .with_cards(Card("1234", CardStatus.ACTIVE))
        .build(),
        identity=IdentityBuilder().build(),
    )

    cards = session.scalars(select(CardRow).order_by(CardRow.card_id)).all()

    assert [c.card_ref for c in cards] == ["CARD-0001", "CARD-0002", "CARD-0003"]
    assert [c.last4 for c in cards] == ["4321", "4321", "1234"]


# Soporte de tests: la columna card_ref es única a nivel de base de datos · Art. 3
def test_card_ref_column_is_unique(session: Session) -> None:
    """Soporte: insertar dos tarjetas con el mismo card_ref viola la unicidad."""
    session.add(
        CustomerRow(
            customer_id="C-1",
            full_name="A",
            full_name_normalized="a",
            document="D-1",
            document_normalized="d-1",
            birth_date=date(1990, 1, 1),
            document_issue_date=date(2010, 1, 1),
            cards=[
                CardRow(pan="1", last4="1111", status="ACTIVE", card_ref="CARD-0001"),
                CardRow(pan="2", last4="2222", status="ACTIVE", card_ref="CARD-0001"),
            ],
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


# Soporte de tests: create_schema crea la tabla transactions del plan §4 · Art. 3
def test_create_schema_creates_transactions_table_with_plan_columns() -> None:
    """Soporte: la tabla transactions tiene las columnas e índice del plan §4."""
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("transactions")}
    index_columns = [tuple(i["column_names"]) for i in inspector.get_indexes("transactions")]

    assert columns == {
        "transaction_id",
        "card_id",
        "occurred_at",
        "merchant",
        "amount_minor",
        "currency",
        "status",
        "merchant_country",
    }
    assert ("card_id", "occurred_at") in index_columns


# Regla: RN-002-14 - las fechas no salen en los resultados de búsqueda (mínima exposición).
# AC-002-14 · Art. 7
def test_ac_002_14_find_matching_entities_do_not_expose_dates(
    repo: SqlAlchemyCustomerRepository,
) -> None:
    """AC-002-14: la entidad Customer devuelta por find_matching no tiene fechas."""
    customer = CustomerBuilder().with_id("C-001").with_document("D-1").build()
    repo.add(customer, identity=IdentityBuilder().build())

    found = repo.find_matching(SearchCriteria.create("D-1", None, None), 6)

    assert len(found) == 1
    assert not hasattr(found[0], "birth_date")
    assert not hasattr(found[0], "document_issue_date")


# Regla: RN-007-31 — Cada cliente devuelto por `buscar_cliente` incorpora `cards`: lista de
# `{card_id, masked_card}` de sus tarjetas en cualquier estado, en el mismo orden que
# `masked_cards`, que no cambia. `card_id` es el mismo identificador opaco que usan
# `consultar_transacciones` y `bloquear_tarjeta`. No incluye el estado ni el número de la tarjeta.
# AC-007-32 · Art. 3
def test_ac_007_32_customer_repository__cards__expose_card_ref_as_card_id(
    repo: SqlAlchemyCustomerRepository,
) -> None:
    """AC-007-32: find_matching devuelve cada Card con card_id igual a su card_ref, en orden."""
    customer = (
        CustomerBuilder()
        .with_id("C-020")
        .with_document("DOC-020")
        .with_cards(Card("4321", CardStatus.ACTIVE), Card("8765", CardStatus.BLOCKED))
        .build()
    )
    repo.add(customer, identity=IdentityBuilder().build())

    found = repo.find_matching(SearchCriteria.create("DOC-020", None, None), 6)

    assert [(c.last4, c.card_id) for c in found[0].cards] == [
        ("4321", "CARD-0001"),
        ("8765", "CARD-0002"),
    ]
