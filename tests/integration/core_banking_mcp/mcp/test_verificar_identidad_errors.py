"""Integración de `verificar_identidad`: errores, entradas inválidas y auditoría (spec 002)."""

import io
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pytest
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.failing_customer_repository import FailingCustomerRepository
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder

from core_banking_mcp.application.ports.customer_repository import CustomerRepository
from core_banking_mcp.application.use_cases.verify_identity import VerifyIdentity
from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.infrastructure.inbound.mcp.identity_tools import register_identity_tools
from core_banking_mcp.infrastructure.outbound.audit.json_audit_log import JsonAuditLog
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)
from core_banking_mcp.infrastructure.outbound.verification.in_memory_verification_store import (
    InMemoryConversationVerificationStore,
)

_PANS = {"4321": "4111111111114321", "8765": "5500000000008765"}
_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_VALID: dict[str, Any] = {
    "conversation_id": "conv-1",
    "customer_id": "C-0001",
    "birth_date": "1990-03-15",
    "document_issue_date": "2008-04-20",
}
_ALL_DATES = ("1990-03-15", "2008-04-20", "1990-03-16", "1985-07-02", "2003-08-10")


@dataclass
class _Harness:
    session: ClientSession
    store: InMemoryConversationVerificationStore
    stream: io.StringIO

    async def call(self, **overrides: Any) -> tuple[bool, dict[str, Any], str]:
        """Invoca la herramienta; un override con valor `_ABSENT` omite el argumento."""
        args = {k: v for k, v in {**_VALID, **overrides}.items() if v is not _ABSENT}
        result = await self.session.call_tool("verificar_identidad", args)
        text = "".join(getattr(block, "text", "") for block in result.content)
        return result.isError, result.structuredContent or {}, text

    def audit_lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]


_ABSENT = object()


def _sqlite_repo() -> SqlAlchemyCustomerRepository:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    repo = SqlAlchemyCustomerRepository(session_factory(engine)())
    laura = (
        CustomerBuilder()
        .with_id("C-0001")
        .with_name("Laura Méndez")
        .with_document("D-1001")
        .with_cards(Card("4321", CardStatus.ACTIVE))
        .build()
    )
    pedro = (
        CustomerBuilder()
        .with_id("C-0002")
        .with_name("Pedro Ruiz")
        .with_document("D-1002")
        .with_cards(Card("8765", CardStatus.ACTIVE))
        .build()
    )
    repo.add(
        laura,
        _PANS,
        identity=IdentityBuilder()
        .with_birth_date(date(1990, 3, 15))
        .with_issue_date(date(2008, 4, 20))
        .build(),
    )
    repo.add(
        pedro,
        _PANS,
        identity=IdentityBuilder()
        .with_birth_date(date(1985, 7, 2))
        .with_issue_date(date(2003, 8, 10))
        .build(),
    )
    return repo


@asynccontextmanager
async def _harness(
    repo: CustomerRepository | None = None, now: datetime = _NOW
) -> AsyncIterator[_Harness]:
    store = InMemoryConversationVerificationStore()
    stream = io.StringIO()
    use_case = VerifyIdentity(
        repo if repo is not None else _sqlite_repo(),
        store,
        JsonAuditLog(stream=stream),
        FixedClock(now),
    )
    mcp = FastMCP("core-banking-test")
    register_identity_tools(mcp, use_case)
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        yield _Harness(session, store, stream)


def _assert_error(structured: dict[str, Any], code: str) -> None:
    assert set(structured) == {"code", "message", "retryable"}
    assert structured["code"] == code
    assert structured["retryable"] is False


def _assert_untouched(h: _Harness) -> None:
    state = h.store.get("conv-1")
    assert state.verified_customer_id is None
    assert state.failed_attempts == 0


# Regla: RN-002-07 - cada dato inválido de la tabla es INVALID_INPUT, sin reintento.
# AC-002-08 · Art. 7 (las filas de la tabla, incluidos customer_id y conversation_id ausentes)
@pytest.mark.parametrize(
    "overrides",
    [
        {"birth_date": ""},
        {"document_issue_date": ""},
        {"birth_date": _ABSENT},
        {"document_issue_date": _ABSENT},
        {"birth_date": None},
        {"document_issue_date": None},
        {"birth_date": "1990-02-31"},
        {"document_issue_date": "2008-02-31"},
        {"birth_date": "15/03/1990"},
        {"birth_date": "2026-10-18"},
        {"document_issue_date": "2026-10-18"},
        {"birth_date": "1990-03-15", "document_issue_date": "1990-03-14"},
        {"customer_id": "   "},
        {"customer_id": ""},
        {"customer_id": _ABSENT},
        {"customer_id": "C" * 33},
        {"conversation_id": "   "},
        {"conversation_id": ""},
        {"conversation_id": _ABSENT},
    ],
    ids=[
        "birth_empty",
        "issue_empty",
        "birth_absent",
        "issue_absent",
        "birth_null",
        "issue_null",
        "birth_nonexistent",
        "issue_nonexistent",
        "birth_bad_format",
        "birth_future",
        "issue_future",
        "issue_before_birth",
        "customer_blank",
        "customer_empty",
        "customer_absent",
        "customer_33_chars",
        "conversation_blank",
        "conversation_empty",
        "conversation_absent",
    ],
)
async def test_ac_002_08_verificar_identidad__invalid_input__returns_invalid_input(
    overrides: dict[str, Any],
) -> None:
    """AC-002-08: cada fila inválida devuelve isError, INVALID_INPUT y retryable=false."""
    async with _harness() as h:
        is_error, structured, _ = await h.call(**overrides)

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        _assert_untouched(h)


