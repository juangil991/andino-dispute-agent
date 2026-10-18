"""Integración de `iniciar_disputa`: errores, identidad y auditoría (spec 004 §7)."""

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
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.failing_dispute_repository import FailingDisputeRepository
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.ports.dispute_repository import DisputeRepository
from core_banking_mcp.application.use_cases.open_dispute import OpenDispute
from core_banking_mcp.application.use_cases.verify_identity import VerifyIdentity
from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.dispute import DisputeReason, DisputeStatus
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.domain.models.transaction import TransactionStatus
from core_banking_mcp.infrastructure.inbound.mcp.dispute_tools import register_dispute_tools
from core_banking_mcp.infrastructure.inbound.mcp.identity_tools import register_identity_tools
from core_banking_mcp.infrastructure.outbound.audit.json_audit_log import JsonAuditLog
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import DisputeRow
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_dispute_repository import (
    SqlAlchemyDisputeRepository,
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
_TX_DATE = datetime(2026, 10, 10, 12, 0, tzinfo=_BOGOTA)
_VALID: dict[str, Any] = {
    "conversation_id": "A",
    "transaction_id": "TX-L1",
    "reason": "UNRECOGNIZED_CHARGE",
    "idempotency_key": "K-1",
}
_ABSENT = object()
_ERROR_FIELDS = {"code", "message", "retryable"}


@dataclass
class _Harness:
    session: ClientSession
    db: Session
    store: InMemoryConversationVerificationStore
    stream: io.StringIO
    dispute_repo: DisputeRepository
    old_id: str | None

    async def call(self, **overrides: Any) -> tuple[bool, dict[str, Any], str]:
        """Invoca la herramienta; un override con valor `_ABSENT` omite el argumento."""
        args = {k: v for k, v in {**_VALID, **overrides}.items() if v is not _ABSENT}
        result = await self.session.call_tool("iniciar_disputa", args)
        text = "".join(getattr(block, "text", "") for block in result.content)
        return result.isError, result.structuredContent or {}, text

    async def verify(self, conversation_id: str) -> None:
        result = await self.session.call_tool(
            "verificar_identidad",
            {
                "conversation_id": conversation_id,
                "customer_id": "C-0001",
                "birth_date": "1985-03-14",
                "document_issue_date": "2005-04-02",
            },
        )
        assert result.structuredContent is not None
        assert result.structuredContent["verified"] is True

    def disputes(self) -> list[tuple[str, str, str]]:
        """(dispute_id, transaction_id, status) de todas las disputas del almacén."""
        if isinstance(self.dispute_repo, FailingDisputeRepository):
            return [
                (d.dispute_id, d.transaction_id, d.status.value) for d in self.dispute_repo.disputes
            ]
        self.db.expire_all()
        rows = self.db.scalars(select(DisputeRow).order_by(DisputeRow.dispute_id))
        return [(row.dispute_id, row.transaction_id, row.status) for row in rows]

    def audit_lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]


