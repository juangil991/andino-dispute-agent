"""Composición del servidor MCP del core bancario (único lugar de cableado, Art. 4)."""

from pathlib import Path

from mcp.server.fastmcp import FastMCP
from sqlalchemy.engine import make_url

from core_banking_mcp.application.use_cases.search_customers import SearchCustomers
from core_banking_mcp.config import CoreSettings
from core_banking_mcp.infrastructure.inbound.mcp.tools import register_tools
from core_banking_mcp.infrastructure.outbound.audit.json_audit_log import JsonAuditLog
from core_banking_mcp.infrastructure.outbound.clock.system_clock import SystemClock
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.seeds.customers import seed_database
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)


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
        seed_database(repository)
    search_customers = SearchCustomers(repository, JsonAuditLog(), SystemClock())
    mcp = FastMCP("core_banking_mcp")
    register_tools(mcp, search_customers)
    return mcp


def main() -> None:
    build_server(CoreSettings()).run("stdio")


if __name__ == "__main__":
    main()
