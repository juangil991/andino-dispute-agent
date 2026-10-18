"""Integración de `buscar_cliente` vía sesión MCP en memoria: respuestas exitosas (spec 001 §7)."""

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.failing_customer_repository import FailingCustomerRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder

from core_banking_mcp.application.use_cases.search_customers import (
    SearchCustomers,
    SearchCustomersCommand,
)
from core_banking_mcp.domain.models.customer import Card, CardStatus, Customer
from core_banking_mcp.domain.models.search import CustomerSearchResult
from core_banking_mcp.infrastructure.inbound.mcp.schemas import BuscarClienteOut
from core_banking_mcp.infrastructure.inbound.mcp.tools import register_tools
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)

_PANS = {"4321": "4111111111114321", "8765": "5500000000008765"}


@asynccontextmanager
async def _client(
    customers: Sequence[Customer], *, use_case: SearchCustomers | None = None
) -> AsyncIterator[ClientSession]:
    if use_case is None:
        engine = create_engine_from_url("sqlite:///:memory:")
        create_schema(engine)
        repo = SqlAlchemyCustomerRepository(session_factory(engine)())
        for customer in customers:
            repo.add(customer, _PANS, identity=IdentityBuilder().build())
        use_case = SearchCustomers(repo, FakeAuditLog(), FixedClock())
    mcp = FastMCP("core-banking-test")
    register_tools(mcp, use_case)
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        yield session


async def _call(
    customers: Sequence[Customer], arguments: dict[str, Any]
) -> tuple[bool, dict[str, Any], str]:
    return await _call_raw(customers, {"conversation_id": "conv-1", **arguments})


async def _call_raw(
    customers: Sequence[Customer],
    arguments: dict[str, Any],
    *,
    use_case: SearchCustomers | None = None,
) -> tuple[bool, dict[str, Any], str]:
    async with _client(customers, use_case=use_case) as session:
        result = await session.call_tool("buscar_cliente", arguments)
    text = "".join(getattr(block, "text", "") for block in result.content)
    return result.isError, result.structuredContent or {}, text


def _laura() -> Customer:
    return (
        CustomerBuilder()
        .with_id("C-0001")
        .with_name("Laura Méndez")
        .with_document("D-1001")
        .with_cards(Card("4321", CardStatus.ACTIVE), Card("8765", CardStatus.BLOCKED))
        .build()
    )


# Regla: RN-001-01 - un documento coincidente devuelve ese cliente con datos mínimos.
# AC-001-01 · Art. 7 (excepción explícita de buscar_cliente)
async def test_ac_001_01_buscar_cliente__single_document__returns_one_customer() -> None:
    """AC-001-01: por documento se devuelve un cliente con los 4 campos exactos."""
    is_error, structured, _ = await _call([_laura()], {"document": "d-1001"})

    assert is_error is False
    assert structured == {
        "customers": [
            {
                "customer_id": "C-0001",
                "full_name": "Laura Méndez",
                "masked_document": "****01",
                "masked_cards": ["**** 4321", "**** 8765"],
                "cards": [
                    {"card_id": "CARD-0001", "masked_card": "**** 4321"},
                    {"card_id": "CARD-0002", "masked_card": "**** 8765"},
                ],
            }
        ],
        "refinement_required": False,
    }
    BuscarClienteOut.model_validate(structured)


# Regla: RN-007-31 — Cada cliente devuelto por `buscar_cliente` incorpora `cards`: lista de
# `{card_id, masked_card}` de sus tarjetas en cualquier estado, en el mismo orden que
# `masked_cards`, que no cambia. No incluye el estado ni el número de la tarjeta.
# AC-007-32 · Art. 7
async def test_ac_007_32_buscar_cliente__customer_with_two_cards__returns_cards_with_card_id() -> (
    None
):
    """AC-007-32: cada cliente trae `cards` con card_id y masked_card, sin PAN ni estado."""
    customer = (
        CustomerBuilder()
        .with_id("C-0001")
        .with_document("D-1001")
        .with_card("4321", CardStatus.ACTIVE)
        .with_card("8765", CardStatus.BLOCKED)
        .build()
    )

    is_error, structured, text = await _call([customer], {"document": "D-1001"})

    assert is_error is False
    match = structured["customers"][0]
    assert match["masked_cards"] == ["**** 4321", "**** 8765"]
    assert match["cards"] == [
        {"card_id": "CARD-0001", "masked_card": "**** 4321"},  # CARD-L1 en la spec
        {"card_id": "CARD-0002", "masked_card": "**** 8765"},  # CARD-L2 en la spec
    ]
    assert all(set(card) == {"card_id", "masked_card"} for card in match["cards"])
    assert "4111111111114321" not in text
    assert "BLOCKED" not in text
    assert "ACTIVE" not in text
    BuscarClienteOut.model_validate(structured)