@asynccontextmanager
async def _harness(
    *,
    tx_status: TransactionStatus = TransactionStatus.CONFIRMED,
    previous: DisputeStatus | None = None,
    verified: bool = True,
    failing: bool = False,
    with_pedro: bool = False,
    pedro_status: TransactionStatus = TransactionStatus.CONFIRMED,
    with_second_tx: bool = False,
) -> AsyncIterator[_Harness]:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    db = session_factory(engine)()
    customers = SqlAlchemyCustomerRepository(db)
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
    transactions = SqlAlchemyTransactionRepository(db)
    transactions.add(
        "CARD-0001",
        TransactionBuilder(merchant="Tienda Aurora")
        .with_id("TX-L1")
        .with_card("CARD-0001", "4321")
        .with_occurred_at(_TX_DATE)
        .with_amount(Decimal("85000.00"))
        .with_status(tx_status)
        .build(),
    )
    if with_second_tx:
        transactions.add(
            "CARD-0001",
            TransactionBuilder()
            .with_id("TX-L2")
            .with_card("CARD-0001", "4321")
            .with_occurred_at(_TX_DATE)
            .build(),
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
        transactions.add(
            "CARD-0002",
            TransactionBuilder()
            .with_id("TX-P1")
            .with_card("CARD-0002", "8765")
            .with_occurred_at(_TX_DATE)
            .with_status(pedro_status)
            .build(),
        )
    dispute_repo: DisputeRepository = (
        FailingDisputeRepository() if failing else SqlAlchemyDisputeRepository(db)
    )
    old_id: str | None = None
    if previous is not None:
        old_id = dispute_repo.add(
            "OLD",
            "K-OLD",
            "TX-L1",
            DisputeReason.OTHER,
            previous,
            datetime(2026, 10, 11, tzinfo=UTC),
        ).dispute_id
    store = InMemoryConversationVerificationStore()
    if verified:
        store.save("A", VerificationState().with_verified("C-0001"))
    stream = io.StringIO()
    audit = JsonAuditLog(stream=stream)
    clock = FixedClock(_NOW)
    mcp = FastMCP("core-banking-test")
    register_dispute_tools(mcp, OpenDispute(transactions, dispute_repo, store, audit, clock))
    register_identity_tools(mcp, VerifyIdentity(customers, store, audit, clock))
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        yield _Harness(client, db, store, stream, dispute_repo, old_id)


def _assert_error(structured: dict[str, Any], code: str) -> None:
    assert set(structured) == _ERROR_FIELDS
    assert structured["code"] == code
    assert structured["retryable"] is False
    assert "dispute_id" not in structured


# Regla: RN-004-03 — La herramienta exige que la conversación esté verificada en el servidor; una conversación sin verificación exitosa, desconocida o bloqueada se rechaza con `IDENTITY_NOT_VERIFIED`. La verificación no se traslada: estar verificada en otra conversación no cuenta.  # noqa: E501
# Regla: RN-004-14 — Abrir una disputa no cambia el estado de verificación de la conversación.  # noqa: E501
# AC-004-12 · Art. 7 (las 4 situaciones de la tabla)
@pytest.mark.parametrize(
    "situation",
    ["never_verified", "one_failed_attempt", "locked", "verified_in_other_conversation"],
)
async def test_ac_004_12_iniciar_disputa__unverified_conversation__returns_identity_not_verified(
    situation: str,
) -> None:
    """AC-004-12: sin identidad verificada en la conversación no se abre ninguna disputa."""
    async with _harness(verified=False) as h:
        conversation = "A"
        match situation:
            case "one_failed_attempt":
                h.store.save("A", VerificationState(failed_attempts=1))
            case "locked":
                h.store.save("A", VerificationState(failed_attempts=3))
            case "verified_in_other_conversation":
                await h.verify("A")
                conversation = "B"
        before = {key: h.store.get(key) for key in ("A", "B")}

        is_error, structured, _ = await h.call(conversation_id=conversation)

        assert is_error is True
        _assert_error(structured, "IDENTITY_NOT_VERIFIED")
        assert h.disputes() == []
        assert {key: h.store.get(key) for key in before} == before


# Regla: RN-004-02 — El motivo es un código de un catálogo cerrado, sensible a mayúsculas; cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`.  # noqa: E501
# Regla: RN-004-09 — Validación de entrada: `reason` obligatorio y del catálogo de RN-004-02. Toda violación ⇒ `INVALID_INPUT`, sin disputa registrada.  # noqa: E501
# AC-004-03 · Art. 10 (las 5 filas de la tabla; ausente y null por separado)
@pytest.mark.parametrize(
    "reason",
    ["FRAUD", "unrecognized_charge", "no reconoce el cargo", "", _ABSENT, None],
    ids=["not_in_catalog", "lowercase", "free_text", "empty", "absent", "null"],
)
async def test_ac_004_03_iniciar_disputa__invalid_reason__returns_invalid_input(
    reason: Any,
) -> None:
    """AC-004-03: un motivo fuera del catálogo devuelve INVALID_INPUT sin registrar disputa."""
    async with _harness() as h:
        is_error, structured, _ = await h.call(reason=reason)

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert h.disputes() == []


# Regla: RN-004-05 — Solo se puede disputar una transacción `CONFIRMED`. Una transacción `PENDING` o `REVERSED` se rechaza con `TRANSACTION_NOT_DISPUTABLE` y no se registra nada.  # noqa: E501
# AC-004-04 · Art. 7 (filas PENDING y REVERSED)
@pytest.mark.parametrize(
    "tx_status",
    [TransactionStatus.PENDING, TransactionStatus.REVERSED],
    ids=["pending", "reversed"],
)
async def test_ac_004_04_iniciar_disputa__not_confirmed__returns_transaction_not_disputable(
    tx_status: TransactionStatus,
) -> None:
    """AC-004-04: una transacción PENDING o REVERSED no se disputa y no deja registro."""
    async with _harness(tx_status=tx_status) as h:
        is_error, structured, _ = await h.call()

        assert is_error is True
        _assert_error(structured, "TRANSACTION_NOT_DISPUTABLE")
        assert h.disputes() == []


# Regla: RN-004-07 — Una transacción tiene como máximo una disputa `OPEN`; si ya la tiene, se rechaza con `DISPUTE_ALREADY_OPEN` cuyo `message` incluye el `dispute_id` existente, y no se registra otra.  # noqa: E501
# AC-004-07 · Art. 7 (fila OPEN)
async def test_ac_004_07_iniciar_disputa__previous_open__returns_dispute_already_open() -> None:
    """AC-004-07: con una disputa previa OPEN se informa su ID y no se registra otra."""
    async with _harness(previous=DisputeStatus.OPEN) as h:
        assert h.old_id is not None

        is_error, structured, _ = await h.call(reason="DUPLICATE_CHARGE", idempotency_key="K-2")

        assert is_error is True
        _assert_error(structured, "DISPUTE_ALREADY_OPEN")
        assert h.old_id in structured["message"]
        assert [d[1] for d in h.disputes()] == ["TX-L1"]
        assert len(h.disputes()) == 1


# Regla: RN-004-08 — Si la conversación ya usó la clave con otra transacción u otro motivo, se rechaza con `INVALID_INPUT` sin registrar nada.  # noqa: E501
# AC-004-09 · Art. 10 (las 2 filas de la tabla)
@pytest.mark.parametrize(
    ("transaction_id", "reason"),
    [("TX-L2", "UNRECOGNIZED_CHARGE"), ("TX-L1", "DUPLICATE_CHARGE")],
    ids=["other_transaction", "other_reason"],
)
async def test_ac_004_09_iniciar_disputa__key_reused_with_other_data__returns_invalid_input(
    transaction_id: str, reason: str
) -> None:
    """AC-004-09: reutilizar K-1 con otros datos devuelve INVALID_INPUT sin disputa adicional."""
    async with _harness(with_second_tx=True) as h:
        first = await h.call()
        assert first[0] is False
        before = h.disputes()

        is_error, structured, _ = await h.call(
            transaction_id=transaction_id, reason=reason, idempotency_key="K-1"
        )

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert h.disputes() == before
        assert len(before) == 1


# Regla: RN-004-08 — La misma clave en otra conversación es una solicitud independiente: la clave pertenece a su conversación.  # noqa: E501
# AC-004-10 · Art. 7
async def test_ac_004_10_iniciar_disputa__same_key_other_conversation__returns_already_open() -> (
    None
):
    """AC-004-10: la clave de A no aplica en B; B recibe DISPUTE_ALREADY_OPEN con el ID de A."""
    async with _harness(verified=False) as h:
        await h.verify("A")
        await h.verify("B")
        first = await h.call(conversation_id="A")
        assert first[0] is False
        first_id = first[1]["dispute_id"]

        is_error, structured, _ = await h.call(conversation_id="B")

        assert is_error is True
        _assert_error(structured, "DISPUTE_ALREADY_OPEN")
        assert first_id in structured["message"]
        assert len(h.disputes()) == 1


# Regla: RN-004-04 — Si la transacción es de otro cliente o no existe, se devuelve `NOT_FOUND` con un mensaje fijo, idéntico en ambos casos, sin datos de ningún cliente.  # noqa: E501
# Regla: RN-004-13 — La respuesta nunca contiene el número completo de ninguna tarjeta, el documento del cliente ni su nombre, ni datos de otros clientes.  # noqa: E501
# AC-004-11 · Art. 7 (transacción ajena frente a inexistente)
async def test_ac_004_11_iniciar_disputa__foreign_or_unknown_transaction__same_not_found() -> None:
    """AC-004-11: `TX-P1` (de C-0002) y `TX-9999` devuelven el mismo NOT_FOUND sin datos ajenos."""
    async with _harness(with_pedro=True) as h:
        foreign = await h.call(transaction_id="TX-P1")
        unknown = await h.call(transaction_id="TX-9999", idempotency_key="K-2")

        for is_error, structured, _ in (foreign, unknown):
            assert is_error is True
            _assert_error(structured, "NOT_FOUND")
        assert foreign[1] == unknown[1]
        assert h.disputes() == []
        for leaked in ("TX-P1", "Pedro", "D-1002", _PAN_PEDRO, "8765", "CARD-0002", "C-0002"):
            assert leaked not in foreign[2]


# Regla: RN-004-09 — `transaction_id` e `idempotency_key` obligatorios, de 1 a 64 caracteres tras recortar; `conversation_id` obligatorio y no vacío tras recortar. Toda violación ⇒ `INVALID_INPUT`, sin disputa registrada.  # noqa: E501
# AC-004-13 · Art. 10 (las 7 filas de la tabla; ausente y null por separado)
@pytest.mark.parametrize(
    "overrides",
    [
        {"transaction_id": _ABSENT},
        {"transaction_id": None},
        {"transaction_id": ""},
        {"transaction_id": "   "},
        {"transaction_id": "T" * 65},
        {"idempotency_key": _ABSENT},
        {"idempotency_key": None},
        {"idempotency_key": ""},
        {"idempotency_key": "   "},
        {"idempotency_key": "k" * 65},
        {"conversation_id": _ABSENT},
        {"conversation_id": ""},
        {"conversation_id": "   "},
    ],
    ids=[
        "transaction_absent",
        "transaction_null",
        "transaction_empty",
        "transaction_blank",
        "transaction_65_chars",
        "key_absent",
        "key_null",
        "key_empty",
        "key_blank",
        "key_65_chars",
        "conversation_absent",
        "conversation_empty",
        "conversation_blank",
    ],
)
async def test_ac_004_13_iniciar_disputa__invalid_fields__returns_invalid_input(
    overrides: dict[str, Any],
) -> None:
    """AC-004-13: cada dato inválido devuelve INVALID_INPUT, retryable=false y sin disputa."""
    async with _harness() as h:
        is_error, structured, _ = await h.call(**overrides)

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert h.disputes() == []


# Regla: RN-004-10 — Las comprobaciones se evalúan en orden: (1) validación, (2) identidad, (3) clave de reintento, (4) transacción del cliente, (5) transacción confirmada, (6) sin disputa abierta; se devuelve el primer resultado.  # noqa: E501
# AC-004-14 · Art. 7 (las 5 filas de la tabla)
@pytest.mark.parametrize(
    "row",
    [
        "unverified_invalid_reason",
        "unverified_unknown_transaction",
        "key_reused_unknown_transaction",
        "foreign_pending_transaction",
        "pending_with_open_dispute",
    ],
)
async def test_ac_004_14_iniciar_disputa__multiple_failures__returns_first_check_error(
    row: str,
) -> None:
    """AC-004-14: se devuelve el primer resultado en el orden de comprobaciones de RN-004-10."""
    match row:
        case "unverified_invalid_reason":
            expected, overrides, kwargs = "INVALID_INPUT", {"reason": "FRAUD"}, {"verified": False}
        case "unverified_unknown_transaction":
            expected = "IDENTITY_NOT_VERIFIED"
            overrides, kwargs = {"transaction_id": "TX-9999"}, {"verified": False}
        case "key_reused_unknown_transaction":
            expected = "INVALID_INPUT"
            overrides, kwargs = {"transaction_id": "TX-9999", "idempotency_key": "K-1"}, {}
        case "foreign_pending_transaction":
            expected, overrides = "NOT_FOUND", {"transaction_id": "TX-P1"}
            kwargs = {"with_pedro": True, "pedro_status": TransactionStatus.PENDING}
        case _:
            expected, overrides = "TRANSACTION_NOT_DISPUTABLE", {}
            kwargs = {"tx_status": TransactionStatus.PENDING, "previous": DisputeStatus.OPEN}
    async with _harness(**kwargs) as h:
        if row == "key_reused_unknown_transaction":
            first = await h.call()
            assert first[0] is False

        is_error, structured, _ = await h.call(**overrides)

        assert is_error is True
        _assert_error(structured, expected)


# Regla: RN-004-15 — Ante una falla inesperada, la herramienta devuelve `INTERNAL` con `retryable = false`, sin detalles internos; no queda ninguna disputa ni clave de reintento registrada.  # noqa: E501
# AC-004-16 · Art. 10 (retryable=false implica escalar)
async def test_ac_004_16_iniciar_disputa__repository_fails__returns_internal() -> None:
    """AC-004-16: una falla al registrar da INTERNAL, sin disputa, y la clave sigue libre."""
    async with _harness(failing=True) as h:
        is_error, structured, text = await h.call()

        assert is_error is True
        _assert_error(structured, "INTERNAL")
        for leaked in ("detalle interno secreto", "RuntimeError", "Traceback", "SELECT"):
            assert leaked not in structured["message"]
            assert leaked not in text
        assert h.disputes() == []

        assert isinstance(h.dispute_repo, FailingDisputeRepository)
        h.dispute_repo.repair()
        retry_error, retry, _ = await h.call()

        assert retry_error is False
        assert retry["status"] == "OPEN"
        assert [(d[1], d[2]) for d in h.disputes()] == [("TX-L1", "OPEN")]


# Regla: RN-004-16 — Cada invocación genera exactamente un registro de auditoría con `conversation_id`, fecha y hora del reloj inyectado, `tool = "iniciar_disputa"`, `transaction_id`, `reason` e `idempotency_key` y el resultado; toda secuencia de 13 a 19 dígitos se registra como `[REDACTED]`; nunca contiene el número completo de una tarjeta ni el documento.  # noqa: E501
# AC-004-17 · Art. 8 (trazabilidad total; los 10 casos de la tabla)
@pytest.mark.parametrize(
    "case",
    [
        "opened",
        "replayed",
        "duplicate",
        "not_disputable",
        "not_found",
        "invalid",
        "pan_in_transaction_id",
        "pan_in_key",
        "unverified",
        "internal",
    ],
)
async def test_ac_004_17_iniciar_disputa__any_case__audits_one_line_without_personal_data(
    case: str,
) -> None:
    """AC-004-17: una sola línea JSON con herramienta, datos recibidos y resultado, sin PAN."""
    overrides: dict[str, Any] = {}
    kwargs: dict[str, Any] = {}
    match case:
        case "duplicate":
            kwargs = {"previous": DisputeStatus.OPEN}
        case "not_disputable":
            kwargs = {"tx_status": TransactionStatus.PENDING}
        case "not_found":
            overrides = {"transaction_id": "TX-9999"}
        case "invalid":
            overrides = {"reason": "FRAUD"}
        case "pan_in_transaction_id":
            overrides = {"transaction_id": _PAN}
        case "pan_in_key":
            overrides = {"idempotency_key": f"pago-{_PAN}"}
        case "unverified":
            kwargs = {"verified": False}
        case "internal":
            kwargs = {"failing": True}
    async with _harness(**kwargs) as h:
        if case == "replayed":
            first = await h.call()
            assert first[0] is False
            h.stream.seek(0)
            h.stream.truncate(0)

        _, structured, _ = await h.call(**overrides)

        lines = h.audit_lines()
        assert len(lines) == 1
        line = lines[0]
        assert line["tool"] == "iniciar_disputa"
        assert line["conversation_id"] == "A"
        assert line["timestamp"] == _NOW.isoformat()
        expected_tx = {"not_found": "TX-9999", "pan_in_transaction_id": "[REDACTED]"}.get(
            case, "TX-L1"
        )
        assert line["transaction_id"] == expected_tx
        expected_key = "pago-[REDACTED]" if case == "pan_in_key" else "K-1"
        assert line["idempotency_key"] == expected_key
        if case == "invalid":
            assert line.get("dispute_reason") in (None, "")
        else:
            assert line["dispute_reason"] == "UNRECOGNIZED_CHARGE"
        match case:
            case "opened" | "pan_in_key":
                assert line["outcome"] == "opened"
                assert line["dispute_id"] == structured["dispute_id"]
            case "replayed":
                assert line["outcome"] == "replayed"
                assert line["dispute_id"] == structured["dispute_id"]
            case "duplicate":
                assert (line["outcome"], line["error_code"]) == ("error", "DISPUTE_ALREADY_OPEN")
                assert line["dispute_id"] == h.old_id
            case "not_disputable":
                assert line["error_code"] == "TRANSACTION_NOT_DISPUTABLE"
            case "not_found" | "pan_in_transaction_id":
                assert line["error_code"] == "NOT_FOUND"
            case "invalid":
                assert line["error_code"] == "INVALID_INPUT"
            case "unverified":
                assert line["error_code"] == "IDENTITY_NOT_VERIFIED"
            case "internal":
                assert line["error_code"] == "INTERNAL"
        raw = h.stream.getvalue()
        assert _PAN not in raw
        assert "D-1001" not in raw
