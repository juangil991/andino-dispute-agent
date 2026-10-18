"""Smoke test por stdio real del servidor core_banking_mcp (AC-001/002/003/004)."""

import os
import sys
from datetime import datetime, timedelta
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
        "iniciar_disputa",
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


# Regla: RN-004-01 — La solicitud indica la transacción por el `transaction_id` que devuelve
#   `consultar_transacciones`, el motivo (`reason`) y una clave de reintento (`idempotency_key`)
#   generada por el consumidor.
# Regla: RN-004-11 — Una disputa nueva queda con `status = OPEN`, un `dispute_id` opaco y único que
#   no se deriva del número de la tarjeta, y `opened_at` igual al instante del reloj inyectado
#   expresado en ISO 8601 con la zona de Bogotá (`−05:00`). (Aquí el reloj es el real: se
#   comprueba formato y zona, no un valor fijo.)
# Regla: RN-004-12 — La respuesta exitosa contiene **solo** `dispute_id`, `status`, `opened_at`,
#   `reason` (el código) y `transaction`, con exactamente los campos de `TransactionItem` de la
#   spec 003 (RN-003-12): `transaction_id`, `occurred_at`, `merchant`, `amount`, `currency`,
#   `status`, `card_id` y `masked_card`.
# AC-004-01 · Art. 7 (apertura de disputa por stdio real con las semillas; base temporal limpia)
async def test_ac_004_01_iniciar_disputa__stdio_server__opens_dispute_on_seeded_transaction(
    tmp_path: Path,
) -> None:
    """AC-004-01: por stdio real, tras verificar a C-0001, TX-000001 queda con disputa OPEN."""
    with anyio.fail_after(30):
        async with (
            stdio_client(_params(tmp_path)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            await session.call_tool(
                "verificar_identidad",
                {
                    "conversation_id": "conv-smoke-dispute",
                    "customer_id": "C-0001",
                    "birth_date": "1990-03-15",
                    "document_issue_date": "2008-04-20",
                },
            )
            result = await session.call_tool(
                "iniciar_disputa",
                {
                    "conversation_id": "conv-smoke-dispute",
                    "transaction_id": "TX-000001",
                    "reason": "UNRECOGNIZED_CHARGE",
                    "idempotency_key": "key-smoke-1",
                },
            )

    assert not result.isError
    assert result.structuredContent is not None
    content = result.structuredContent
    assert set(content) == {"dispute_id", "status", "opened_at", "reason", "transaction"}
    assert content["status"] == "OPEN"
    assert content["reason"] == "UNRECOGNIZED_CHARGE"
    assert isinstance(content["dispute_id"], str)
    assert content["dispute_id"]
    assert "4321" not in content["dispute_id"]
    opened_at = datetime.fromisoformat(content["opened_at"])
    assert opened_at.utcoffset() == timedelta(hours=-5)
    assert content["opened_at"].endswith("-05:00")
    assert set(content["transaction"]) == {
        "transaction_id",
        "occurred_at",
        "merchant",
        "amount",
        "currency",
        "status",
        "card_id",
        "masked_card",
    }
    assert content["transaction"]["transaction_id"] == "TX-000001"
    assert "4111111111114321" not in result.model_dump_json()


# Regla: RN-004-03 — La herramienta exige que la conversación esté verificada en el servidor
#   (estado de RN-002-13). Una conversación sin verificación exitosa, desconocida o bloqueada por
#   intentos agotados se rechaza con `IDENTITY_NOT_VERIFIED`. La verificación no se traslada:
#   estar verificada en otra conversación no cuenta.
# AC-004-12 · Art. 7 (sin identificación no se abre una disputa)
async def test_ac_004_12_iniciar_disputa__stdio_server__unverified_conversation_is_rejected(
    tmp_path: Path,
) -> None:
    """AC-004-12: por stdio real, una conversación distinta a la verificada recibe el rechazo."""
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
                "iniciar_disputa",
                {
                    "conversation_id": "conv-other",
                    "transaction_id": "TX-000001",
                    "reason": "UNRECOGNIZED_CHARGE",
                    "idempotency_key": "key-smoke-2",
                },
            )

    assert result.structuredContent is not None
    assert result.structuredContent["code"] == "IDENTITY_NOT_VERIFIED"
    assert result.structuredContent["retryable"] is False
    assert "dispute_id" not in result.structuredContent
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
