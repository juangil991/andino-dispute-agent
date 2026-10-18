"""Integración de `iniciar_disputa` (camino exitoso) vía sesión MCP en memoria (spec 004 §7)."""

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
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.use_cases.open_dispute import OpenDispute
from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.dispute import DisputeReason, DisputeStatus
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.domain.models.transaction import TransactionStatus
from core_banking_mcp.infrastructure.inbound.mcp.dispute_tools import register_dispute_tools
from core_banking_mcp.infrastructure.inbound.mcp.schemas import IniciarDisputaOut
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    CardRow,
    DisputeRow,
    TransactionRow,
)
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
_BOGOTA = timezone(timedelta(hours=-5))
_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_TX_DATE = datetime(2026, 10, 10, 12, 0, tzinfo=_BOGOTA)
_CARD_REF = "CARD-0001"
_RESPONSE_FIELDS = {"dispute_id", "status", "opened_at", "reason", "transaction"}
_TRANSACTION_FIELDS = {
    "transaction_id",
    "occurred_at",
    "merchant",
    "amount",
    "currency",
    "status",
    "card_id",
    "masked_card",
    "merchant_country",
}
_REASONS = [
    "UNRECOGNIZED_CHARGE",
    "DUPLICATE_CHARGE",
    "INCORRECT_AMOUNT",
    "NOT_RECEIVED",
    "OTHER",
]


class _MutableClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant


@dataclass
class _Result:
    is_error: bool
    structured: dict[str, Any]
    text: str


@dataclass
class _Harness:
    client: ClientSession
    db: Session
    clock: _MutableClock
    store: InMemoryConversationVerificationStore

    async def open(
        self,
        *,
        reason: str = "UNRECOGNIZED_CHARGE",
        key: str = "K-1",
        transaction_id: str = "TX-L1",
        conversation_id: str = "A",
    ) -> _Result:
        result = await self.client.call_tool(
            "iniciar_disputa",
            {
                "conversation_id": conversation_id,
                "transaction_id": transaction_id,
                "reason": reason,
                "idempotency_key": key,
            },
        )
        text = "".join(getattr(block, "text", "") for block in result.content)
        return _Result(result.isError, result.structuredContent or {}, text)

    def disputes(self) -> list[DisputeRow]:
        self.db.expire_all()
        return list(self.db.scalars(select(DisputeRow).order_by(DisputeRow.dispute_id)))

    def transaction_status(self) -> str:
        self.db.expire_all()
        return self.db.scalars(select(TransactionRow.status)).one()

    def card_status(self) -> str:
        self.db.expire_all()
        return self.db.scalars(select(CardRow.status)).one()


@asynccontextmanager
async def _harness(
    *,
    tx_status: TransactionStatus = TransactionStatus.CONFIRMED,
    occurred_at: datetime = _TX_DATE,
    card_status: CardStatus = CardStatus.ACTIVE,
    previous: DisputeStatus | None = None,
    merchant_country: str = "CO",
) -> AsyncIterator[_Harness]:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    db = session_factory(engine)()
    SqlAlchemyCustomerRepository(db).add(
        CustomerBuilder()
        .with_id("C-0001")
        .with_name("Laura Méndez")
        .with_document("D-1001")
        .with_cards(Card("4321", card_status))
        .build(),
        {"4321": _PAN},
        identity=IdentityBuilder().build(),
    )
    transactions = SqlAlchemyTransactionRepository(db)
    transactions.add(
        _CARD_REF,
        TransactionBuilder(merchant="Tienda Aurora")
        .with_id("TX-L1")
        .with_card(_CARD_REF, "4321")
        .with_occurred_at(occurred_at)
        .with_amount(Decimal("85000.00"))
        .with_merchant_country(merchant_country)
        .with_status(tx_status)
        .build(),
    )
    disputes = SqlAlchemyDisputeRepository(db)
    if previous is not None:
        disputes.add(
            "OLD",
            "K-OLD",
            "TX-L1",
            DisputeReason.OTHER,
            previous,
            datetime(2026, 10, 11, tzinfo=UTC),
        )
    store = InMemoryConversationVerificationStore()
    store.save("A", VerificationState().with_verified("C-0001"))
    clock = _MutableClock(_NOW)
    use_case = OpenDispute(transactions, disputes, store, FakeAuditLog(), clock)
    mcp = FastMCP("core-banking-test")
    register_dispute_tools(mcp, use_case)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        yield _Harness(client, db, clock, store)


