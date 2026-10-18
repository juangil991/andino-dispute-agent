"""Integración de `bloquear_tarjeta`: errores, identidad y auditoría (spec 005 §7)."""

import io
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.failing_card_repository import FailingCardRepository
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.owned_card_builder import OwnedCardBuilder

from core_banking_mcp.application.ports.card_repository import CardRepository
from core_banking_mcp.application.use_cases.block_card import BlockCard
from core_banking_mcp.application.use_cases.verify_identity import VerifyIdentity
from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.infrastructure.inbound.mcp.card_tools import register_card_tools
from core_banking_mcp.infrastructure.inbound.mcp.identity_tools import register_identity_tools
from core_banking_mcp.infrastructure.outbound.audit.json_audit_log import JsonAuditLog
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
_PAN_PEDRO = "5500000000001234"
_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_CARD_1 = "CARD-0001"  # CARD-L1 de la spec: de C-0001, terminada en 4321
_CARD_2 = "CARD-0002"  # CARD-L2: de C-0001, terminada en 8765
_CARD_PEDRO = "CARD-0003"  # CARD-P1: de C-0002, terminada en 1234
_VALID: dict[str, Any] = {
    "conversation_id": "A",
    "card_id": _CARD_1,
    "reason": "FRAUD_SUSPECTED",
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
    card_repo: CardRepository

    async def call(self, **overrides: Any) -> tuple[bool, dict[str, Any], str]:
        """Invoca la herramienta; un override con valor `_ABSENT` omite el argumento."""
        args = {k: v for k, v in {**_VALID, **overrides}.items() if v is not _ABSENT}
        result = await self.session.call_tool("bloquear_tarjeta", args)
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

    def card_status(self, card_ref: str) -> str:
        if isinstance(self.card_repo, FailingCardRepository):
            card = self.card_repo.find_customer_card("C-0001", card_ref)
            assert card is not None
            return card.status.value
        self.db.expire_all()
        return self.db.scalars(select(CardRow.status).where(CardRow.card_ref == card_ref)).one()

    def all_statuses(self) -> dict[str, str]:
        if isinstance(self.card_repo, FailingCardRepository):
            return {_CARD_1: self.card_status(_CARD_1)}
        self.db.expire_all()
        rows = self.db.execute(select(CardRow.card_ref, CardRow.status))
        return {card_ref: status for card_ref, status in rows}

    def blocks(self) -> list[tuple[int, str, str]]:
        """(card, reason, conversation) de todos los bloqueos del almacén."""
        if isinstance(self.card_repo, FailingCardRepository):
            return [(0, b.reason.value, b.conversation_id) for b in self.card_repo.blocks]
        self.db.expire_all()
        rows = self.db.scalars(select(CardBlockRow).order_by(CardBlockRow.block_id))
        return [(row.card_id, row.reason, row.conversation_id) for row in rows]

    def cancel_directly(self, card_ref: str) -> None:
        self.db.execute(
            update(CardRow)
            .where(CardRow.card_ref == card_ref)
            .values(status=CardStatus.CANCELLED.value)
        )
        self.db.commit()

    def audit_lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]


@asynccontextmanager
async def _harness(
    *,
    card_status: CardStatus = CardStatus.ACTIVE,
    verified: bool = True,
    failing: bool = False,
    with_pedro: bool = False,
    pedro_status: CardStatus = CardStatus.ACTIVE,
) -> AsyncIterator[_Harness]:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    db = session_factory(engine)()
    customers = SqlAlchemyCustomerRepository(db)
    pans = {"4321": _PAN, "8765": "5500000000008765", "1234": _PAN_PEDRO}
    customers.add(
        CustomerBuilder()
        .with_id("C-0001")
        .with_name("Laura Méndez")
        .with_document("D-1001")
        .with_cards(Card("4321", card_status), Card("8765", CardStatus.ACTIVE))
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
            .with_cards(Card("1234", pedro_status))
            .build(),
            pans,
            identity=IdentityBuilder().build(),
        )
    card_repo: CardRepository = (
        FailingCardRepository({"C-0001": [OwnedCardBuilder().build()]})
        if failing
        else SqlAlchemyCardRepository(db)
    )
    store = InMemoryConversationVerificationStore()
    if verified:
        store.save("A", VerificationState().with_verified("C-0001"))
    stream = io.StringIO()
    audit = JsonAuditLog(stream=stream)
    clock = FixedClock(_NOW)
    mcp = FastMCP("core-banking-test")
    register_card_tools(mcp, BlockCard(card_repo, store, audit, clock))
    register_identity_tools(mcp, VerifyIdentity(customers, store, audit, clock))
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        yield _Harness(client, db, store, stream, card_repo)


