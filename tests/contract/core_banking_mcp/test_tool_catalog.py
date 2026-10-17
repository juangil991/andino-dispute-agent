"""Snapshot del catálogo de herramientas del servidor `core_banking_mcp` (specs 001 y 002 §7)."""

import anyio
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import Tool

from core_banking_mcp.config import CoreSettings
from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    BuscarClienteOut,
    ConsultarTransaccionesOut,
    VerificarIdentidadOut,
)
from core_banking_mcp.server import build_server


def _list_tools() -> list[Tool]:
    server = build_server(CoreSettings(database_url="sqlite://", seed_on_start=False))

    async def run() -> list[Tool]:
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            return (await session.list_tools()).tools

    return anyio.run(run)


# Regla: RN-002-01 — la solicitud aporta customer_id, birth_date y document_issue_date (parte de
#   RN-002-01 que verifica este snapshot: los campos de entrada del catálogo); el catálogo expone
#   solo las herramientas declaradas en spec §7.
# AC-002-01 · Art. 7 (mínima exposición)
def test_ac_002_01_catalog_exposes_buscar_cliente_and_verificar_identidad() -> None:
    """AC-002-01: list_tools devuelve solo buscar_cliente y verificar_identidad con sus esquemas."""
    tools = {t.name: t for t in _list_tools()}
    assert sorted(tools) == ["buscar_cliente", "consultar_transacciones", "verificar_identidad"]
    buscar, verificar = tools["buscar_cliente"], tools["verificar_identidad"]

    assert set(buscar.inputSchema["properties"]) == {
        "conversation_id",
        "document",
        "full_name",
        "card_last4",
    }
    assert not buscar.inputSchema.get("required")
    assert "bligatorio" in buscar.inputSchema["properties"]["conversation_id"]["description"]

    assert buscar.outputSchema is not None
    expected = BuscarClienteOut.model_json_schema()
    assert buscar.outputSchema["properties"] == expected["properties"]
    assert buscar.outputSchema["$defs"]["CustomerMatchOut"]["additionalProperties"] is False

    assert set(verificar.inputSchema["properties"]) == {
        "conversation_id",
        "customer_id",
        "birth_date",
        "document_issue_date",
    }
    assert not verificar.inputSchema.get("required")
    assert "bligatorio" in verificar.inputSchema["properties"]["conversation_id"]["description"]

    assert verificar.outputSchema is not None
    expected_out = VerificarIdentidadOut.model_json_schema()
    assert verificar.outputSchema["properties"] == expected_out["properties"]
    assert verificar.outputSchema["additionalProperties"] is False


# Regla: RN-003-12 — cada transacción devuelta contiene solo: `transaction_id`, `occurred_at`,
#   `merchant`, `amount`, `currency`, `status`, `card_id` y `masked_card` (parte de RN-003-12 que
#   verifica este snapshot: los campos del esquema de salida, sin campos extra); el catálogo
#   expone solo las herramientas declaradas en spec §7.
# AC-003-14 · Art. 7 (mínima exposición)
def test_ac_003_14_catalog_exposes_consultar_transacciones_with_spec_schemas() -> None:
    """AC-003-14: list_tools incluye consultar_transacciones con esquemas de la spec 003 §7."""
    tools = {t.name: t for t in _list_tools()}
    assert sorted(tools) == ["buscar_cliente", "consultar_transacciones", "verificar_identidad"]
    consultar = tools["consultar_transacciones"]

    properties = consultar.inputSchema["properties"]
    assert set(properties) == {"conversation_id", "card_last4", "date_from", "date_to"}
    assert not consultar.inputSchema.get("required")
    assert all(properties[name].get("description") for name in properties)
    assert "bligatorio" in properties["conversation_id"]["description"]

    assert consultar.outputSchema is not None
    expected = ConsultarTransaccionesOut.model_json_schema()
    assert consultar.outputSchema["properties"] == expected["properties"]
    assert consultar.outputSchema["additionalProperties"] is False
    assert consultar.outputSchema["$defs"]["TransactionItemOut"]["additionalProperties"] is False