# Regla: RN-007-31 — Cada cliente devuelto por `buscar_cliente` incorpora `cards`: lista de
# `{card_id, masked_card}` de sus tarjetas en cualquier estado, en el mismo orden que
# `masked_cards`, que no cambia. No incluye el estado ni el número de la tarjeta.
# AC-007-32 · Art. 7
async def test_ac_007_32_buscar_cliente__refinement_required__returns_no_cards() -> None:
    """AC-007-32: con refinement_required = true no se devuelve ningún cliente ni tarjeta."""
    customers = [
        CustomerBuilder()
        .with_id(f"C-{n:04d}")
        .with_name("Ana Pérez")
        .with_document(f"D-80{n}")
        .with_card("4321")
        .build()
        for n in range(6)
    ]

    is_error, structured, _ = await _call(customers, {"full_name": "Ana Pérez"})

    assert is_error is False
    assert structured == {"customers": [], "refinement_required": True}


# Regla: RN-001-04 - la tarjeta coincide por últimos 4 sin importar su estado.
# AC-001-03 · Art. 7
@pytest.mark.parametrize("status", list(CardStatus), ids=lambda s: s.value.lower())
async def test_ac_001_03_buscar_cliente__card_last4_any_status__returns_customer(
    status: CardStatus,
) -> None:
    """AC-001-03: los últimos 4 dígitos encuentran tarjetas activas, bloqueadas o canceladas."""
    customer = CustomerBuilder().with_id("C-0002").with_cards(Card("1234", status)).build()

    is_error, structured, _ = await _call([customer], {"card_last4": "1234"})

    assert is_error is False
    assert [c["customer_id"] for c in structured["customers"]] == ["C-0002"]
    assert structured["customers"][0]["masked_cards"] == ["**** 1234"]


# Regla: RN-001-06 - los homónimos se devuelven ordenados por customer_id.
# AC-001-04 · Art. 7
async def test_ac_001_04_buscar_cliente__homonyms__returns_distinguishable_customers() -> None:
    """AC-001-04: dos homónimos se devuelven distinguibles por id y documento enmascarado."""
    ana2 = CustomerBuilder().with_id("C-0004").with_name("Ana Torres").with_document("D-2002")
    ana1 = CustomerBuilder().with_id("C-0003").with_name("Ana Torres").with_document("D-2001")

    is_error, structured, _ = await _call([ana2.build(), ana1.build()], {"full_name": "ana torres"})

    assert is_error is False
    customers = structured["customers"]
    assert [c["customer_id"] for c in customers] == ["C-0003", "C-0004"]
    assert [c["masked_document"] for c in customers] == ["****01", "****02"]
    assert structured["refinement_required"] is False


# Regla: RN-001-07 - sin coincidencias es un éxito con lista vacía.
# AC-001-06 · Art. 7
async def test_ac_001_06_buscar_cliente__no_matches__returns_empty_success() -> None:
    """AC-001-06: sin coincidencias se responde éxito, lista vacía y sin refinamiento."""
    is_error, structured, _ = await _call([_laura()], {"document": "NO-EXISTE"})

    assert is_error is False
    assert structured == {"customers": [], "refinement_required": False}


# Regla: RN-001-07 - más de 5 coincidencias exige refinar y no devuelve clientes.
# AC-001-07 · Art. 7 (borde: 6 coincidencias)
async def test_ac_001_07_buscar_cliente__six_matches__requires_refinement() -> None:
    """AC-001-07: con 6 coincidencias se devuelve lista vacía y refinement_required=true."""
    customers = [
        CustomerBuilder()
        .with_id(f"C-10{i}")
        .with_name("Juan Pérez")
        .with_document(f"D-90{i}")
        .build()
        for i in range(6)
    ]

    is_error, structured, _ = await _call(customers, {"full_name": "Juan Perez"})

    assert is_error is False
    assert structured == {"customers": [], "refinement_required": True}


# Regla: Art. 7 - buscar_cliente no exige identidad verificada ni la marca.
# AC-001-10 · Art. 7
async def test_ac_001_10_buscar_cliente__unverified_conversation__returns_customer() -> None:
    """AC-001-10: responde sin verificación previa y sin parámetros de identidad."""
    async with _client([_laura()]) as session:
        tools = (await session.list_tools()).tools
        tool = next(t for t in tools if t.name == "buscar_cliente")
        properties = set(tool.inputSchema["properties"])
        assert properties == {"conversation_id", "document", "full_name", "card_last4"}
        assert tool.inputSchema.get("required", []) == []
        assert tool.outputSchema == BuscarClienteOut.model_json_schema()

        result = await session.call_tool(
            "buscar_cliente", {"conversation_id": "conv-sin-verificar", "document": "D-1001"}
        )

    assert result.isError is False
    assert result.structuredContent is not None
    assert len(result.structuredContent["customers"]) == 1


