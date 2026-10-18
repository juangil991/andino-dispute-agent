"""Integración del adaptador MCP por stdio del agente (AC-007-18, AC-007-23)."""

import os
import sys
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

_SLOW_SERVER = Path(__file__).resolve().parents[3] / "fakes" / "slow_mcp_server.py"


def _slow_adapter(sleep_seconds: float, timeout: float) -> McpStdioBankingAdapter:
    return McpStdioBankingAdapter(
        command=sys.executable,
        args=[str(_SLOW_SERVER), str(sleep_seconds)],
        env={**os.environ},
        call_timeout_seconds=timeout,
    )


# Regla: RN-007-21 — Si una herramienta devuelve `INTERNAL`, no responde a tiempo o devuelve una
#   respuesta que no cumple el esquema, el agente no resuelve por criterio propio y deriva.
# AC-007-23 · Art. 10 (el tiempo límite se traduce en un error de indisponibilidad)
async def test_ac_007_23_mcp_adapter__timeout__raises_unavailable() -> None:
    """AC-007-23: una herramienta que tarda más que el tiempo límite lanza indisponibilidad."""
    adapter = _slow_adapter(sleep_seconds=5, timeout=0.5)
    await adapter.open()
    try:
        with pytest.raises(BankingToolUnavailableError):
            await adapter.search_customer("conv-slow", document="D-1001")
    finally:
        await adapter.close()


# Regla: RN-007-21 — Si una herramienta devuelve `INTERNAL`, no responde a tiempo o devuelve una
#   respuesta que no cumple el esquema, el agente no resuelve por criterio propio y deriva.
# AC-007-23 · Art. 10 (una respuesta fuera de esquema se traduce en indisponibilidad)
async def test_ac_007_23_mcp_adapter__schema_violation__raises_unavailable() -> None:
    """AC-007-23: una salida de iniciar_disputa sin dispute_id lanza indisponibilidad."""
    adapter = _slow_adapter(sleep_seconds=0, timeout=10)
    await adapter.open()
    try:
        with pytest.raises(BankingToolUnavailableError):
            await adapter.open_dispute("conv-bad", "TX-000001", "UNRECOGNIZED_CHARGE", "key-1")
    finally:
        await adapter.close()


# Regla: RN-007-12 — Si `iniciar_disputa` devuelve `DISPUTE_ALREADY_OPEN`, el agente no
#   reintenta ni deriva: informa la disputa existente.
# AC-007-18 · Art. 10 (el adaptador expone el dispute_id existente)
async def test_ac_007_18_mcp_adapter__dispute_already_open__exposes_existing_id(
    tmp_path: Path,
) -> None:
    """AC-007-18: el segundo iniciar_disputa sobre la misma transacción expone el id existente."""
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
        verification = await adapter.verify_identity(
            "conv-dup", "C-0001", date(1990, 3, 15), date(2008, 4, 20)
        )
        first = await adapter.open_dispute("conv-dup", "TX-000001", "UNRECOGNIZED_CHARGE", "k-1")
        with pytest.raises(BankingToolError) as raised:
            await adapter.open_dispute("conv-dup", "TX-000001", "UNRECOGNIZED_CHARGE", "k-2")
    finally:
        await adapter.close()

    assert verification.verified is True
    assert first.status == "OPEN"
    assert first.transaction.transaction_id == "TX-000001"
    assert raised.value.code == "DISPUTE_ALREADY_OPEN"
    assert raised.value.retryable is False
    assert raised.value.existing_dispute_id == first.dispute_id
