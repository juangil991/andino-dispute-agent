"""Composición del servidor MCP del core bancario (único lugar de cableado, Art. 4)."""

from pathlib import Path

from mcp.server.fastmcp import FastMCP
from sqlalchemy.engine import make_url

from core_banking_mcp.application.use_cases.block_card import BlockCard
from core_banking_mcp.application.use_cases.list_card_transactions import ListCardTransactions
from core_banking_mcp.application.use_cases.open_dispute import OpenDispute
from core_banking_mcp.application.use_cases.search_customers import SearchCustomers
from core_banking_mcp.application.use_cases.verify_identity import VerifyIdentity
from core_banking_mcp.config import CoreSettings
from core_banking_mcp.infrastructure.inbound.mcp.card_tools import register_card_tools
from core_banking_mcp.infrastructure.inbound.mcp.dispute_tools import register_dispute_tools
from core_banking_mcp.infrastructure.inbound.mcp.identity_tools import register_identity_tools
from core_banking_mcp.infrastructure.inbound.mcp.tools import register_tools
from core_banking_mcp.infrastructure.inbound.mcp.transaction_tools import (
    register_transaction_tools,
)
from core_banking_mcp.infrastructure.outbound.audit.json_audit_log import JsonAuditLog
from core_banking_mcp.infrastructure.outbound.clock.system_clock import SystemClock
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.seeds.customers import seed_database
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_card_repository import (
    SqlAlchemyCardRepository,
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
from core_banking_mcp.infrastructure.outbound.verification.in_memory_verification_store import (
    InMemoryConversationVerificationStore,
)

_mcp: FastMCP | None = None


def _ensure_sqlite_directory(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)


def build_server(settings: CoreSettings | None = None) -> FastMCP:
    """Compone engine, repositorio, auditoría, caso de uso y herramientas MCP."""
    settings = settings or CoreSettings()
    _ensure_sqlite_directory(settings.database_url)
    engine = create_engine_from_url(settings.database_url)
    create_schema(engine)
    session = session_factory(engine)()
    repository = SqlAlchemyCustomerRepository(session)
    if settings.seed_on_start:
        seed_database(
            repository,
            SqlAlchemyTransactionRepository(session),
            SqlAlchemyDisputeRepository(session),
        )
    search_customers = SearchCustomers(repository, JsonAuditLog(), SystemClock())
    store = InMemoryConversationVerificationStore()
    verify_identity = VerifyIdentity(repository, store, JsonAuditLog(), SystemClock())
    list_card_transactions = ListCardTransactions(
        SqlAlchemyTransactionRepository(session), store, JsonAuditLog(), SystemClock()
    )
    open_dispute = OpenDispute(
        SqlAlchemyTransactionRepository(session),
        SqlAlchemyDisputeRepository(session),
        store,
        JsonAuditLog(),
        SystemClock(),
    )
    block_card = BlockCard(SqlAlchemyCardRepository(session), store, JsonAuditLog(), SystemClock())
    mcp = FastMCP("core_banking_mcp")
    register_tools(mcp, search_customers)
    register_identity_tools(mcp, verify_identity)
    register_transaction_tools(mcp, list_card_transactions)
    register_dispute_tools(mcp, open_dispute)
    register_card_tools(mcp, block_card)
    return mcp


def __getattr__(name: str) -> FastMCP:
    """Atributo perezoso `mcp`: construye el servidor una sola vez al primer acceso."""
    global _mcp
    if name != "mcp":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _mcp is None:
        _mcp = build_server()
    return _mcp


def main() -> None:
    build_server(CoreSettings()).run("stdio")


if __name__ == "__main__":
    main()