# Regla: RN-004-01 — La solicitud indica la transacción por el `transaction_id` que devuelve `consultar_transacciones`, el motivo (`reason`) y una clave de reintento (`idempotency_key`) generada por el consumidor.  # noqa: E501
# Regla: RN-004-11 — Una disputa nueva queda con `status = OPEN`, un `dispute_id` opaco y único que no se deriva del número de la tarjeta, y `opened_at` igual al instante del reloj inyectado expresado en ISO 8601 con la zona de Bogotá (`−05:00`).  # noqa: E501
# Regla: RN-004-12 — La respuesta exitosa contiene solo `dispute_id`, `status`, `opened_at`, `reason` y `transaction`, con exactamente los campos de `TransactionItem`.  # noqa: E501
# Regla: RN-004-14 — Abrir una disputa solo registra la disputa y la clave de reintento usada. No cambia la transacción, la tarjeta ni el estado de verificación de la conversación.  # noqa: E501
# AC-004-01 · Art. 7
async def test_ac_004_01_iniciar_disputa__confirmed_transaction__opens_dispute() -> None:
    """AC-004-01: una transacción confirmada abre una disputa OPEN sin alterar nada más."""
    async with _harness() as h:
        verification_before = h.store.get("A")

        result = await h.open()

        assert result.is_error is False
        out = result.structured
        assert out["dispute_id"] != ""
        assert out["status"] == "OPEN"
        assert out["opened_at"] == "2026-10-17T10:00:00-05:00"
        assert out["reason"] == "UNRECOGNIZED_CHARGE"
        assert out["transaction"] == {
            "transaction_id": "TX-L1",
            "occurred_at": "2026-10-10T12:00:00-05:00",
            "merchant": "Tienda Aurora",
            "amount": "85000.00",
            "currency": "COP",
            "status": "CONFIRMED",
            "card_id": _CARD_REF,
            "masked_card": "**** 4321",
            "merchant_country": "CO",
        }
        rows = h.disputes()
        assert len(rows) == 1
        assert (rows[0].dispute_id, rows[0].transaction_id, rows[0].status) == (
            out["dispute_id"],
            "TX-L1",
            "OPEN",
        )
        assert h.transaction_status() == "CONFIRMED"
        assert h.card_status() == "ACTIVE"
        assert h.store.get("A") == verification_before


# Regla: RN-007-30 — `TransactionItem` (RN-003-12) incorpora `merchant_country`: el código ISO 3166-1 alfa-2 del país del comercio, en mayúsculas (`CO` = Colombia).  # noqa: E501
# AC-007-33 · Art. 7
async def test_ac_007_33_iniciar_disputa__us_merchant__returns_merchant_country() -> None:
    """AC-007-33: el TransactionItem de la disputa trae merchant_country = "US"."""
    async with _harness(merchant_country="US") as h:
        result = await h.open()

        assert result.is_error is False
        assert result.structured["transaction"]["merchant_country"] == "US"
        assert set(result.structured["transaction"]) == _TRANSACTION_FIELDS


# Regla: RN-004-02 — El motivo es un código de un catálogo cerrado: UNRECOGNIZED_CHARGE, DUPLICATE_CHARGE, INCORRECT_AMOUNT, NOT_RECEIVED y OTHER.  # noqa: E501
# AC-004-02 · Art. 7
@pytest.mark.parametrize("reason", _REASONS, ids=_REASONS)
async def test_ac_004_02_iniciar_disputa__allowed_reason__opens_dispute(reason: str) -> None:
    """AC-004-02: cada motivo del catálogo queda registrado y se devuelve tal cual."""
    async with _harness() as h:
        result = await h.open(reason=reason)

        assert result.is_error is False
        assert result.structured["reason"] == reason
        rows = h.disputes()
        assert [(row.status, row.reason) for row in rows] == [("OPEN", reason)]


# Regla: RN-004-05 — Solo se puede disputar una transacción `CONFIRMED`.  # noqa: E501
# AC-004-04 · Art. 7 (fila CONFIRMED)
async def test_ac_004_04_iniciar_disputa__confirmed_status__registers_open_dispute() -> None:
    """AC-004-04 (fila CONFIRMED): la disputa queda registrada como OPEN."""
    async with _harness(tx_status=TransactionStatus.CONFIRMED) as h:
        result = await h.open()

        assert result.is_error is False
        assert [row.status for row in h.disputes()] == ["OPEN"]


# Regla: RN-004-06 — No hay plazo máximo para disputar una transacción confirmada: su antigüedad no influye en esta herramienta.  # noqa: E501
# AC-004-05 · Art. 7 (1, 90 y 400 días)
@pytest.mark.parametrize(
    "occurred_at",
    [
        datetime(2026, 10, 16, 12, 0, tzinfo=_BOGOTA),
        datetime(2026, 7, 19, 12, 0, tzinfo=_BOGOTA),
        datetime(2025, 9, 12, 12, 0, tzinfo=_BOGOTA),
    ],
    ids=["1-day", "90-days", "400-days"],
)
async def test_ac_004_05_iniciar_disputa__any_age__opens_dispute(occurred_at: datetime) -> None:
    """AC-004-05: la antigüedad de la transacción no impide abrir la disputa."""
    async with _harness(occurred_at=occurred_at) as h:
        result = await h.open()

        assert result.is_error is False
        assert result.structured["transaction"]["occurred_at"] == occurred_at.isoformat()
        assert [row.status for row in h.disputes()] == ["OPEN"]


