"""Semillas ficticias de core_banking_mcp (plan §4; habilita AC-001-01 en el smoke test)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core_banking_mcp.domain.models.search import SearchCriteria
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    CardRow,
    CustomerRow,
)
from core_banking_mcp.infrastructure.outbound.persistence.seeds.customers import (
    SEED_CUSTOMERS,
    seed_database,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)


def _new_session() -> Session:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    return session_factory(engine)()


# Regla: plan §4 - semillas fijas y ficticias; la inserción es idempotente.
# AC-001-01 · Art. 1 (datos ficticios)
def test_seed_database_is_idempotent_and_reproducible() -> None:
    """AC-001-01: las 7 semillas del plan §4 se insertan una sola vez, normalizadas."""
    session = _new_session()
    repo = SqlAlchemyCustomerRepository(session)

    seed_database(repo)
    seed_database(repo)

    assert len(SEED_CUSTOMERS) == 7
    assert session.scalar(select(func.count()).select_from(CustomerRow)) == 7
    assert session.scalar(select(func.count()).select_from(CardRow)) == 4

    ids = [r.customer_id for r in session.scalars(select(CustomerRow).order_by("customer_id"))]
    assert ids == [f"C-000{i}" for i in range(1, 8)]

    laura = repo.find_matching(SearchCriteria.create("d-1001", None, None), 6)
    assert [c.customer_id for c in laura] == ["C-0001"]
    assert [(c.last4, c.status.value) for c in laura[0].cards] == [
        ("4321", "ACTIVE"),
        ("8765", "BLOCKED"),
    ]
    row = session.scalars(select(CustomerRow).where(CustomerRow.customer_id == "C-0001")).one()
    assert row.full_name_normalized == "laura mendez"
    assert {c.pan for c in row.cards} == {"4111111111114321", "5500000000008765"}

    ana = repo.find_matching(SearchCriteria.create(None, "ana torres", None), 6)
    assert [c.customer_id for c in ana] == ["C-0003", "C-0004"]
