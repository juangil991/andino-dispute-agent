"""Smoke test por stdio real del servidor core_banking_mcp (AC-001-01, AC-002-01, AC-002-05)."""

import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _params(tmp_path: Path) -> StdioServerParameters:
    env = {
        **os.environ,
        "CORE_DATABASE_URL": f"sqlite:///{(tmp_path / 'core.db').as_posix()}",
    }
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "core_banking_mcp.server"],
        env=env,
    )


# Regla: RN-002-02 — la verificación es exitosa solo si ambas fechas coinciden con las registradas.
# Regla: RN-002-01 — la solicitud aporta customer_id, birth_date y document_issue_date.
# Regla: RN-002-09 — la verificación exitosa deja a la conversación verificada.
# AC-002-01 · Art. 7 (verificación de identidad por stdio real)
async def test_ac_002_01_verificar_identidad__stdio_server__verifies_seeded_customer(
    tmp_path: Path,
) -> None:
    """AC-002-01: por stdio real, C-0001 con sus fechas queda verificado."""
    with anyio.fail_after(30):
        async with (
            stdio_client(_params(tmp_path)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool(
                "verificar_identidad",
                {
                    "conversation_id": "conv-smoke-id",
                    "customer_id": "C-0001",
                    "birth_date": "1990-03-15",
                    "document_issue_date": "2008-04-20",
                },
            )

    assert [t.name for t in tools.tools] == ["buscar_cliente", "verificar_identidad"]
    assert not result.isError
    assert result.structuredContent == {
        "verified": True,
        "attempts_remaining": 3,
        "escalation_required": False,
    }


# Regla: RN-002-04 — una conversación nueva con un dato incorrecto conserva 2 intentos.
# AC-002-05 · Art. 7 (fallo de verificación por stdio real)
async def test_ac_002_05_verificar_identidad__stdio_wrong_birth_date__two_attempts_remaining(
    tmp_path: Path,
) -> None:
    """AC-002-05: por stdio real, una fecha incorrecta devuelve verified=false y 2 restantes."""
    with anyio.fail_after(30):
        async with (
            stdio_client(_params(tmp_path)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "verificar_identidad",
                {
                    "conversation_id": "conv-smoke-fail",
                    "customer_id": "C-0001",
                    "birth_date": "1990-03-16",
                    "document_issue_date": "2008-04-20",
                },
            )

    assert not result.isError
    assert result.structuredContent == {
        "verified": False,
        "attempts_remaining": 2,
        "escalation_required": False,
    }


async def test_ac_001_01_buscar_cliente__stdio_server__finds_seeded_customer(
    tmp_path: Path,
) -> None:
    """AC-001-01: por stdio real, buscar D-1001 devuelve C-0001 con datos enmascarados."""
    params = _params(tmp_path)

    with anyio.fail_after(30):
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "buscar_cliente",
                {"conversation_id": "conv-smoke", "document": "D-1001"},
            )

    assert not result.isError
    assert result.structuredContent is not None
    customer = result.structuredContent["customers"][0]
    assert customer["customer_id"] == "C-0001"
    assert customer["masked_document"] == "****01"
    assert customer["masked_cards"] == ["**** 4321", "**** 8765"]
    assert "D-1001" not in result.model_dump_json()