# Regla: RN-004-04 — La transacción debe pertenecer a una tarjeta del cliente verificado, sea cual sea el estado de la tarjeta (activa, bloqueada o cancelada).  # noqa: E501
# AC-004-06 · Art. 7
@pytest.mark.parametrize(
    "card_status",
    [CardStatus.ACTIVE, CardStatus.BLOCKED, CardStatus.CANCELLED],
    ids=["active", "blocked", "cancelled"],
)
async def test_ac_004_06_iniciar_disputa__any_card_status__opens_dispute(
    card_status: CardStatus,
) -> None:
    """AC-004-06: el estado de la tarjeta no impide abrir la disputa."""
    async with _harness(card_status=card_status) as h:
        result = await h.open()

        assert result.is_error is False
        assert [row.status for row in h.disputes()] == ["OPEN"]


# Regla: RN-004-07 — Las disputas previas `CLOSED` o `REJECTED` no impiden abrir una nueva.  # noqa: E501
# AC-004-07 · Art. 7 (filas CLOSED y REJECTED)
@pytest.mark.parametrize(
    "previous",
    [DisputeStatus.CLOSED, DisputeStatus.REJECTED],
    ids=["closed", "rejected"],
)
async def test_ac_004_07_iniciar_disputa__previous_not_open__opens_new_dispute(
    previous: DisputeStatus,
) -> None:
    """AC-004-07: con una disputa previa cerrada o rechazada se registra una nueva OPEN."""
    async with _harness(previous=previous) as h:
        old_id = h.disputes()[0].dispute_id

        result = await h.open(reason="DUPLICATE_CHARGE", key="K-2")

        assert result.is_error is False
        assert result.structured["status"] == "OPEN"
        assert result.structured["dispute_id"] != old_id
        rows = {row.dispute_id: row.status for row in h.disputes()}
        assert rows == {old_id: previous.value, result.structured["dispute_id"]: "OPEN"}


# Regla: RN-004-08 — Si la conversación ya usó la clave con la misma transacción y el mismo motivo, se devuelve la disputa que creó esa solicitud (mismo `dispute_id` y `opened_at`) sin registrar otra.  # noqa: E501
# Regla: RN-004-10 — Las comprobaciones se evalúan en orden: la clave de reintento antes que la disputa abierta.  # noqa: E501
# AC-004-08 · Art. 7
async def test_ac_004_08_iniciar_disputa__same_request_repeated__returns_same_dispute() -> None:
    """AC-004-08: repetir la solicitud devuelve la misma disputa y no la duplica."""
    async with _harness() as h:
        first = await h.open()
        h.clock.instant = _NOW + timedelta(hours=1)

        second = await h.open()

        assert first.is_error is False
        assert second.is_error is False
        assert second.structured["dispute_id"] == first.structured["dispute_id"]
        assert second.structured["opened_at"] == first.structured["opened_at"]
        assert second.structured["opened_at"] == "2026-10-17T10:00:00-05:00"
        assert "DISPUTE_ALREADY_OPEN" not in second.text
        assert len(h.disputes()) == 1


# Regla: RN-004-12 — La respuesta exitosa contiene solo `dispute_id`, `status`, `opened_at`, `reason` y `transaction`, con exactamente los campos de `TransactionItem`.  # noqa: E501
# Regla: RN-004-13 — La respuesta nunca contiene el número completo de ninguna tarjeta, el documento del cliente ni su nombre, ni datos de otros clientes.  # noqa: E501
# AC-004-15 · Art. 7
async def test_ac_004_15_iniciar_disputa__success__protects_personal_data() -> None:
    """AC-004-15: la respuesta solo trae los campos permitidos y ningún dato personal."""
    async with _harness() as h:
        result = await h.open()

        assert result.is_error is False
        out = result.structured
        assert set(out) == _RESPONSE_FIELDS
        assert set(out["transaction"]) == _TRANSACTION_FIELDS
        assert out["transaction"]["masked_card"] == "**** 4321"
        assert _PAN not in out["dispute_id"]
        assert _PAN not in out["transaction"]["card_id"]
        serialized = json.dumps(out, ensure_ascii=False) + result.text
        for forbidden in (_PAN, "D-1001", "Laura Méndez"):
            assert forbidden not in serialized
        IniciarDisputaOut.model_validate(out)
