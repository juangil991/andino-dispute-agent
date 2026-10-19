"""Fábrica de engine, sesiones y esquema."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core_banking_mcp.infrastructure.outbound.persistence.models.tables import Base


def create_engine_from_url(url: str) -> Engine:
    """Crea el engine; SQLite en memoria comparte una sola conexión."""
    if url in ("sqlite://", "sqlite:///:memory:"):
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def reset_schema(engine: Engine) -> None:
    """Recrea el esquema desde cero: `create_all` no altera tablas de una versión anterior."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
