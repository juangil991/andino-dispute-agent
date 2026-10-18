"""Servidor MCP mínimo por stdio para probar tiempo límite y salidas inválidas del adaptador.

Soporte de tests: `python tests/fakes/slow_mcp_server.py [segundos]`. `buscar_cliente` duerme los
segundos indicados; `iniciar_disputa` devuelve una salida sin `dispute_id`.
"""

import sys
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

_SLEEP_SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0

mcp = FastMCP("slow-core")


@mcp.tool()
def buscar_cliente(conversation_id: str, document: str | None = None) -> dict[str, Any]:
    """Responde tras dormir más que el tiempo límite del cliente."""
    time.sleep(_SLEEP_SECONDS)
    return {"customers": [], "refinement_required": False}


@mcp.tool()
def iniciar_disputa(
    conversation_id: str, transaction_id: str, reason: str, idempotency_key: str
) -> dict[str, Any]:
    """Devuelve una salida inválida: no trae `dispute_id`."""
    return {"status": "OPEN", "reason": reason}


if __name__ == "__main__":
    mcp.run(transport="stdio")