def _assert_error(structured: dict[str, Any], code: str) -> None:
    assert set(structured) == _ERROR_FIELDS
    assert structured["code"] == code
    assert structured["retryable"] is False


# Regla: RN-005-03 — La herramienta exige que la conversación esté verificada en el servidor (estado de RN-002-13). Se rechaza con `IDENTITY_NOT_VERIFIED` toda conversación sin verificación exitosa, desconocida o bloqueada por agotar sus intentos. La verificación no se traslada: estar verificada en otra conversación no cuenta.  # noqa: E501
# AC-005-09 · Art. 7 (las 4 situaciones de la tabla)
@pytest.mark.parametrize(
    "situation",
    ["never_verified", "one_failed_attempt", "locked", "verified_in_other_conversation"],
)
async def test_ac_005_09_bloquear_tarjeta__unverified_conversation__returns_identity_not_verified(
    situation: str,
) -> None:
    """AC-005-09: sin identidad verificada en la conversación no se bloquea ninguna tarjeta."""
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
        statuses = h.all_statuses()

        is_error, structured, _ = await h.call(conversation_id=conversation)

        assert is_error is True
        _assert_error(structured, "IDENTITY_NOT_VERIFIED")
        assert statuses[_CARD_1] == "ACTIVE"
        assert h.all_statuses() == statuses
        assert h.blocks() == []
        assert {key: h.store.get(key) for key in before} == before


# Regla: RN-005-02 — El motivo es un código de un catálogo cerrado que distingue mayúsculas: `FRAUD_SUSPECTED` (sospecha de fraude) y `LOST_OR_STOLEN` (tarjeta perdida o robada). Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`.  # noqa: E501
# Regla: RN-005-08 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_id` obligatorio, de 1 a 64 caracteres tras recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-005-02. Toda violación ⇒ `INVALID_INPUT`, sin cambiar ninguna tarjeta.  # noqa: E501
# AC-005-03 · Art. 10 (las 5 filas de la tabla; ausente y null por separado)
@pytest.mark.parametrize(
    "reason",
    ["STOLEN", "fraud_suspected", "sospecha de fraude", "", _ABSENT, None],
    ids=["not_in_catalog", "lowercase", "free_text", "empty", "absent", "null"],
)
async def test_ac_005_03_bloquear_tarjeta__invalid_reason__returns_invalid_input(
    reason: Any,
) -> None:
    """AC-005-03: un motivo fuera del catálogo devuelve INVALID_INPUT sin registrar bloqueo."""
    async with _harness() as h:
        statuses = h.all_statuses()

        is_error, structured, _ = await h.call(reason=reason)

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert h.all_statuses() == statuses
        assert statuses[_CARD_1] == "ACTIVE"
        assert h.blocks() == []


# Regla: RN-005-05 — Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada.  # noqa: E501
# AC-005-04 · Art. 7 (fila CANCELLED)
async def test_ac_005_04_bloquear_tarjeta__previous_cancelled__returns_card_not_blockable() -> None:
    """AC-005-04 (fila CANCELLED): CARD_NOT_BLOCKABLE; la tarjeta sigue CANCELLED sin bloqueos."""
    async with _harness(card_status=CardStatus.CANCELLED) as h:
        is_error, structured, _ = await h.call()

        assert is_error is True
        _assert_error(structured, "CARD_NOT_BLOCKABLE")
        assert h.card_status(_CARD_1) == "CANCELLED"
        assert h.blocks() == []


# Regla: RN-005-07 — La clave de reintento es única **dentro de cada conversación** y solo se registra cuando se crea un bloqueo nuevo. Si la conversación ya usó la clave con la **misma** tarjeta y el **mismo** motivo, se devuelve el resultado de esa solicitud (mismo `blocked_at` y `already_blocked = false`) sin registrar otro bloqueo. Si la usó con otra tarjeta u otro motivo, se rechaza con `INVALID_INPUT` y no se cambia nada. La misma clave en otra conversación es una solicitud independiente.  # noqa: E501
# AC-005-06 · Art. 10 (las 2 filas de la tabla)
@pytest.mark.parametrize(
    ("card_id", "reason"),
    [(_CARD_2, "FRAUD_SUSPECTED"), (_CARD_1, "LOST_OR_STOLEN")],
    ids=["other_card", "other_reason"],
)
async def test_ac_005_06_bloquear_tarjeta__key_reused_with_other_data__returns_invalid_input(
    card_id: str, reason: str
) -> None:
    """AC-005-06: reutilizar K-1 con otros datos devuelve INVALID_INPUT sin bloqueo adicional."""
    async with _harness() as h:
        first = await h.call()
        assert first[0] is False
        before = h.blocks()
        statuses = h.all_statuses()

        is_error, structured, _ = await h.call(
            card_id=card_id, reason=reason, idempotency_key="K-1"
        )

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert h.blocks() == before
        assert len(before) == 1
        assert h.all_statuses() == statuses
        assert statuses[_CARD_2] == "ACTIVE"


