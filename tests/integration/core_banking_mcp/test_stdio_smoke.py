"""Smoke test por stdio real del servidor core_banking_mcp (AC-001-01)."""

import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_ac_001_01_buscar_cliente__stdio_server__finds_seeded_customer(
    tmp_path: Path,
) -> None:
    """AC-001-01: por stdio real, buscar D-1001 devuelve C-0001 con datos enmascarados."""
    env = {
        **os.environ,
        "CORE_DATABASE_URL": f"sqlite:///{(tmp_path / 'core.db').as_posix()}",
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "core_banking_mcp.server"],
        env=env,
    )

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
