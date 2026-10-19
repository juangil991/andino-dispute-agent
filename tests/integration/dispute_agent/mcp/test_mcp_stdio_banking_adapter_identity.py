"""Integración del adaptador MCP por stdio con `verificar_identidad` (AC-007-49, AC-007-54)."""

import os
import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest

from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolUnavailableError,
)
from dispute_agent.infrastructure.outbound.mcp.mcp_stdio_banking_adapter import (
    McpStdioBankingAdapter,
)

_NO_VERIFIED_SERVER = textwrap.dedent(
    """
    from typing import Any

    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("no-verified-core")


    @mcp.tool()
    def verificar_identidad(
        conversation_id: str,
        customer_id: str,
        birth_date: str,
        document_issue_date: str,
    ) -> dict[str, Any]:
        return {"attempts_remaining": 2}


    if __name__ == "__main__":
        mcp.run(transport="stdio")
    """
)


# Regla: RN-007-40 — Fechas inválidas no consumen intento: el core responde `INVALID_INPUT` y el
#   agente vuelve a preguntar.
# AC-007-49 · Art. 10 (el adaptador traduce el sobre de error del core)
async def test_ac_007_49_mcp_adapter__verify_identity_invalid_input__raises_banking_tool_error(
    tmp_path: Path,
) -> None:
    """AC-007-49: expedición anterior al nacimiento ⇒ INVALID_INPUT no reintentable."""
    adapter = McpStdioBankingAdapter(
        command=sys.executable,
        args=["-m", "core_banking_mcp.server"],
        env={
            **os.environ,
            "CORE_DATABASE_URL": f"sqlite:///{(tmp_path / 'core.db').as_posix()}",
        },
        call_timeout_seconds=20,
    )
    await adapter.open()
    try:
        with pytest.raises(BankingToolError) as raised:
            await adapter.verify_identity(
                "conv-invalid", "C-0001", date(1990, 3, 15), date(1980, 1, 1)
            )
    finally:
        await adapter.close()

    assert raised.value.code == "INVALID_INPUT"
    assert raised.value.retryable is False


# Regla: RN-007-21 — Una respuesta que no cumple el esquema no se resuelve por criterio propio:
#   se trata como indisponibilidad.
# AC-007-54 · Art. 10 (salida sin `verified` ⇒ indisponibilidad)
async def test_ac_007_54_mcp_adapter__verify_identity_without_verified__raises_unavailable(
    tmp_path: Path,
) -> None:
    """AC-007-54: una salida de verificar_identidad sin verified lanza indisponibilidad."""
    server = tmp_path / "no_verified_server.py"
    server.write_text(_NO_VERIFIED_SERVER, encoding="utf-8")
    adapter = McpStdioBankingAdapter(
        command=sys.executable,
        args=[str(server)],
        env={**os.environ},
        call_timeout_seconds=10,
    )
    await adapter.open()
    try:
        with pytest.raises(BankingToolUnavailableError):
            await adapter.verify_identity(
                "conv-bad", "C-0001", date(1990, 3, 15), date(2008, 4, 20)
            )
    finally:
        await adapter.close()