# Regla: RN-005-04 — La tarjeta debe pertenecer al cliente verificado en la conversación. Si no es así, porque es de otro cliente o porque no existe, se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en ambos casos y sin datos de ningún cliente.  # noqa: E501
# AC-005-08 · Art. 7 (tarjeta ajena frente a inexistente)
async def test_ac_005_08_bloquear_tarjeta__foreign_or_unknown_card__same_not_found() -> None:
    """AC-005-08: `CARD-P1` (de C-0002) y `CARD-9999` devuelven el mismo NOT_FOUND sin datos."""
    async with _harness(with_pedro=True) as h:
        foreign = await h.call(card_id=_CARD_PEDRO)
        unknown = await h.call(card_id="CARD-9999", idempotency_key="K-2")

        for is_error, structured, _ in (foreign, unknown):
            assert is_error is True
            _assert_error(structured, "NOT_FOUND")
        assert foreign[1] == unknown[1]
        assert h.all_statuses()[_CARD_PEDRO] == "ACTIVE"
        assert h.blocks() == []
        for leaked in (_CARD_PEDRO, "Pedro", "D-1002", _PAN_PEDRO, "1234", "C-0002"):
            assert leaked not in foreign[2]


# Regla: RN-005-08 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_id` obligatorio, de 1 a 64 caracteres tras recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-005-02. Toda violación ⇒ `INVALID_INPUT`, sin cambiar ninguna tarjeta.  # noqa: E501
# AC-005-10 · Art. 10 (las 7 filas de la tabla; ausente y null por separado)
@pytest.mark.parametrize(
    "overrides",
    [
        {"card_id": _ABSENT},
        {"card_id": None},
        {"card_id": ""},
        {"card_id": "   "},
        {"card_id": "C" * 65},
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
        "card_absent",
        "card_null",
        "card_empty",
        "card_blank",
        "card_65_chars",
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
async def test_ac_005_10_bloquear_tarjeta__invalid_fields__returns_invalid_input(
    overrides: dict[str, Any],
) -> None:
    """AC-005-10: cada dato inválido devuelve INVALID_INPUT, retryable=false y sin bloqueo."""
    async with _harness() as h:
        statuses = h.all_statuses()

        is_error, structured, _ = await h.call(**overrides)

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert h.all_statuses() == statuses
        assert h.blocks() == []


# Regla: RN-005-09 — Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) clave de reintento ya usada en la conversación → el bloqueo existente (misma solicitud) o `INVALID_INPUT` (solicitud distinta); (4) tarjeta del cliente verificado → `NOT_FOUND`; (5) estado de la tarjeta → `CARD_NOT_BLOCKABLE` (cancelada), `already_blocked` (bloqueada) o bloqueo nuevo (activa).  # noqa: E501
# AC-005-11 · Art. 7 (las 5 filas de la tabla)
@pytest.mark.parametrize(
    "row",
    [
        "unverified_invalid_reason",
        "unverified_unknown_card",
        "key_reused_unknown_card",
        "foreign_cancelled_card",
        "key_replay_after_cancel",
    ],
)
async def test_ac_005_11_bloquear_tarjeta__multiple_failures__returns_first_check_result(
    row: str,
) -> None:
    """AC-005-11: se devuelve el primer resultado en el orden de comprobaciones de RN-005-09."""
    overrides: dict[str, Any] = {}
    kwargs: dict[str, Any] = {}
    match row:
        case "unverified_invalid_reason":
            expected, overrides, kwargs = "INVALID_INPUT", {"reason": "STOLEN"}, {"verified": False}
        case "unverified_unknown_card":
            expected, overrides, kwargs = (
                "IDENTITY_NOT_VERIFIED",
                {"card_id": "CARD-9999"},
                {"verified": False},
            )
        case "key_reused_unknown_card":
            expected = "INVALID_INPUT"
            overrides = {"card_id": "CARD-9999", "idempotency_key": "K-1"}
        case "foreign_cancelled_card":
            expected, overrides = "NOT_FOUND", {"card_id": _CARD_PEDRO}
            kwargs = {"with_pedro": True, "pedro_status": CardStatus.CANCELLED}
        case _:
            expected = "blocked"
    async with _harness(**kwargs) as h:
        if row in ("key_reused_unknown_card", "key_replay_after_cancel"):
            first = await h.call()
            assert first[0] is False
        if row == "key_replay_after_cancel":
            h.cancel_directly(_CARD_1)

        is_error, structured, _ = await h.call(**overrides)

        if expected == "blocked":
            assert is_error is False
            assert structured["already_blocked"] is False
            assert structured["reason"] == "FRAUD_SUSPECTED"
            assert structured["blocked_at"] == "2026-10-17T10:00:00-05:00"
        else:
            assert is_error is True
            _assert_error(structured, expected)


# Regla: RN-005-13 — Ante una falla inesperada (p. ej. el repositorio de tarjetas no responde al bloquear), la herramienta devuelve `INTERNAL` con `retryable = false` y sin detalles internos (trazas, SQL, texto de la excepción). La operación es atómica: la tarjeta conserva su estado anterior y no queda registrado ningún bloqueo ni clave de reintento.  # noqa: E501
# AC-005-14 · Art. 10 (retryable=false implica escalar)
async def test_ac_005_14_bloquear_tarjeta__repository_fails__returns_internal() -> None:
    """AC-005-14: una falla al bloquear da INTERNAL, la tarjeta sigue ACTIVE y la clave libre."""
    async with _harness(failing=True) as h:
        is_error, structured, text = await h.call()

        assert is_error is True
        _assert_error(structured, "INTERNAL")
        for leaked in ("detalle interno secreto", "RuntimeError", "Traceback", "SELECT"):
            assert leaked not in structured["message"]
            assert leaked not in text
        assert h.card_status(_CARD_1) == "ACTIVE"
        assert h.blocks() == []

        assert isinstance(h.card_repo, FailingCardRepository)
        h.card_repo.repair()
        retry_error, retry, _ = await h.call()

        assert retry_error is False
        assert retry["already_blocked"] is False
        assert h.card_status(_CARD_1) == "BLOCKED"


# Regla: RN-005-14 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "bloquear_tarjeta"`; el `card_id`, el `reason` y la `idempotency_key` recibidos (cada uno vacío si no es válido según RN-005-08, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); y el resultado.  # noqa: E501
# AC-005-15 · Art. 8 (trazabilidad total; los 10 casos de la tabla)
@pytest.mark.parametrize(
    "case",
    [
        "blocked",
        "replayed",
        "already_blocked",
        "cancelled",
        "not_found",
        "invalid",
        "pan_in_card_id",
        "pan_in_key",
        "unverified",
        "internal",
    ],
)
async def test_ac_005_15_bloquear_tarjeta__any_case__audits_one_line_without_personal_data(
    case: str,
) -> None:
    """AC-005-15: una sola línea JSON con herramienta, datos recibidos y resultado, sin PAN."""
    overrides: dict[str, Any] = {}
    kwargs: dict[str, Any] = {}
    match case:
        case "already_blocked":
            kwargs = {"card_status": CardStatus.BLOCKED}
        case "cancelled":
            kwargs = {"card_status": CardStatus.CANCELLED}
        case "not_found":
            overrides, kwargs = {"card_id": _CARD_PEDRO}, {"with_pedro": True}
        case "invalid":
            overrides = {"reason": "STOLEN"}
        case "pan_in_card_id":
            overrides = {"card_id": _PAN}
        case "pan_in_key":
            overrides = {"idempotency_key": f"bloqueo-{_PAN}"}
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

        await h.call(**overrides)

        lines = h.audit_lines()
        assert len(lines) == 1
        line = lines[0]
        assert line["tool"] == "bloquear_tarjeta"
        assert line["conversation_id"] == "A"
        assert line["timestamp"] == _NOW.isoformat()
        expected_card = {"not_found": _CARD_PEDRO, "pan_in_card_id": "[REDACTED]"}.get(
            case, _CARD_1
        )
        assert line["card_id"] == expected_card
        expected_key = "bloqueo-[REDACTED]" if case == "pan_in_key" else "K-1"
        assert line["idempotency_key"] == expected_key
        if case == "invalid":
            assert line.get("block_reason") in (None, "")
        else:
            assert line["block_reason"] == "FRAUD_SUSPECTED"
        if case in ("not_found", "pan_in_card_id", "unverified", "invalid"):
            assert line.get("masked_card") in (None, "")
        elif case != "internal":
            assert line["masked_card"] == "**** 4321"
        expected_outcome = {"pan_in_key": "blocked"}.get(case, case)
        match case:
            case "blocked" | "pan_in_key" | "replayed" | "already_blocked":
                assert line["outcome"] == expected_outcome
            case "cancelled":
                assert line["error_code"] == "CARD_NOT_BLOCKABLE"
            case "not_found" | "pan_in_card_id":
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
