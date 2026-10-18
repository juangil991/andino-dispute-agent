"""El atributo `server.mcp` es perezoso y expone las cinco herramientas (Art. 4)."""

import pytest
from mcp.server.fastmcp import FastMCP

from core_banking_mcp import server


# Invariante: Art. 4 — el cableado vive solo en server.py y no hay efectos al importar.
# AC-002-01 · Art. 4 (soporte de plan §1/§2)
def test_ac_002_01_server_mcp_attribute_is_lazy_and_exposes_all_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invariante Art. 4: importar server no construye nada; mcp único con cinco tools."""
    monkeypatch.setenv("CORE_DATABASE_URL", "sqlite://")
    monkeypatch.setattr(server, "_mcp", None)

    assert server._mcp is None  # importar el módulo no construyó el servidor
    first = server.mcp  # type: ignore[attr-defined]
    assert isinstance(first, FastMCP)
    assert server.mcp is first  # type: ignore[attr-defined]
    names = sorted(tool.name for tool in first._tool_manager.list_tools())
    assert names == [
        "bloquear_tarjeta",
        "buscar_cliente",
        "consultar_transacciones",
        "iniciar_disputa",
        "verificar_identidad",
    ]

    with pytest.raises(AttributeError):
        server.otro_nombre  # noqa: B018  # type: ignore[attr-defined]
