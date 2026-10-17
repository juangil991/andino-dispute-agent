"""Integración de `verificar_identidad` vía sesión MCP en memoria: camino exitoso (spec 002 §7)."""

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
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder

from core_banking_mcp.application.use_cases.verify_identity import VerifyIdentity
from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.infrastructure.inbound.mcp.identity_tools import register_identity_tools
from core_banking_mcp.infrastructure.inbound.mcp.schemas import VerificarIdentidadOut
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
_CORRECT = ("1990-03-15", "2008-04-20")
_WRONG_BIRTH = ("1990-03-16", "2008-04-20")


@dataclass
class _Harness:
    session: ClientSession
    store: InMemoryConversationVerificationStore

    async def verify(
        self,
        customer_id: str,
        dates: tuple[str, str],
        conversation_id: str = "conv-1",
    ) -> tuple[bool, dict[str, Any], str]:
        result = await self.session.call_tool(
            "verificar_identidad",
            {
                "conversation_id": conversation_id,
                "customer_id": customer_id,
                "birth_date": dates[0],
                "document_issue_date": dates[1],
            },
        )
        text = "".join(getattr(block, "text", "") for block in result.content)
        return result.isError, result.structuredContent or {}, text


@asynccontextmanager
async def _harness() -> AsyncIterator[_Harness]:
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
    store = InMemoryConversationVerificationStore()
    use_case = VerifyIdentity(
        repo, store, FakeAuditLog(), FixedClock(datetime(2026, 10, 17, 15, 0, tzinfo=UTC))
    )
    mcp = FastMCP("core-banking-test")
    register_identity_tools(mcp, use_case)
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        yield _Harness(session, store)


def _assert_response(structured: dict[str, Any], verified: bool, remaining: int, esc: bool) -> None:
    assert structured == {
        "verified": verified,
        "attempts_remaining": remaining,
        "escalation_required": esc,
    }
    VerificarIdentidadOut.model_validate(structured)


# Regla: RN-002-02 - ambas fechas iguales a las registradas verifican al cliente.
# AC-002-01 · Art. 7 (excepción explícita de verificar_identidad)
async def test_ac_002_01_verificar_identidad__correct_dates__verifies_customer() -> None:
    """AC-002-01: con ambas fechas correctas se verifica y el almacén indica C-0001."""
    async with _harness() as h:
        is_error, structured, _ = await h.verify("C-0001", _CORRECT)

        assert is_error is False
        _assert_response(structured, True, 3, False)
        assert h.store.get("conv-1").verified_customer_id == "C-0001"


# Regla: RN-002-09 - la verificación dura mientras viva el proceso, entre llamadas.
# AC-002-01 · Art. 7 (llamadas posteriores, incluida la de otro cliente, no la alteran)
async def test_ac_002_01_verificar_identidad__persists_across_calls__stays_verified() -> None:
    """AC-002-01: tras verificar a C-0001, nuevas llamadas no cambian el cliente verificado."""
    async with _harness() as h:
        await h.verify("C-0001", _CORRECT)
        assert h.store.get("conv-1").verified_customer_id == "C-0001"

        await h.verify("C-0001", _WRONG_BIRTH)
        assert h.store.get("conv-1").verified_customer_id == "C-0001"

        await h.verify("C-0002", ("1985-07-02", "2003-08-10"))
        assert h.store.get("conv-1").verified_customer_id == "C-0001"


# Regla: RN-002-02 - basta una fecha distinta para no verificar, sin revelar cuál.
# AC-002-02 · Art. 7
@pytest.mark.parametrize(
    "dates",
    [("1990-03-16", "2008-04-20"), ("1990-03-15", "2008-04-21"), ("1990-03-16", "2008-04-21")],
    ids=["birth_wrong", "issue_wrong", "both_wrong"],
)
async def test_ac_002_02_verificar_identidad__one_wrong_date__not_verified(
    dates: tuple[str, str],
) -> None:
    """AC-002-02: una fecha incorrecta responde false/2/false sin cliente verificado."""
    async with _harness() as h:
        is_error, structured, _ = await h.verify("C-0001", dates)

        assert is_error is False
        _assert_response(structured, False, 2, False)
        assert h.store.get("conv-1").verified_customer_id is None


# Regla: RN-002-03 - un cliente inexistente responde igual que unas fechas incorrectas.
# AC-002-04 · Art. 7
async def test_ac_002_04_verificar_identidad__unknown_customer__same_response_as_wrong() -> None:
    """AC-002-04: C-9999 devuelve la misma respuesta que fechas incorrectas y suma un fallo."""
    async with _harness() as h:
        _, wrong, _ = await h.verify("C-0001", _WRONG_BIRTH, "conv-a")
        is_error, unknown, _ = await h.verify("C-9999", _CORRECT, "conv-b")

        assert is_error is False
        assert unknown == wrong
        _assert_response(unknown, False, 2, False)
        assert h.store.get("conv-b").failed_attempts == 1


