"""Contrato del lado cliente: los modelos espejo del agente frente a la salida real del core."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import BaseModel, ValidationError
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.failing_customer_repository import FailingCustomerRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.use_cases.block_card import BlockCard
from core_banking_mcp.application.use_cases.escalate_to_analyst import EscalateToAnalyst
from core_banking_mcp.application.use_cases.list_card_transactions import ListCardTransactions
from core_banking_mcp.application.use_cases.open_dispute import OpenDispute
from core_banking_mcp.application.use_cases.search_customers import SearchCustomers
from core_banking_mcp.application.use_cases.verify_identity import VerifyIdentity
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.infrastructure.inbound.mcp.card_tools import register_card_tools
from core_banking_mcp.infrastructure.inbound.mcp.dispute_tools import register_dispute_tools
from core_banking_mcp.infrastructure.inbound.mcp.escalation_tools import (
    register_escalation_tools,
)
from core_banking_mcp.infrastructure.inbound.mcp.identity_tools import register_identity_tools
from core_banking_mcp.infrastructure.inbound.mcp.tools import register_tools
from core_banking_mcp.infrastructure.inbound.mcp.transaction_tools import (
    register_transaction_tools,
)
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_card_repository import (
    SqlAlchemyCardRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_customer_repository import (
    SqlAlchemyCustomerRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_dispute_repository import (
    SqlAlchemyDisputeRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_escalation_repository import (
    SqlAlchemyEscalationRepository,
)
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_transaction_repository import (
    SqlAlchemyTransactionRepository,
)
from core_banking_mcp.infrastructure.outbound.verification.in_memory_verification_store import (
    InMemoryConversationVerificationStore,
)
from dispute_agent.infrastructure.outbound.mcp.response_models import (
    BloquearTarjetaModel,
    BuscarClienteModel,
    ConsultarTransaccionesModel,
    EscalarAnalistaModel,
    IniciarDisputaModel,
    ToolErrorEnvelope,
    VerificarIdentidadModel,
)

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_BOGOTA = timezone(timedelta(hours=-5))
_PAN = "4111111111114321"
_CARD = "CARD-0001"
_TX = "TX-L1"
_VERIFIED = "A"
_UNVERIFIED = "B"

_CALLS: dict[str, dict[str, Any]] = {
    "buscar_cliente": {"conversation_id": _VERIFIED, "document": "D-1001"},
    "verificar_identidad": {
        "conversation_id": "C",
        "customer_id": "C-0001",
        "birth_date": "1985-03-14",
        "document_issue_date": "2005-04-02",
    },
    "consultar_transacciones": {
        "conversation_id": _VERIFIED,
        "card_last4": "4321",
        "date_from": "2026-10-01",
        "date_to": "2026-10-17",
    },
    "iniciar_disputa": {
        "conversation_id": _VERIFIED,
        "transaction_id": _TX,
        "reason": "UNRECOGNIZED_CHARGE",
        "idempotency_key": "K-1",
    },
    "bloquear_tarjeta": {
        "conversation_id": _VERIFIED,
        "card_id": _CARD,
        "reason": "FRAUD_SUSPECTED",
        "idempotency_key": "K-2",
    },
    "escalar_a_analista": {
        "conversation_id": _VERIFIED,
        "reason": "FRAUD_SUSPECTED",
        "idempotency_key": "K-3",
        "transaction_id": _TX,
        "card_id": _CARD,
    },
}

_MODELS: dict[str, type[BaseModel]] = {
    "buscar_cliente": BuscarClienteModel,
    "verificar_identidad": VerificarIdentidadModel,
    "consultar_transacciones": ConsultarTransaccionesModel,
    "iniciar_disputa": IniciarDisputaModel,
    "bloquear_tarjeta": BloquearTarjetaModel,
    "escalar_a_analista": EscalarAnalistaModel,
}
_TOOLS = list(_MODELS)
_TOOL_IDS = [t.replace("_", "-") for t in _TOOLS]


@asynccontextmanager
async def _session(*, failing: bool = False) -> AsyncIterator[ClientSession]:
    """Sesión MCP en memoria sobre el core real con SQLite en memoria y datos ficticios."""
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    db = session_factory(engine)()
    customers = SqlAlchemyCustomerRepository(db)
    customers.add(
        CustomerBuilder()
        .with_id("C-0001")
        .with_name("Laura Méndez")
        .with_document("D-1001")
        .with_card("4321")
        .with_card("8765")
        .build(),
        {"4321": _PAN, "8765": "5500000000008765"},
        identity=IdentityBuilder().build(),
    )
    transactions = SqlAlchemyTransactionRepository(db)
    transactions.add(
        _CARD,
        TransactionBuilder(merchant="Tienda Aurora")
        .with_id(_TX)
        .with_card(_CARD, "4321")
        .with_occurred_at(datetime(2026, 10, 10, 12, 0, tzinfo=_BOGOTA))
        .with_amount(Decimal("85000.00"))
        .build(),
    )
    disputes = SqlAlchemyDisputeRepository(db)
    cards = SqlAlchemyCardRepository(db)
    store = InMemoryConversationVerificationStore()
    store.save(_VERIFIED, VerificationState().with_verified("C-0001"))
    audit = FakeAuditLog()
    clock = FixedClock(_NOW)
    mcp = FastMCP("core-banking-contract")
    if failing:
        register_tools(mcp, SearchCustomers(FailingCustomerRepository(), audit, clock))
    else:
        register_tools(mcp, SearchCustomers(customers, audit, clock))
    register_identity_tools(mcp, VerifyIdentity(customers, store, audit, clock))
    register_transaction_tools(mcp, ListCardTransactions(transactions, store, audit, clock))
    register_dispute_tools(mcp, OpenDispute(transactions, disputes, store, audit, clock))
    register_card_tools(mcp, BlockCard(cards, store, audit, clock))
    register_escalation_tools(
        mcp,
        EscalateToAnalyst(
            transactions,
            cards,
            disputes,
            SqlAlchemyEscalationRepository(db),
            store,
            audit,
            clock,
        ),
    )
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        yield client


async def _real(tool: str) -> dict[str, Any]:
    async with _session() as session:
        result = await session.call_tool(tool, _CALLS[tool])
    assert result.isError is False, result.structuredContent
    assert result.structuredContent is not None
    return result.structuredContent


def _transaction_of(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    if tool == "consultar_transacciones":
        item: dict[str, Any] = payload["transactions"][0]
        return item
    if tool == "escalar_a_analista":
        summary_tx: dict[str, Any] = payload["summary"]["transaction"]
        return summary_tx
    transaction: dict[str, Any] = payload["transaction"]
    return transaction


# Regla: RN-007-31 — Cada cliente devuelto por `buscar_cliente` incorpora `cards`: lista de
# `{card_id, masked_card}` de sus tarjetas en cualquier estado, en el mismo orden que
# `masked_cards`, que no cambia. `card_id` es el mismo identificador opaco que usan
# `consultar_transacciones` y `bloquear_tarjeta`. No incluye el estado ni el número de la tarjeta.
# AC-007-32 · Art. 7
async def test_ac_007_32_client_contract__buscar_cliente__accepts_real_output_with_cards() -> None:
    """AC-007-32: el modelo espejo acepta la salida real con cards y rechaza campos extra."""
    payload = await _real("buscar_cliente")
    assert payload["customers"][0]["cards"]

    model = BuscarClienteModel.model_validate(payload)
    assert [c.card_id for c in model.customers[0].cards] == [_CARD, "CARD-0002"]

    payload["customers"][0]["cards"][0]["pan"] = _PAN
    with pytest.raises(ValidationError):
        BuscarClienteModel.model_validate(payload)


# Regla: RN-007-30 — `TransactionItem` (RN-003-12) incorpora `merchant_country`: el código
# ISO 3166-1 alfa-2 del país del comercio, en mayúsculas (`CO` = Colombia). Aparece en todas las
# respuestas que incluyen `TransactionItem` (`consultar_transacciones`, `iniciar_disputa`,
# `escalar_a_analista`). Toda transacción del core tiene país, también en las semillas.
# AC-007-33 · Art. 7
@pytest.mark.parametrize(
    "tool",
    ["consultar_transacciones", "iniciar_disputa", "escalar_a_analista"],
    ids=["consultar-transacciones", "iniciar-disputa", "escalar-a-analista"],
)
async def test_ac_007_33_client_contract__transaction_item__accepts_merchant_country(
    tool: str,
) -> None:
    """AC-007-33: el modelo espejo acepta merchant_country real y rechaza campos extra."""
    payload = await _real(tool)
    assert _transaction_of(tool, payload)["merchant_country"] == "CO"

    model = _MODELS[tool]
    model.model_validate(payload)

    _transaction_of(tool, payload)["unexpected"] = "x"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


# Soporte de tests: el camino feliz real de cada herramienta lo acepta el modelo espejo · Art. 3
@pytest.mark.parametrize("tool", _TOOLS, ids=_TOOL_IDS)
async def test_client_contract__happy_path__is_accepted_by_mirror_model(tool: str) -> None:
    """Soporte: la salida real de cada una de las 6 herramientas valida contra su modelo."""
    payload = await _real(tool)
    assert _MODELS[tool].model_validate(payload)


# Soporte de tests: un campo extra en la salida real se rechaza (extra="forbid") · Art. 3
@pytest.mark.parametrize("tool", _TOOLS, ids=_TOOL_IDS)
async def test_client_contract__extra_field__is_rejected_by_mirror_model(tool: str) -> None:
    """Soporte: un campo no declarado en la salida de cualquiera de las 6 herramientas falla."""
    payload = await _real(tool)
    payload["unexpected"] = "x"
    with pytest.raises(ValidationError):
        _MODELS[tool].model_validate(payload)


_UNVERIFIED_TX = {**_CALLS["consultar_transacciones"], "conversation_id": _UNVERIFIED}
_UNKNOWN_CARD_TX = {**_CALLS["consultar_transacciones"], "card_last4": "9999"}


# Soporte de tests: el sobre de error real lo parsea el modelo de error del cliente · Art. 3
@pytest.mark.parametrize(
    ("tool", "args", "failing", "code"),
    [
        ("buscar_cliente", {"conversation_id": _VERIFIED}, False, "INVALID_INPUT"),
        ("consultar_transacciones", _UNVERIFIED_TX, False, "IDENTITY_NOT_VERIFIED"),
        ("consultar_transacciones", _UNKNOWN_CARD_TX, False, "NOT_FOUND"),
        ("buscar_cliente", _CALLS["buscar_cliente"], True, "INTERNAL"),
    ],
    ids=["invalid-input", "identity-not-verified", "not-found", "internal"],
)
async def test_client_contract__error_envelope__is_parsed_by_client_error_model(
    tool: str, args: dict[str, Any], failing: bool, code: str
) -> None:
    """Soporte: INVALID_INPUT, IDENTITY_NOT_VERIFIED, NOT_FOUND e INTERNAL se parsean."""
    async with _session(failing=failing) as session:
        result = await session.call_tool(tool, args)
    assert result.isError is True
    assert result.structuredContent is not None
    envelope = ToolErrorEnvelope.model_validate(result.structuredContent)
    assert envelope.code == code
    assert envelope.retryable is False

    with pytest.raises(ValidationError):
        ToolErrorEnvelope.model_validate({**result.structuredContent, "trace": "x"})