# Regla: RN-002-02 y RN-002-07 - fechas intercambiadas: expedición anterior al nacimiento.
# AC-002-03 · Art. 7 (INVALID_INPUT no cuenta intento)
async def test_ac_002_03_verificar_identidad__swapped_dates__returns_invalid_input() -> None:
    """AC-002-03: fechas intercambiadas dan INVALID_INPUT sin verificar ni contar fallos."""
    async with _harness() as h:
        is_error, structured, _ = await h.call(
            birth_date="2008-04-20", document_issue_date="1990-03-15"
        )

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        _assert_untouched(h)


# Regla: RN-002-07 y RN-002-08 - "hoy" es la fecha de Bogotá (UTC-05) del reloj inyectado.
# AC-002-09 · Art. 7 (bordes: medianoche en Bogotá e igualdad con el nacimiento)
@pytest.mark.parametrize(
    ("instant", "issue", "invalid"),
    [
        (datetime(2026, 10, 17, 15, 0, tzinfo=UTC), "2026-10-17", False),
        (datetime(2026, 10, 18, 3, 0, tzinfo=UTC), "2026-10-18", True),
        (datetime(2026, 10, 18, 5, 0, tzinfo=UTC), "2026-10-18", False),
        (datetime(2026, 10, 17, 15, 0, tzinfo=UTC), "1990-03-15", False),
    ],
    ids=["today_in_bogota", "still_17_in_bogota", "already_18_in_bogota", "issue_equals_birth"],
)
async def test_ac_002_09_verificar_identidad__date_limits__follow_bogota_today(
    instant: datetime, issue: str, invalid: bool
) -> None:
    """AC-002-09: los 4 instantes del reloj fijo dan datos válidos o INVALID_INPUT."""
    async with _harness(now=instant) as h:
        is_error, structured, _ = await h.call(customer_id="C-9999", document_issue_date=issue)

        if invalid:
            assert is_error is True
            _assert_error(structured, "INVALID_INPUT")
        else:
            assert is_error is False
            assert structured["verified"] is False


# Regla: RN-002-04 y RN-002-07 - un dato inválido no consume intentos.
# AC-002-10 · Art. 10 (borde: 2 fallos previos)
async def test_ac_002_10_verificar_identidad__invalid_after_two_failures__keeps_attempts() -> None:
    """AC-002-10: con 2 fallos, una fecha inválida y luego fechas correctas verifican."""
    async with _harness() as h:
        h.store.save("conv-1", VerificationState(failed_attempts=2))

        is_error, structured, _ = await h.call(birth_date="1990-02-31")
        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert h.store.get("conv-1").failed_attempts == 2

        is_error, structured, _ = await h.call()

        assert is_error is False
        assert structured["verified"] is True


# Regla: RN-002-16 - una falla inesperada es INTERNAL sin detalles ni cambio de estado.
# AC-002-16 · Art. 10 (retryable=false implica escalar)
async def test_ac_002_16_verificar_identidad__repository_fails__returns_internal() -> None:
    """AC-002-16: repositorio caído da INTERNAL sin el texto de la excepción ni estado."""
    async with _harness(repo=FailingCustomerRepository()) as h:
        is_error, structured, text = await h.call()

        assert is_error is True
        _assert_error(structured, "INTERNAL")
        for leaked in ("detalle interno secreto", "RuntimeError", "Traceback", "SELECT"):
            assert leaked not in structured["message"]
            assert leaked not in text
        _assert_untouched(h)


# Regla: RN-002-15 - cada invocación deja un registro de auditoría sin las fechas.
# AC-002-15 · Art. 8 (trazabilidad total; los 8 casos de la tabla)
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("verified", {"outcome": "verified"}),
        ("already_verified", {"outcome": "already_verified"}),
        ("first_failure", {"outcome": "failed", "intento": 1}),
        ("third_failure", {"outcome": "locked"}),
        ("locked_conversation", {"outcome": "locked"}),
        ("other_customer", {"outcome": "other_customer"}),
        ("invalid_input", {"outcome": "error", "error_code": "INVALID_INPUT"}),
        ("internal", {"outcome": "error", "error_code": "INTERNAL"}),
    ],
    ids=[
        "verified",
        "already_verified",
        "first_failure",
        "third_failure",
        "locked_conversation",
        "other_customer",
        "invalid_input",
        "internal",
    ],
)
async def test_ac_002_15_verificar_identidad__any_case__audits_one_line_without_dates(
    case: str, expected: dict[str, Any]
) -> None:
    """AC-002-15: una sola línea JSON con tool, customer_id y resultado, sin fechas."""
    repo = FailingCustomerRepository() if case == "internal" else None
    overrides: dict[str, Any] = {}
    async with _harness(repo=repo) as h:
        match case:
            case "already_verified":
                h.store.save("conv-1", VerificationState(verified_customer_id="C-0001"))
            case "other_customer":
                h.store.save("conv-1", VerificationState(verified_customer_id="C-0002"))
            case "first_failure":
                overrides = {"birth_date": "1990-03-16"}
            case "third_failure":
                h.store.save("conv-1", VerificationState(failed_attempts=2))
                overrides = {"birth_date": "1990-03-16"}
            case "locked_conversation":
                h.store.save("conv-1", VerificationState(failed_attempts=3))
            case "invalid_input":
                overrides = {"birth_date": "1990-02-31"}

        await h.call(**overrides)

        lines = h.audit_lines()
        assert len(lines) == 1
        line = lines[0]
        assert line["tool"] == "verificar_identidad"
        assert line["conversation_id"] == "conv-1"
        assert line["customer_id"] == "C-0001"
        assert line["timestamp"] == _NOW.isoformat()
        for key, value in expected.items():
            assert line[key] == value
        raw = h.stream.getvalue()
        for sent in (*_ALL_DATES, overrides.get("birth_date", "")):
            if sent:
                assert sent not in raw
