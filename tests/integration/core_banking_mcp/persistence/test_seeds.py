"""Semillas ficticias de core_banking_mcp (plan §4; habilita AC-001-01 en el smoke test)."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core_banking_mcp.domain.models.search import SearchCriteria
from core_banking_mcp.domain.models.transaction import BogotaDateRange
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    CardRow,
    CustomerRow,
    DisputeRow,
    TransactionRow,
)
from core_banking_mcp.infrastructure.outbound.persistence.seeds.customers import (
    SEED_CUSTOMERS,
    seed_database,
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

    seed_database(
        repo, SqlAlchemyTransactionRepository(session), SqlAlchemyDisputeRepository(session)
    )
    seed_database(
        repo, SqlAlchemyTransactionRepository(session), SqlAlchemyDisputeRepository(session)
    )

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


# Regla: RN-002-01 - cada semilla tiene fecha de nacimiento y de emisión.
# AC-002-01 · Art. 1 (datos ficticios)
def test_ac_002_01_seeded_customers_have_registered_dates() -> None:
    """AC-002-01: las 7 semillas tienen identidad y C-0001/C-0002 las fechas de la spec."""
    session = _new_session()
    repo = SqlAlchemyCustomerRepository(session)

    seed_database(
        repo, SqlAlchemyTransactionRepository(session), SqlAlchemyDisputeRepository(session)
    )

    for i in range(1, 8):
        assert repo.find_identity(f"C-000{i}") is not None
    first = repo.find_identity("C-0001")
    second = repo.find_identity("C-0002")
    assert first is not None
    assert (first.birth_date, first.document_issue_date) == (date(1990, 3, 15), date(2008, 4, 20))
    assert second is not None
    assert (second.birth_date, second.document_issue_date) == (date(1985, 7, 2), date(2003, 8, 10))


# Soporte de tests: semillas ficticias reproducibles · Art. 1
# Invariante: Art. 1 — datos semilla ficticios y reproducibles (se siembran una sola vez).
# AC-003-01 · Art. 1
def test_seed_database_seeds_transactions_once() -> None:
    """Soporte: las 11 transacciones del plan §4 se siembran una sola vez, con sus card_ref."""
    session = _new_session()
    customers = SqlAlchemyCustomerRepository(session)
    transactions = SqlAlchemyTransactionRepository(session)

    seed_database(customers, transactions, SqlAlchemyDisputeRepository(session))
    seed_database(customers, transactions, SqlAlchemyDisputeRepository(session))

    assert session.scalar(select(func.count()).select_from(TransactionRow)) == 11
    refs = {
        row.card_ref: row.last4
        for row in session.scalars(select(CardRow).order_by(CardRow.card_ref))
    }
    assert refs == {
        "CARD-0001": "4321",
        "CARD-0002": "8765",
        "CARD-0003": "1234",
        "CARD-0004": "5555",
    }
    start, end = BogotaDateRange(date(2026, 9, 1), date(2026, 9, 30)).utc_bounds()
    found = transactions.find_transactions(["CARD-0001"], start, end, 50)
    assert [t.transaction_id for t in found] == ["TX-000004", "TX-000003", "TX-000002", "TX-000001"]


# Soporte de tests: semillas ficticias reproducibles (idempotentes) · Art. 1
# Invariante: Art. 1 — datos semilla ficticios y reproducibles; la consulta de disputa OPEN
# sobre las semillas solo confirma su estado (OPEN frente a CLOSED y REJECTED).
# AC-004-07 · Art. 1
def test_support_seed_database_seeds_disputes_once() -> None:
    """Soporte: las 3 disputas del plan §4 se siembran una sola vez."""
    session = _new_session()
    customers = SqlAlchemyCustomerRepository(session)
    transactions = SqlAlchemyTransactionRepository(session)
    disputes = SqlAlchemyDisputeRepository(session)

    seed_database(customers, transactions, disputes)
    seed_database(customers, transactions, disputes)

    rows = session.scalars(select(DisputeRow).order_by(DisputeRow.dispute_id)).all()
    assert [(r.dispute_id, r.status, r.transaction_id) for r in rows] == [
        ("DSP-000001", "OPEN", "TX-000002"),
        ("DSP-000002", "CLOSED", "TX-000006"),
        ("DSP-000003", "REJECTED", "TX-000008"),
    ]
    opened = disputes.find_open_by_transaction("TX-000002")
    assert opened is not None
    assert opened.dispute_id == "DSP-000001"
    assert disputes.find_open_by_transaction("TX-000006") is None
    assert disputes.find_open_by_transaction("TX-000008") is None
