"""Integración de `consultar_transacciones`: errores, identidad y auditoría (spec 003 §7)."""

import io
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.failing_transaction_repository import FailingTransactionRepository
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.ports.transaction_repository import TransactionRepository
from core_banking_mcp.application.use_cases.list_card_transactions import ListCardTransactions
from core_banking_mcp.application.use_cases.verify_identity import VerifyIdentity
from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.domain.models.transaction import Transaction
from core_banking_mcp.infrastructure.inbound.mcp.identity_tools import register_identity_tools
from core_banking_mcp.infrastructure.inbound.mcp.transaction_tools import (
    register_transaction_tools,
)
from core_banking_mcp.infrastructure.outbound.audit.json_audit_log import JsonAuditLog
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_transaction_repository import (
    SqlAlchemyTransactionRepository,
)
from core_banking_mcp.infrastructure.outbound.verification.in_memory_verification_store import (
    InMemoryConversationVerificationStore,
)

_PAN = "4111111111114321"
_PAN_PEDRO = "5500000000008765"
_BOGOTA = timezone(timedelta(hours=-5))
_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_VALID: dict[str, Any] = {
    "conversation_id": "conv-1",
    "card_last4": "4321",
    "date_from": "2026-09-01",
    "date_to": "2026-09-30",
}
_ABSENT = object()


@dataclass
class _Harness:
    session: ClientSession
    store: InMemoryConversationVerificationStore
    stream: io.StringIO

    async def call(self, **overrides: Any) -> tuple[bool, dict[str, Any], str]:
        """Invoca la herramienta; un override con valor `_ABSENT` omite el argumento."""
        args = {k: v for k, v in {**_VALID, **overrides}.items() if v is not _ABSENT}
        result = await self.session.call_tool("consultar_transacciones", args)
        text = "".join(getattr(block, "text", "") for block in result.content)
        return result.isError, result.structuredContent or {}, text

    def audit_lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]


def _sept_tx(transaction_id: str, day: int, hour: int = 10) -> Transaction:
    return (
        TransactionBuilder()
        .with_id(transaction_id)
        .with_card("CARD-0001", "4321")
        .with_occurred_at(datetime(2026, 9, day, hour, 0, tzinfo=_BOGOTA))
        .with_amount(Decimal("100.00"))
        .build()
    )