# Regla: RN-002-04 y RN-002-06 - 3.er fallo bloquea y deriva; antes no.
# AC-002-05 · Art. 10 (borde: tercer fallo)
@pytest.mark.parametrize(
    ("previous", "remaining", "escalate"),
    [(0, 2, False), (1, 1, False), (2, 0, True)],
    ids=["no_previous", "one_previous", "two_previous_locks"],
)
async def test_ac_002_05_verificar_identidad__failed_attempts_limit__counts_and_escalates(
    previous: int, remaining: int, escalate: bool
) -> None:
    """AC-002-05: con 0, 1 y 2 fallos previos el contador y la derivación son los de la tabla."""
    async with _harness() as h:
        h.store.save("conv-1", VerificationState(failed_attempts=previous))

        is_error, structured, _ = await h.verify("C-0001", _WRONG_BIRTH)

        assert is_error is False
        _assert_response(structured, False, remaining, escalate)


# Regla: RN-002-05 - antes de bloquear, fechas correctas verifican pese a fallos previos.
# AC-002-06 · Art. 7 (borde: 2 fallos previos)
async def test_ac_002_06_verificar_identidad__correct_dates_after_two_failures__verifies() -> None:
    """AC-002-06: con 2 fallos previos las fechas correctas verifican y quedan 1 intento."""
    async with _harness() as h:
        h.store.save("conv-1", VerificationState(failed_attempts=2))

        is_error, structured, _ = await h.verify("C-0001", _CORRECT)

        assert is_error is False
        _assert_response(structured, True, 1, False)
        assert h.store.get("conv-1").verified_customer_id == "C-0001"


# Regla: RN-002-05 - una conversación bloqueada no verifica ni con fechas correctas.
# AC-002-07 · Art. 10 (borde: 3 fallos)
async def test_ac_002_07_verificar_identidad__locked_conversation__never_verifies() -> None:
    """AC-002-07: con 3 fallos previos, fechas correctas dan false/0/true sin verificar."""
    async with _harness() as h:
        h.store.save("conv-1", VerificationState(failed_attempts=3))

        is_error, structured, _ = await h.verify("C-0001", _CORRECT)

        assert is_error is False
        _assert_response(structured, False, 0, True)
        assert h.store.get("conv-1").verified_customer_id is None


# Regla: RN-002-10 - una conversación se verifica para un solo cliente.
# AC-002-11 · Art. 7
@pytest.mark.parametrize(
    ("customer_id", "dates"),
    [
        ("C-0002", ("1985-07-02", "2003-08-10")),
        ("C-0002", ("1985-07-03", "2003-08-10")),
        ("C-9999", _CORRECT),
    ],
    ids=["other_correct", "other_wrong", "unknown"],
)
async def test_ac_002_11_verificar_identidad__verified_for_other_customer__rejected(
    customer_id: str, dates: tuple[str, str]
) -> None:
    """AC-002-11: otro cliente no se verifica, no cuenta intento y se conserva C-0001."""
    async with _harness() as h:
        await h.verify("C-0001", _CORRECT)

        is_error, structured, _ = await h.verify(customer_id, dates)

        assert is_error is False
        _assert_response(structured, False, 3, False)
        assert h.store.get("conv-1").verified_customer_id == "C-0001"


# Regla: RN-002-11 - re-verificar al mismo cliente es idempotente y no compara fechas.
# AC-002-12 · Art. 7
@pytest.mark.parametrize("dates", [_CORRECT, _WRONG_BIRTH], ids=["correct_dates", "wrong_dates"])
async def test_ac_002_12_verificar_identidad__same_customer_again__idempotent(
    dates: tuple[str, str],
) -> None:
    """AC-002-12: repetir para el mismo cliente da true/3/false sin intentos fallidos."""
    async with _harness() as h:
        await h.verify("C-0001", _CORRECT)

        is_error, structured, _ = await h.verify("C-0001", dates)

        assert is_error is False
        _assert_response(structured, True, 3, False)
        state = h.store.get("conv-1")
        assert state.verified_customer_id == "C-0001"
        assert state.failed_attempts == 0


# Regla: RN-002-12 - la verificación pertenece a su conversación y el contador es propio.
# AC-002-13 · Art. 7
async def test_ac_002_13_verificar_identidad__other_conversation__not_verified() -> None:
    """AC-002-13: B no hereda la verificación de A y tiene su propio contador."""
    async with _harness() as h:
        await h.verify("C-0001", _CORRECT, "conv-a")
        assert h.store.get("conv-b").verified_customer_id is None

        is_error, structured, _ = await h.verify("C-0001", _WRONG_BIRTH, "conv-b")

        assert is_error is False
        _assert_response(structured, False, 2, False)
        assert h.store.get("conv-b").verified_customer_id is None
        assert h.store.get("conv-a").verified_customer_id == "C-0001"


# Regla: RN-002-14 - la respuesta contiene solo los tres campos y ningún dato personal.
# AC-002-14 · Art. 7 (mínima exposición)
@pytest.mark.parametrize("dates", [_CORRECT, _WRONG_BIRTH], ids=["correct_dates", "wrong_dates"])
async def test_ac_002_14_verificar_identidad__any_outcome__exposes_no_personal_data(
    dates: tuple[str, str],
) -> None:
    """AC-002-14: la respuesta serializada tiene 3 campos y no contiene datos personales."""
    async with _harness() as h:
        is_error, structured, text = await h.verify("C-0001", dates)

        assert is_error is False
        assert set(structured) == {"verified", "attempts_remaining", "escalation_required"}
        assert set(json.loads(text)) == set(structured)
        serialized = json.dumps(structured, ensure_ascii=False) + text
        for forbidden in ("1990-03-15", "2008-04-20", "Laura Méndez", "D-1001", "4111111111114321"):
            assert forbidden not in serialized
