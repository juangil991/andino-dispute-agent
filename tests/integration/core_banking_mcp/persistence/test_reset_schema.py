"""Regeneración del esquema del core al arrancar (la base de una versión anterior no se migra)."""

from sqlalchemy import inspect, text

from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    reset_schema,
)


# Regla: Art. 3 (persistencia) - el esquema siempre coincide con los modelos actuales.
# Soporte de tests: regresión de `consultar_transacciones` → INTERNAL por esquema viejo
def test_reset_schema_replaces_a_stale_transactions_table() -> None:
    engine = create_engine_from_url("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE transactions (transaction_id VARCHAR PRIMARY KEY)"))

    reset_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("transactions")}
    assert "merchant_country" in columns