# Regla: RN-001-09 - la respuesta nunca contiene el documento completo ni el PAN.
# AC-001-11 · Art. 7 y Art. 9 (mínima exposición)
async def test_ac_001_11_buscar_cliente__response_never_contains_full_document_or_pan() -> None:
    """AC-001-11: ni el JSON estructurado ni el texto incluyen documento completo ni PAN."""
    is_error, structured, text = await _call([_laura()], {"document": "D-1001"})

    serialized = json.dumps(structured) + text
    assert is_error is False
    assert "D-1001" not in serialized
    assert "4111111111114321" not in serialized
    assert "5500000000008765" not in serialized


_INVALID_ROWS: list[Any] = [
    pytest.param({}, id="no_criteria"),
    pytest.param({"document": ""}, id="empty_document"),
    pytest.param({"document": "D" * 33}, id="document_33_chars"),
    pytest.param({"full_name": "   "}, id="blank_full_name"),
    pytest.param({"full_name": "N" * 101}, id="full_name_101_chars"),
    pytest.param({"card_last4": "123"}, id="card_last4_3_digits"),
    pytest.param({"card_last4": "12345"}, id="card_last4_5_digits"),
    pytest.param({"card_last4": "12a4"}, id="card_last4_non_digit"),
    pytest.param({"conversation_id": None, "document": "D-1001"}, id="conversation_id_missing"),
    pytest.param({"conversation_id": "", "document": "D-1001"}, id="conversation_id_empty"),
]


# Regla: RN-001-05 - toda entrada inválida se rechaza con INVALID_INPUT no reintentable.
# AC-001-09 · Art. 10 (retryable=false escala) y Art. 7 (sin datos de cliente)
@pytest.mark.parametrize("arguments", _INVALID_ROWS)
async def test_ac_001_09_buscar_cliente__invalid_input__returns_invalid_input_error(
    arguments: dict[str, Any],
) -> None:
    """AC-001-09: cada fila inválida devuelve isError y el sobre INVALID_INPUT sin datos."""
    args: dict[str, Any] = {"conversation_id": "conv-1", **arguments}
    args = {k: v for k, v in args.items() if v is not None}

    is_error, structured, text = await _call_raw([_laura()], args)

    assert is_error is True
    assert set(structured) == {"code", "message", "retryable"}
    assert structured["code"] == "INVALID_INPUT"
    assert isinstance(structured["message"], str) and structured["message"]
    assert structured["retryable"] is False
    assert json.loads(text) == structured
    serialized = json.dumps(structured) + text
    assert "customers" not in structured
    assert "C-0001" not in serialized
    assert "Laura" not in serialized


# Regla: RN-001-13 - una falla del core se reporta como INTERNAL no reintentable, sin detalle.
# AC-001-14 · Art. 10 (ante falla no recuperable, escalar)
async def test_ac_001_14_buscar_cliente__repository_failure__returns_internal_not_retryable() -> (
    None
):
    """AC-001-14: la falla del repositorio produce INTERNAL, retryable=false y sin el texto."""
    use_case = SearchCustomers(FailingCustomerRepository(), FakeAuditLog(), FixedClock())

    is_error, structured, text = await _call_raw(
        [], {"conversation_id": "conv-1", "document": "D-1001"}, use_case=use_case
    )

    assert is_error is True
    assert structured["code"] == "INTERNAL"
    assert structured["retryable"] is False
    assert json.loads(text) == structured
    assert "secreto" not in json.dumps(structured) + text
    assert "fallo simulado" not in json.dumps(structured) + text


class _ExplodingSearchCustomers(SearchCustomers):
    def __init__(self) -> None:
        super().__init__(FailingCustomerRepository(), FakeAuditLog(), FixedClock())

    def execute(self, command: SearchCustomersCommand) -> CustomerSearchResult:
        raise ValueError("detalle interno")


# Regla: RN-001-13 - cualquier excepción inesperada se mapea a INTERNAL (catch-all defensivo).
# AC-001-14 · Art. 10
async def test_ac_001_14_buscar_cliente__unexpected_exception__returns_internal_not_retryable() -> (
    None
):
    """AC-001-14: una excepción inesperada no se filtra y produce INTERNAL sin el texto."""
    is_error, structured, text = await _call_raw(
        [],
        {"conversation_id": "conv-1", "document": "D-1001"},
        use_case=_ExplodingSearchCustomers(),
    )

    assert is_error is True
    assert structured["code"] == "INTERNAL"
    assert structured["retryable"] is False
    assert "detalle interno" not in json.dumps(structured) + text
