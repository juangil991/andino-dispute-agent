"""Snapshot del catálogo de herramientas del servidor `core_banking_mcp` (spec 001 §7)."""

import anyio
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import Tool

from core_banking_mcp.config import CoreSettings
from core_banking_mcp.infrastructure.inbound.mcp.schemas import BuscarClienteOut
from core_banking_mcp.server import build_server


def _list_tools() -> list[Tool]:
    server = build_server(CoreSettings(database_url="sqlite://", seed_on_start=False))

    async def run() -> list[Tool]:
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            return (await session.list_tools()).tools

    return anyio.run(run)


# Regla: RN-001-10 — el catálogo expone solo `buscar_cliente` con el esquema de la spec §7.
# AC-001-01 · Art. 1 (mínima exposición); AC-001-09 · mcp-testing §7 (snapshot del catálogo)
def test_ac_001_01_catalog_exposes_only_buscar_cliente_with_spec_schema() -> None:
    """AC-001-01: list_tools devuelve solo buscar_cliente con la entrada y salida de la spec."""
    tools = _list_tools()
    assert [t.name for t in tools] == ["buscar_cliente"]
    tool = tools[0]

    assert set(tool.inputSchema["properties"]) == {
        "conversation_id",
        "document",
        "full_name",
        "card_last4",
    }
    assert not tool.inputSchema.get("required")
    assert "bligatorio" in tool.inputSchema["properties"]["conversation_id"]["description"]

    assert tool.outputSchema is not None
    expected = BuscarClienteOut.model_json_schema()
    assert tool.outputSchema["properties"] == expected["properties"]
    assert tool.outputSchema["$defs"]["CustomerMatchOut"]["additionalProperties"] is False
