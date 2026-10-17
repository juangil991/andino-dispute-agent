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

    assert sorted(t.name for t in tools.tools) == [
        "buscar_cliente",
        "consultar_transacciones",
        "verificar_identidad",
    ]
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


# Regla: RN-003-01 — la solicitud indica la tarjeta por sus últimos 4 dígitos (`card_last4`) y el
#   rango con `date_from` y `date_to` en formato ISO `AAAA-MM-DD`, ambos incluidos.
# Regla: RN-003-05 — entra en el rango si su fecha local en `America/Bogota` está entre
#   `date_from` y `date_to`, ambos incluidos (la transacción del 2 de octubre queda fuera).
# Regla: RN-003-11 — las transacciones se ordenan de la más reciente a la más antigua por
#   `occurred_at`.
# Regla: RN-003-12 — cada transacción devuelta contiene solo `transaction_id`, `occurred_at`,
#   `merchant`, `amount`, `currency`, `status`, `card_id` y `masked_card` (`**** 4321`).
# AC-003-01 · Art. 7 (consulta de transacciones por stdio real con las semillas)
async def test_ac_003_01_consultar_transacciones__stdio_server__lists_seeded_september(
    tmp_path: Path,
) -> None:
    """AC-003-01: por stdio real, tras verificar a C-0001, 4321 de septiembre lista 4 de 4."""
    with anyio.fail_after(30):
        async with (
            stdio_client(_params(tmp_path)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            verification = await session.call_tool(
                "verificar_identidad",
                {
                    "conversation_id": "conv-smoke-tx",
                    "customer_id": "C-0001",
                    "birth_date": "1990-03-15",
                    "document_issue_date": "2008-04-20",
                },
            )
            result = await session.call_tool(
                "consultar_transacciones",
                {
                    "conversation_id": "conv-smoke-tx",
                    "card_last4": "4321",
                    "date_from": "2026-09-01",
                    "date_to": "2026-09-30",
                },
            )

    assert verification.structuredContent is not None
    assert verification.structuredContent["verified"] is True
    assert not result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["refinement_required"] is False
    transactions = result.structuredContent["transactions"]
    assert [t["transaction_id"] for t in transactions] == [
        "TX-000004",
        "TX-000003",
        "TX-000002",
        "TX-000001",
    ]
    assert {t["masked_card"] for t in transactions} == {"**** 4321"}
    assert "4111111111114321" not in result.model_dump_json()


# Regla: RN-003-02 — una conversación sin verificación exitosa se rechaza con
#   `IDENTITY_NOT_VERIFIED`; la verificación no se traslada de otra conversación.
# AC-003-11 · Art. 7 (sin identificación no se muestra información)
async def test_ac_003_11_consultar_transacciones__stdio_server__unverified_conversation_is_rejected(
    tmp_path: Path,
) -> None:
    """AC-003-11: por stdio real, una conversación distinta a la verificada recibe el rechazo."""
    with anyio.fail_after(30):
        async with (
            stdio_client(_params(tmp_path)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            await session.call_tool(
                "verificar_identidad",
                {
                    "conversation_id": "conv-verified",
                    "customer_id": "C-0001",
                    "birth_date": "1990-03-15",
                    "document_issue_date": "2008-04-20",
                },
            )
            result = await session.call_tool(
                "consultar_transacciones",
                {
                    "conversation_id": "conv-other",
                    "card_last4": "4321",
                    "date_from": "2026-09-01",
                    "date_to": "2026-09-30",
                },
            )

    assert result.structuredContent is not None
    assert result.structuredContent["code"] == "IDENTITY_NOT_VERIFIED"
    assert result.structuredContent["retryable"] is False
    assert "transactions" not in result.structuredContent
    assert "TX-0000" not in result.model_dump_json()


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
