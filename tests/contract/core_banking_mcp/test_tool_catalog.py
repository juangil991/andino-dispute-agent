"""Snapshot del catálogo de herramientas del servidor `core_banking_mcp` (specs 001 y 002 §7)."""

import anyio
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import Tool

from core_banking_mcp.config import CoreSettings
from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    BuscarClienteOut,
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
    tools = _list_tools()
    assert [t.name for t in tools] == ["buscar_cliente", "verificar_identidad"]
    buscar, verificar = tools

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
