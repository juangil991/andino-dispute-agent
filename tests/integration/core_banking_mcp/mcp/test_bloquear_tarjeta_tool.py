"""Integración de `bloquear_tarjeta` (camino exitoso) vía sesión MCP en memoria (spec 005 §7)."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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

from core_banking_mcp.application.use_cases.block_card import BlockCard
from core_banking_mcp.application.use_cases.verify_identity import VerifyIdentity
from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.infrastructure.inbound.mcp.card_tools import register_card_tools
from core_banking_mcp.infrastructure.inbound.mcp.identity_tools import register_identity_tools
from core_banking_mcp.infrastructure.inbound.mcp.schemas import BloquearTarjetaOut
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    CardBlockRow,
    CardRow,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_card_repository import (
    SqlAlchemyCardRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)
from core_banking_mcp.infrastructure.outbound.verification.in_memory_verification_store import (
    InMemoryConversationVerificationStore,
)

_PAN = "4111111111114321"
_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_CARD_1 = "CARD-0001"
_CARD_2 = "CARD-0002"
_RESPONSE_FIELDS = {"card_id", "masked_card", "status", "blocked_at", "reason", "already_blocked"}
_REASONS = ["FRAUD_SUSPECTED", "LOST_OR_STOLEN"]


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

    async def block(
        self,
        *,
        reason: str = "FRAUD_SUSPECTED",
        key: str = "K-1",
        card_id: str = _CARD_1,
        conversation_id: str = "A",
    ) -> _Result:
        result = await self.client.call_tool(
            "bloquear_tarjeta",
            {
                "conversation_id": conversation_id,
                "card_id": card_id,
                "reason": reason,
                "idempotency_key": key,
            },
        )
        text = "".join(getattr(block, "text", "") for block in result.content)
        return _Result(result.isError, result.structuredContent or {}, text)

    async def verify(self, conversation_id: str) -> None:
        result = await self.client.call_tool(
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

    def card_status(self, card_ref: str) -> str:
        self.db.expire_all()
        return self.db.scalars(select(CardRow.status).where(CardRow.card_ref == card_ref)).one()

    def blocks(self, card_ref: str | None = None) -> list[CardBlockRow]:
        self.db.expire_all()
        query = select(CardBlockRow).order_by(CardBlockRow.block_id)
        if card_ref is not None:
            query = query.join(CardRow, CardRow.card_id == CardBlockRow.card_id).where(
                CardRow.card_ref == card_ref
            )
        return list(self.db.scalars(query))


@asynccontextmanager
async def _harness(
    *,
    card_status: CardStatus = CardStatus.ACTIVE,
    clock_at: datetime = _NOW,
    verified: bool = True,
) -> AsyncIterator[_Harness]:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    db = session_factory(engine)()
    customers = SqlAlchemyCustomerRepository(db)
    customers.add(
        CustomerBuilder()
        .with_id("C-0001")
        .with_name("Laura Méndez")
        .with_document("D-1001")
        .with_cards(Card("4321", card_status), Card("8765", CardStatus.ACTIVE))
        .build(),
        {"4321": _PAN},
        identity=IdentityBuilder().build(),
    )
    store = InMemoryConversationVerificationStore()
    if verified:
        store.save("A", VerificationState().with_verified("C-0001"))
    clock = _MutableClock(clock_at)
    audit = FakeAuditLog()
    block_card = BlockCard(SqlAlchemyCardRepository(db), store, audit, clock)
    verify_identity = VerifyIdentity(customers, store, audit, clock)
    mcp = FastMCP("core-banking-test")
    register_card_tools(mcp, block_card)
    register_identity_tools(mcp, verify_identity)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        yield _Harness(client, db, clock, store)


# Regla: RN-005-01 — La solicitud indica la tarjeta por su `card_id`, el identificador opaco que devuelve `consultar_transacciones` (RN-003-12); además indica el motivo (`reason`) y una clave de reintento (`idempotency_key`) generada por el consumidor.  # noqa: E501
# Regla: RN-005-05 — Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada.  # noqa: E501
# Regla: RN-005-06 — Un bloqueo nuevo registra `blocked_at`, igual al instante del reloj inyectado en ISO 8601 con la zona de Bogotá (`−05:00`), y el `reason` recibido. Si una tarjeta ya bloqueada no tiene un bloqueo registrado (p. ej. por semilla), la respuesta trae `blocked_at = null` y `reason = null`.  # noqa: E501
# Regla: RN-005-10 — La respuesta exitosa contiene **solo** `card_id`, `masked_card` (`**** ` seguido de los 4 últimos dígitos, RN-001-09), `status` (`BLOCKED`), `blocked_at`, `reason` y `already_blocked`.  # noqa: E501
# AC-005-01 · Art. 7
async def test_ac_005_01_bloquear_tarjeta__active_card__blocks_card() -> None:
    """AC-005-01: una tarjeta activa queda BLOCKED con un bloqueo registrado."""
    async with _harness() as h:
        result = await h.block()

        assert result.is_error is False
        assert result.structured == {
            "card_id": _CARD_1,
            "masked_card": "**** 4321",
            "status": "BLOCKED",
            "blocked_at": "2026-10-17T10:00:00-05:00",
            "reason": "FRAUD_SUSPECTED",
            "already_blocked": False,
        }
        assert h.card_status(_CARD_1) == "BLOCKED"
        rows = h.blocks()
        assert [(row.reason, row.blocked_at) for row in rows] == [
            ("FRAUD_SUSPECTED", datetime(2026, 10, 17, 15, 0))
        ]


# Regla: RN-005-02 — El motivo es un código de un catálogo cerrado que distingue mayúsculas: `FRAUD_SUSPECTED` (sospecha de fraude) y `LOST_OR_STOLEN` (tarjeta perdida o robada). Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`.  # noqa: E501
# AC-005-02 · Art. 7
@pytest.mark.parametrize("reason", _REASONS, ids=_REASONS)
async def test_ac_005_02_bloquear_tarjeta__allowed_reason__blocks_card(reason: str) -> None:
    """AC-005-02: cada motivo del catálogo bloquea la tarjeta y se devuelve tal cual."""
    async with _harness() as h:
        result = await h.block(reason=reason)

        assert result.is_error is False
        assert result.structured["reason"] == reason
        assert h.card_status(_CARD_1) == "BLOCKED"
        assert [row.reason for row in h.blocks()] == [reason]


# Regla: RN-005-05 — Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada.  # noqa: E501
# Regla: RN-005-06 — Un bloqueo nuevo registra `blocked_at`, igual al instante del reloj inyectado en ISO 8601 con la zona de Bogotá (`−05:00`), y el `reason` recibido. Si una tarjeta ya bloqueada no tiene un bloqueo registrado (p. ej. por semilla), la respuesta trae `blocked_at = null` y `reason = null`.  # noqa: E501
# Regla: RN-005-12 — Bloquear una tarjeta solo cambia el estado de esa tarjeta y registra el bloqueo y la clave de reintento. No cambia las demás tarjetas del cliente, sus transacciones, sus disputas ni el estado de verificación de la conversación. No decide si hay fraude, no abre disputas ni escala.  # noqa: E501
# AC-005-04 · Art. 7 (fila ACTIVE)
async def test_ac_005_04_bloquear_tarjeta__previous_active__blocks_card() -> None:
    """AC-005-04 (fila ACTIVE): la tarjeta queda BLOCKED con 1 bloqueo y already_blocked=false."""
    async with _harness(card_status=CardStatus.ACTIVE) as h:
        result = await h.block()

        assert result.is_error is False
        assert result.structured["status"] == "BLOCKED"
        assert result.structured["already_blocked"] is False
        assert h.card_status(_CARD_1) == "BLOCKED"
        assert len(h.blocks(_CARD_1)) == 1


# Regla: RN-005-05 — Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada.  # noqa: E501
# Regla: RN-005-06 — Un bloqueo nuevo registra `blocked_at`, igual al instante del reloj inyectado en ISO 8601 con la zona de Bogotá (`−05:00`), y el `reason` recibido. Si una tarjeta ya bloqueada no tiene un bloqueo registrado (p. ej. por semilla), la respuesta trae `blocked_at = null` y `reason = null`.  # noqa: E501
# Regla: RN-005-12 — Bloquear una tarjeta solo cambia el estado de esa tarjeta y registra el bloqueo y la clave de reintento. No cambia las demás tarjetas del cliente, sus transacciones, sus disputas ni el estado de verificación de la conversación. No decide si hay fraude, no abre disputas ni escala.  # noqa: E501
# AC-005-04 · Art. 7 (fila BLOCKED con bloqueo original)
async def test_ac_005_04_bloquear_tarjeta__previous_blocked_with_record__returns_original() -> None:
    """AC-005-04 (fila BLOCKED): devuelve el bloqueo original y no registra otro."""
    async with _harness(clock_at=datetime(2026, 10, 15, 14, 0, tzinfo=UTC)) as h:
        first = await h.block(reason="LOST_OR_STOLEN", key="K-0")
        assert first.is_error is False
        h.clock.instant = _NOW

        result = await h.block()

        assert result.is_error is False
        assert result.structured["status"] == "BLOCKED"
        assert result.structured["already_blocked"] is True
        assert result.structured["blocked_at"] == "2026-10-15T09:00:00-05:00"
        assert result.structured["reason"] == "LOST_OR_STOLEN"
        assert len(h.blocks(_CARD_1)) == 1


# Regla: RN-005-05 — Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada.  # noqa: E501
# Regla: RN-005-06 — Un bloqueo nuevo registra `blocked_at`, igual al instante del reloj inyectado en ISO 8601 con la zona de Bogotá (`−05:00`), y el `reason` recibido. Si una tarjeta ya bloqueada no tiene un bloqueo registrado (p. ej. por semilla), la respuesta trae `blocked_at = null` y `reason = null`.  # noqa: E501
# Regla: RN-005-12 — Bloquear una tarjeta solo cambia el estado de esa tarjeta y registra el bloqueo y la clave de reintento. No cambia las demás tarjetas del cliente, sus transacciones, sus disputas ni el estado de verificación de la conversación. No decide si hay fraude, no abre disputas ni escala.  # noqa: E501
# AC-005-04 · Art. 7 (fila BLOCKED sin bloqueo registrado)
async def test_ac_005_04_bloquear_tarjeta__previous_blocked_seed__returns_null_block() -> None:
    """AC-005-04 (fila BLOCKED sin registro): blocked_at y reason son null y no se registra."""
    async with _harness(card_status=CardStatus.BLOCKED) as h:
        result = await h.block()

        assert result.is_error is False
        assert result.structured["status"] == "BLOCKED"
        assert result.structured["already_blocked"] is True
        assert result.structured["blocked_at"] is None
        assert result.structured["reason"] is None
        assert h.blocks() == []


# Regla: RN-005-07 — La clave de reintento es única **dentro de cada conversación** y solo se registra cuando se crea un bloqueo nuevo. Si la conversación ya usó la clave con la **misma** tarjeta y el **mismo** motivo, se devuelve el resultado de esa solicitud (mismo `blocked_at` y `already_blocked = false`) sin registrar otro bloqueo. Si la usó con otra tarjeta u otro motivo, se rechaza con `INVALID_INPUT` y no se cambia nada. La misma clave en otra conversación es una solicitud independiente.  # noqa: E501
# Regla: RN-005-09 — Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) clave de reintento ya usada en la conversación → el bloqueo existente (misma solicitud) o `INVALID_INPUT` (solicitud distinta); (4) tarjeta del cliente verificado → `NOT_FOUND`; (5) estado de la tarjeta → `CARD_NOT_BLOCKABLE` (cancelada), `already_blocked` (bloqueada) o bloqueo nuevo (activa).  # noqa: E501
# AC-005-05 · Art. 7
async def test_ac_005_05_bloquear_tarjeta__same_request_repeated__returns_same_block() -> None:
    """AC-005-05: repetir la solicitud devuelve la misma respuesta y no duplica el bloqueo."""
    async with _harness() as h:
        first = await h.block()
        h.clock.instant = _NOW + timedelta(hours=1)

        second = await h.block()

        assert first.is_error is False
        assert second.is_error is False
        assert second.structured == first.structured
        assert second.structured["already_blocked"] is False
        assert second.structured["blocked_at"] == "2026-10-17T10:00:00-05:00"
        assert len(h.blocks(_CARD_1)) == 1


# Regla: RN-005-07 — La clave de reintento es única **dentro de cada conversación** y solo se registra cuando se crea un bloqueo nuevo. Si la conversación ya usó la clave con la **misma** tarjeta y el **mismo** motivo, se devuelve el resultado de esa solicitud (mismo `blocked_at` y `already_blocked = false`) sin registrar otro bloqueo. Si la usó con otra tarjeta u otro motivo, se rechaza con `INVALID_INPUT` y no se cambia nada. La misma clave en otra conversación es una solicitud independiente.  # noqa: E501
# AC-005-07 · Art. 7
async def test_ac_005_07_bloquear_tarjeta__same_key_other_conversation__is_independent() -> None:
    """AC-005-07: la clave de A no aplica en B; B recibe already_blocked con el bloqueo de A."""
    async with _harness(verified=False) as h:
        await h.verify("A")
        await h.verify("B")
        first = await h.block(conversation_id="A")
        h.clock.instant = _NOW + timedelta(hours=1)

        result = await h.block(conversation_id="B")

        assert first.is_error is False
        assert result.is_error is False
        assert result.structured["already_blocked"] is True
        assert result.structured["blocked_at"] == first.structured["blocked_at"]
        assert len(h.blocks(_CARD_1)) == 1


# Regla: RN-005-12 — Bloquear una tarjeta solo cambia el estado de esa tarjeta y registra el bloqueo y la clave de reintento. No cambia las demás tarjetas del cliente, sus transacciones, sus disputas ni el estado de verificación de la conversación. No decide si hay fraude, no abre disputas ni escala.  # noqa: E501
# AC-005-12 · Art. 7
async def test_ac_005_12_bloquear_tarjeta__other_card__stays_active() -> None:
    """AC-005-12: la otra tarjeta del cliente sigue ACTIVE y sin bloqueos."""
    async with _harness() as h:
        result = await h.block()

        assert result.is_error is False
        assert h.card_status(_CARD_1) == "BLOCKED"
        assert h.card_status(_CARD_2) == "ACTIVE"
        assert h.blocks(_CARD_2) == []


# Regla: RN-005-10 — La respuesta exitosa contiene **solo** `card_id`, `masked_card` (`**** ` seguido de los 4 últimos dígitos, RN-001-09), `status` (`BLOCKED`), `blocked_at`, `reason` y `already_blocked`.  # noqa: E501
# Regla: RN-005-11 — La respuesta nunca contiene el número completo de ninguna tarjeta, el documento del cliente ni su nombre, ni datos de otros clientes.  # noqa: E501
# AC-005-13 · Art. 7
async def test_ac_005_13_bloquear_tarjeta__success__protects_personal_data() -> None:
    """AC-005-13: la respuesta solo trae los campos permitidos y ningún dato personal."""
    async with _harness() as h:
        result = await h.block()

        assert result.is_error is False
        out = result.structured
        assert set(out) == _RESPONSE_FIELDS
        assert out["masked_card"] == "**** 4321"
        assert _PAN not in out["card_id"]
        serialized = json.dumps(out, ensure_ascii=False) + result.text
        for forbidden in (_PAN, "D-1001", "Laura Méndez"):
            assert forbidden not in serialized
        BloquearTarjetaOut.model_validate(out)