@asynccontextmanager
async def _harness(
    *,
    tx_count: int = 0,
    verified: bool = True,
    failing: bool = False,
    with_pedro: bool = False,
    now: datetime = _NOW,
) -> AsyncIterator[_Harness]:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    session = session_factory(engine)()
    customers = SqlAlchemyCustomerRepository(session)
    pans = {"4321": _PAN, "8765": _PAN_PEDRO}
    customers.add(
        CustomerBuilder()
        .with_id("C-0001")
        .with_name("Laura Méndez")
        .with_document("D-1001")
        .with_cards(Card("4321", CardStatus.ACTIVE))
        .build(),
        pans,
        identity=IdentityBuilder().build(),
    )
    if with_pedro:
        customers.add(
            CustomerBuilder()
            .with_id("C-0002")
            .with_name("Pedro Ríos")
            .with_document("D-1002")
            .with_cards(Card("8765", CardStatus.ACTIVE))
            .build(),
            pans,
            identity=IdentityBuilder().build(),
        )
    real_repo = SqlAlchemyTransactionRepository(session)
    for n in range(tx_count):
        real_repo.add("CARD-0001", _sept_tx(f"T-{n:03d}", 1 + n % 28, 8 + n // 28))
    if with_pedro:
        pedro_tx = (
            TransactionBuilder()
            .with_id("T-PEDRO")
            .with_card("CARD-0002", "8765")
            .with_occurred_at(datetime(2026, 9, 10, 10, 0, tzinfo=_BOGOTA))
            .build()
        )
        real_repo.add("CARD-0002", pedro_tx)
    repo: TransactionRepository = FailingTransactionRepository() if failing else real_repo
    store = InMemoryConversationVerificationStore()
    if verified:
        store.save("conv-1", VerificationState().with_verified("C-0001"))
    stream = io.StringIO()
    audit = JsonAuditLog(stream=stream)
    clock = FixedClock(now)
    mcp = FastMCP("core-banking-test")
    register_transaction_tools(mcp, ListCardTransactions(repo, store, audit, clock))
    register_identity_tools(mcp, VerifyIdentity(customers, store, audit, clock))
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        yield _Harness(client, store, stream)


def _assert_error(structured: dict[str, Any], code: str) -> None:
    assert set(structured) == {"code", "message", "retryable"}
    assert structured["code"] == code
    assert structured["retryable"] is False
    assert "transactions" not in structured


# Regla: RN-003-06 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_last4` obligatorio, exactamente 4 dígitos `0-9`, sin espacios; `date_from` y `date_to` obligatorias, en formato `AAAA-MM-DD` y existentes en el calendario; `date_from` no posterior a `date_to`; `date_to` no posterior a hoy; el rango no supera **90 días contando ambos extremos** (`date_to − date_from + 1 ≤ 90`). No hay límite hacia el pasado para `date_from`. Toda violación ⇒ `INVALID_INPUT`, sin transacciones.  # noqa: E501
# AC-003-07 · Art. 10 (borde: 91 días, un día más que el máximo)
async def test_ac_003_07_consultar_transacciones__91_days__returns_invalid_input() -> None:
    """AC-003-07: un rango de 91 días devuelve INVALID_INPUT con retryable=false."""
    async with _harness() as h:
        is_error, structured, _ = await h.call(date_from="2026-06-01", date_to="2026-08-30")

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")


# Regla: RN-003-06 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_last4` obligatorio, exactamente 4 dígitos `0-9`, sin espacios; `date_from` y `date_to` obligatorias, en formato `AAAA-MM-DD` y existentes en el calendario; `date_from` no posterior a `date_to`; `date_to` no posterior a hoy; el rango no supera **90 días contando ambos extremos** (`date_to − date_from + 1 ≤ 90`). No hay límite hacia el pasado para `date_from`. Toda violación ⇒ `INVALID_INPUT`, sin transacciones.  # noqa: E501
# AC-003-09 · Art. 10 (las 13 filas de la tabla)
@pytest.mark.parametrize(
    "overrides",
    [
        {"date_from": ""},
        {"date_to": ""},
        {"date_from": _ABSENT},
        {"date_to": _ABSENT},
        {"date_from": None},
        {"date_to": None},
        {"date_to": "2026-09-31"},
        {"date_from": "01/09/2026"},
        {"date_from": "2026-09-30", "date_to": "2026-09-01"},
        {"date_from": "2026-10-01", "date_to": "2026-10-18"},
        {"card_last4": _ABSENT},
        {"card_last4": None},
        {"card_last4": "432"},
        {"card_last4": "54321"},
        {"card_last4": "43a1"},
        {"conversation_id": _ABSENT},
        {"conversation_id": ""},
        {"conversation_id": "   "},
    ],
    ids=[
        "date_from_empty",
        "date_to_empty",
        "date_from_absent",
        "date_to_absent",
        "date_from_null",
        "date_to_null",
        "date_to_nonexistent",
        "date_from_bad_format",
        "from_after_to",
        "to_after_today",
        "card_absent",
        "card_null",
        "card_3_digits",
        "card_5_digits",
        "card_with_letters",
        "conversation_absent",
        "conversation_empty",
        "conversation_blank",
    ],
)
async def test_ac_003_09_consultar_transacciones__invalid_input__returns_invalid_input(
    overrides: dict[str, Any],
) -> None:
    """AC-003-09: cada fila inválida devuelve isError, INVALID_INPUT y retryable=false."""
    async with _harness(tx_count=2) as h:
        is_error, structured, _ = await h.call(**overrides)

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")


# Regla: RN-003-06 — Validación de entrada: ... `date_to` no posterior a hoy ...  # noqa: E501
# Regla: RN-003-07 — "Hoy" es la fecha del reloj inyectado en la zona horaria `America/Bogota` (UTC−05:00), igual que RN-002-08.  # noqa: E501
# AC-003-10 · Art. 7 (fila inválida; borde: aún 17 en Bogotá)
async def test_ac_003_10_consultar_transacciones__tomorrow_in_bogota__returns_invalid_input() -> (
    None
):
    """AC-003-10: a las 03:00Z `date_to = 2026-10-18` aún es futuro en Bogotá."""
    async with _harness(now=datetime(2026, 10, 18, 3, 0, tzinfo=UTC)) as h:
        is_error, structured, _ = await h.call(date_from="2026-10-01", date_to="2026-10-18")

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")


# Regla: RN-003-02 — La herramienta exige que la conversación esté verificada en el servidor (estado de RN-002-13). Una conversación sin verificación exitosa, desconocida o bloqueada por intentos agotados se rechaza con `IDENTITY_NOT_VERIFIED`. La verificación no se traslada: estar verificada en otra conversación no cuenta.  # noqa: E501
# Regla: RN-003-14 — La herramienta es de solo lectura: no modifica transacciones, tarjetas ni el estado de verificación de la conversación (cliente verificado e intentos fallidos).  # noqa: E501
# AC-003-11 · Art. 7 (las 4 situaciones de la tabla)
@pytest.mark.parametrize(
    "situation",
    ["never_verified", "one_failed_attempt", "locked", "verified_in_other_conversation"],
)
async def test_ac_003_11_consultar_transacciones__unverified_conversation__returns_identity_not_verified(  # noqa: E501
    situation: str,
) -> None:
    """AC-003-11: sin identidad verificada en la conversación no se muestra ninguna transacción."""
    async with _harness(tx_count=2, verified=False) as h:
        conversation = "conv-1"
        match situation:
            case "one_failed_attempt":
                h.store.save("conv-1", VerificationState(failed_attempts=1))
            case "locked":
                h.store.save("conv-1", VerificationState(failed_attempts=3))
            case "verified_in_other_conversation":
                result = await h.session.call_tool(
                    "verificar_identidad",
                    {
                        "conversation_id": "conv-a",
                        "customer_id": "C-0001",
                        "birth_date": "1985-03-14",
                        "document_issue_date": "2005-04-02",
                    },
                )
                assert result.structuredContent is not None
                assert result.structuredContent["verified"] is True
                conversation = "conv-b"
        before = {key: h.store.get(key) for key in ("conv-1", "conv-a", "conv-b")}

        is_error, structured, text = await h.call(conversation_id=conversation)

        assert is_error is True
        _assert_error(structured, "IDENTITY_NOT_VERIFIED")
        assert "T-0" not in text
        assert {key: h.store.get(key) for key in before} == before


# Regla: RN-003-08 — Las comprobaciones se evalúan en este orden y se devuelve el primer error: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) tarjeta del cliente verificado → `NOT_FOUND`.  # noqa: E501
# AC-003-12 · Art. 7 (las 3 filas de la tabla)
@pytest.mark.parametrize(
    ("verified", "overrides", "code"),
    [
        (False, {"card_last4": "43a1"}, "INVALID_INPUT"),
        (False, {"card_last4": "0000"}, "IDENTITY_NOT_VERIFIED"),
        (True, {"card_last4": "0000", "date_to": "2026-10-18"}, "INVALID_INPUT"),
    ],
    ids=["unverified_invalid_card", "unverified_unknown_card", "verified_unknown_card_future_date"],
)
async def test_ac_003_12_consultar_transacciones__multiple_failures__returns_first_check_error(
    verified: bool, overrides: dict[str, Any], code: str
) -> None:
    """AC-003-12: se devuelve el primer error en el orden validación, identidad, tarjeta."""
    async with _harness(verified=verified) as h:
        is_error, structured, _ = await h.call(**overrides)

        assert is_error is True
        _assert_error(structured, code)


# Regla: RN-003-04 — Si el cliente verificado no tiene ninguna tarjeta terminada en `card_last4` (porque la tarjeta es de otro cliente o porque no existe), se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en ambos casos, sin datos de ningún cliente.  # noqa: E501
# Regla: RN-003-13 — La respuesta nunca contiene el número completo de ninguna tarjeta, el documento del cliente ni su nombre, ni datos de otros clientes.  # noqa: E501
# AC-003-13 · Art. 7 (tarjeta ajena frente a inexistente)
async def test_ac_003_13_consultar_transacciones__foreign_or_unknown_card__same_not_found() -> None:
    """AC-003-13: `8765` (de C-0002) y `0000` devuelven el mismo NOT_FOUND sin datos ajenos."""
    async with _harness(with_pedro=True) as h:
        foreign = await h.call(card_last4="8765")
        unknown = await h.call(card_last4="0000")

        for is_error, structured, _ in (foreign, unknown):
            assert is_error is True
            _assert_error(structured, "NOT_FOUND")
        assert foreign[1] == unknown[1]
        for leaked in ("T-PEDRO", "Pedro", "D-1002", _PAN_PEDRO, "8765", "CARD-0002"):
            assert leaked not in foreign[2]


# Regla: RN-003-16 — Ante una falla inesperada (p. ej. el repositorio de transacciones no responde), la herramienta devuelve `INTERNAL` con `retryable = false`, sin transacciones ni detalles internos (trazas, SQL, texto de la excepción).  # noqa: E501
# AC-003-18 · Art. 10 (retryable=false implica escalar)
async def test_ac_003_18_consultar_transacciones__repository_fails__returns_internal() -> None:
    """AC-003-18: repositorio caído da INTERNAL sin transacciones ni texto de la excepción."""
    async with _harness(failing=True) as h:
        is_error, structured, text = await h.call()

        assert is_error is True
        _assert_error(structured, "INTERNAL")
        for leaked in ("detalle interno secreto", "RuntimeError", "Traceback", "SELECT"):
            assert leaked not in structured["message"]
            assert leaked not in text


# Regla: RN-003-15 — Cada invocación genera exactamente un registro de auditoría con `conversation_id` (o vacío si no llegó), fecha y hora del reloj inyectado, `tool = "consultar_transacciones"`, tarjeta enmascarada (`**** NNNN`; vacía si `card_last4` no es válido, para no registrar lo que se haya escrito en ese campo), rango consultado (`date_from` y `date_to` recibidos) y resultado: `found` con la cantidad y los `transaction_id` devueltos (cantidad 0 si no hubo), `refinement_required`, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INTERNAL`). El registro **nunca** contiene el número completo de una tarjeta.  # noqa: E501
# AC-003-17 · Art. 8 (trazabilidad total; los 8 casos de la tabla)
@pytest.mark.parametrize(
    ("case", "expected_masked", "expected"),
    [
        ("found", "**** 4321", {"outcome": "found", "count": 2}),
        ("empty", "**** 4321", {"outcome": "found", "count": 0}),
        ("refinement", "**** 4321", {"outcome": "refinement_required"}),
        ("invalid", "**** 4321", {"outcome": "error", "error_code": "INVALID_INPUT"}),
        ("full_pan", None, {"outcome": "error", "error_code": "INVALID_INPUT"}),
        ("unverified", "**** 4321", {"outcome": "error", "error_code": "IDENTITY_NOT_VERIFIED"}),
        ("not_found", "**** 0000", {"outcome": "error", "error_code": "NOT_FOUND"}),
        ("internal", "**** 4321", {"outcome": "error", "error_code": "INTERNAL"}),
    ],
    ids=[
        "found",
        "empty",
        "refinement_required",
        "invalid_input",
        "full_pan_in_field",
        "identity_not_verified",
        "not_found",
        "internal",
    ],
)
async def test_ac_003_17_consultar_transacciones__any_case__audits_one_line_without_pan(
    case: str, expected_masked: str | None, expected: dict[str, Any]
) -> None:
    """AC-003-17: una sola línea JSON con herramienta, tarjeta enmascarada, rango y resultado."""
    tx_count = {"found": 2, "refinement": 51}.get(case, 0)
    overrides: dict[str, Any] = {}
    match case:
        case "invalid":
            overrides = {"date_to": "2026-09-31"}
        case "full_pan":
            overrides = {"card_last4": _PAN}
        case "not_found":
            overrides = {"card_last4": "0000"}
    async with _harness(
        tx_count=tx_count, verified=case != "unverified", failing=case == "internal"
    ) as h:
        await h.call(**overrides)

        lines = h.audit_lines()
        assert len(lines) == 1
        line = lines[0]
        assert line["tool"] == "consultar_transacciones"
        assert line["conversation_id"] == "conv-1"
        assert line["timestamp"] == _NOW.isoformat()
        assert line.get("masked_card") == expected_masked
        assert line["date_from"] == overrides.get("date_from", "2026-09-01")
        assert line["date_to"] == overrides.get("date_to", "2026-09-30")
        for key, value in expected.items():
            assert line[key] == value
        if case == "found":
            assert sorted(line["transaction_ids"]) == ["T-000", "T-001"]
        assert _PAN not in h.stream.getvalue()
