"""Integración de `consultar_transacciones` vía sesión MCP en memoria (spec 003 §7)."""

import json
from collections.abc import AsyncIterator, Sequence
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
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.use_cases.list_card_transactions import ListCardTransactions
from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.domain.models.transaction import Transaction, TransactionStatus
from core_banking_mcp.infrastructure.inbound.mcp.schemas import ConsultarTransaccionesOut
from core_banking_mcp.infrastructure.inbound.mcp.transaction_tools import (
    register_transaction_tools,
)
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
_BOGOTA = timezone(timedelta(hours=-5))
_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_FIRST_CARD = "CARD-0001"
_SECOND_CARD = "CARD-0002"
_RESPONSE_FIELDS = {
    "transaction_id",
    "occurred_at",
    "merchant",
    "amount",
    "currency",
    "status",
    "card_id",
    "masked_card",
}


def _tx(
    transaction_id: str,
    occurred_at: datetime,
    *,
    card_id: str = _FIRST_CARD,
    amount: str = "100.00",
    currency: str = "COP",
    status: TransactionStatus = TransactionStatus.CONFIRMED,
) -> tuple[str, Transaction]:
    built = (
        TransactionBuilder()
        .with_id(transaction_id)
        .with_card(card_id, "4321")
        .with_occurred_at(occurred_at)
        .with_amount(Decimal(amount))
        .with_currency(currency)
        .with_status(status)
        .build()
    )
    return card_id, built


def _sept(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 9, day, hour, 0, tzinfo=_BOGOTA)


@dataclass
class _Harness:
    session: ClientSession

    async def consult(
        self,
        card_last4: str = "4321",
        date_from: str = "2026-09-01",
        date_to: str = "2026-09-30",
        conversation_id: str = "conv-1",
    ) -> tuple[bool, dict[str, Any], str]:
        result = await self.session.call_tool(
            "consultar_transacciones",
            {
                "conversation_id": conversation_id,
                "card_last4": card_last4,
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        text = "".join(getattr(block, "text", "") for block in result.content)
        return result.isError, result.structuredContent or {}, text


@asynccontextmanager
async def _harness(
    transactions: Sequence[tuple[str, Transaction]] = (),
    *,
    card_status: CardStatus = CardStatus.ACTIVE,
    two_cards: bool = False,
    now: datetime = _NOW,
) -> AsyncIterator[_Harness]:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    session = session_factory(engine)()
    customers = SqlAlchemyCustomerRepository(session)
    cards = [Card("4321", card_status)] + ([Card("4321", CardStatus.ACTIVE)] if two_cards else [])
    customers.add(
        CustomerBuilder()
        .with_id("C-0001")
        .with_name("Laura Méndez")
        .with_document("D-1001")
        .with_cards(*cards)
        .build(),
        {"4321": _PAN},
        identity=IdentityBuilder().build(),
    )
    repo = SqlAlchemyTransactionRepository(session)
    for card_ref, transaction in transactions:
        repo.add(card_ref, transaction)
    store = InMemoryConversationVerificationStore()
    store.save("conv-1", VerificationState().with_verified("C-0001"))
    use_case = ListCardTransactions(repo, store, FakeAuditLog(), FixedClock(now))
    mcp = FastMCP("core-banking-test")
    register_transaction_tools(mcp, use_case)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        yield _Harness(client)


def _ids(structured: dict[str, Any]) -> list[str]:
    return [item["transaction_id"] for item in structured["transactions"]]


# Regla: RN-003-01 — La solicitud indica la tarjeta por sus últimos 4 dígitos (`card_last4`) y el rango con `date_from` y `date_to` en formato ISO `AAAA-MM-DD`, ambos incluidos.  # noqa: E501
# Regla: RN-003-05 — Cada transacción tiene un instante `occurred_at` (fecha y hora con zona). Entra en el rango si su **fecha local en `America/Bogota`** está entre `date_from` y `date_to`, ambos incluidos.  # noqa: E501
# Regla: RN-003-11 — Las transacciones se ordenan de la más reciente a la más antigua por `occurred_at`; si dos tienen el mismo instante, por `transaction_id` ascendente (resultado determinista).  # noqa: E501
# Regla: RN-003-12 — Cada transacción devuelta contiene **solo**: `transaction_id`, `occurred_at`, `merchant`, `amount`, `currency`, `status`, `card_id` y `masked_card`.  # noqa: E501
# AC-003-01 · Art. 7
async def test_ac_003_01_consultar_transacciones__september_range__lists_newest_first() -> None:
    """AC-003-01: devuelve las 3 de septiembre, de la más reciente a la más antigua."""
    txs = [
        _tx("T-A", datetime(2026, 9, 5, 9, 15, tzinfo=_BOGOTA)),
        _tx("T-B", datetime(2026, 9, 12, 18, 0, tzinfo=_BOGOTA)),
        _tx("T-C", datetime(2026, 9, 20, 14, 32, tzinfo=_BOGOTA)),
        _tx("T-D", datetime(2026, 10, 2, 11, 0, tzinfo=_BOGOTA)),
    ]
    async with _harness(txs) as h:
        is_error, structured, _ = await h.consult()

        assert is_error is False
        assert structured["refinement_required"] is False
        assert _ids(structured) == ["T-C", "T-B", "T-A"]
        for item in structured["transactions"]:
            assert set(item) == _RESPONSE_FIELDS
            assert item["masked_card"] == "**** 4321"
        assert structured["transactions"][0]["occurred_at"] == "2026-09-20T14:32:00-05:00"
        ConsultarTransaccionesOut.model_validate(structured)


# Regla: RN-003-01 — La solicitud indica la tarjeta por sus últimos 4 dígitos (`card_last4`) y el rango con `date_from` y `date_to` en formato ISO `AAAA-MM-DD`, ambos incluidos.  # noqa: E501
# Regla: RN-003-05 — Cada transacción tiene un instante `occurred_at` (fecha y hora con zona). Entra en el rango si su **fecha local en `America/Bogota`** está entre `date_from` y `date_to`, ambos incluidos.  # noqa: E501
# AC-003-02 · Art. 7
@pytest.mark.parametrize(
    ("instant", "appears"),
    [
        (datetime(2026, 9, 1, 0, 0, 0, tzinfo=_BOGOTA), True),
        (datetime(2026, 9, 30, 23, 59, 59, tzinfo=_BOGOTA), True),
        (datetime(2026, 8, 31, 23, 59, 59, tzinfo=_BOGOTA), False),
        (datetime(2026, 10, 1, 0, 0, 0, tzinfo=_BOGOTA), False),
        (datetime(2026, 10, 1, 3, 30, tzinfo=UTC), True),
        (datetime(2026, 9, 1, 4, 30, tzinfo=UTC), False),
    ],
    ids=[
        "first_day_start",
        "last_day_end",
        "day_before_end",
        "day_after_start",
        "utc_next_month_is_bogota_last_day",
        "utc_same_month_is_bogota_previous_day",
    ],
)
async def test_ac_003_02_consultar_transacciones__range_edges__uses_bogota_date(
    instant: datetime, appears: bool
) -> None:
    """AC-003-02: los extremos del rango se evalúan por la fecha local de Bogotá."""
    async with _harness([_tx("T-1", instant)]) as h:
        is_error, structured, _ = await h.consult()

        assert is_error is False
        assert _ids(structured) == (["T-1"] if appears else [])


# Regla: RN-003-09 — Se devuelven transacciones en cualquier estado: confirmada (`CONFIRMED`), pendiente (`PENDING`) o reversada (`REVERSED`). El monto es siempre el original y positivo; la reversión se ve solo en el estado.  # noqa: E501
# AC-003-03 · Art. 7
@pytest.mark.parametrize("status", list(TransactionStatus), ids=lambda s: s.value)
async def test_ac_003_03_consultar_transacciones__any_status__is_listed(
    status: TransactionStatus,
) -> None:
    """AC-003-03: la transacción aparece con su estado y el monto original."""
    txs = [_tx("T-1", _sept(10), amount="125000.00", status=status)]
    async with _harness(txs) as h:
        is_error, structured, _ = await h.consult()

        assert is_error is False
        assert [(t["status"], t["amount"]) for t in structured["transactions"]] == [
            (status.value, "125000.00")
        ]


# Regla: RN-003-03 — Se consultan **todas** las tarjetas del cliente verificado en la conversación que terminan en `card_last4`, **sea cual sea su estado** (activa, bloqueada, cancelada); sus transacciones se devuelven juntas en una sola lista.  # noqa: E501
# AC-003-04 · Art. 7
@pytest.mark.parametrize("card_status", list(CardStatus), ids=lambda s: s.name.lower())
async def test_ac_003_04_consultar_transacciones__any_card_status__lists_transactions(
    card_status: CardStatus,
) -> None:
    """AC-003-04: una tarjeta en cualquier estado devuelve sus 2 transacciones."""
    txs = [_tx("T-1", _sept(3)), _tx("T-2", _sept(4))]
    async with _harness(txs, card_status=card_status) as h:
        is_error, structured, _ = await h.consult()

        assert is_error is False
        assert _ids(structured) == ["T-2", "T-1"]


# Regla: RN-003-03 — Se consultan **todas** las tarjetas del cliente verificado en la conversación que terminan en `card_last4`, **sea cual sea su estado** (activa, bloqueada, cancelada); sus transacciones se devuelven juntas en una sola lista.  # noqa: E501
# Regla: RN-003-12 — Cada transacción devuelta contiene **solo**: `transaction_id`, `occurred_at`, `merchant`, `amount`, `currency`, `status`, `card_id` y `masked_card`.  # noqa: E501
# AC-003-05 · Art. 7
async def test_ac_003_05_consultar_transacciones__two_cards_same_last4__distinct_card_ids() -> None:
    """AC-003-05: las dos tarjetas terminadas en 4321 se distinguen por `card_id`."""
    txs = [_tx("T-1", _sept(3), card_id=_FIRST_CARD), _tx("T-2", _sept(4), card_id=_SECOND_CARD)]
    async with _harness(txs, two_cards=True) as h:
        is_error, structured, _ = await h.consult()

        assert is_error is False
        items = structured["transactions"]
        assert len(items) == 2
        assert {item["masked_card"] for item in items} == {"**** 4321"}
        assert {item["card_id"] for item in items} == {_FIRST_CARD, _SECOND_CARD}
        by_id = {item["transaction_id"]: item["card_id"] for item in items}
        assert by_id == {"T-1": _FIRST_CARD, "T-2": _SECOND_CARD}


# Regla: RN-003-10 — Tope de 50 transacciones. Sin transacciones en el rango, la respuesta es exitosa con lista vacía y `refinement_required = false`. Con 1 a 50 se devuelven todas con `refinement_required = false`. Con más de 50, la respuesta es exitosa, **sin ninguna transacción** y con `refinement_required = true` para que se acote el rango.  # noqa: E501
# AC-003-06 · Art. 7
async def test_ac_003_06_consultar_transacciones__no_transactions__empty_success() -> None:
    """AC-003-06: sin transacciones responde éxito con lista vacía."""
    async with _harness() as h:
        is_error, structured, _ = await h.consult()

        assert is_error is False
        assert structured == {"transactions": [], "refinement_required": False}


# Regla: RN-003-06 — Validación de entrada: ... el rango no supera **90 días contando ambos extremos** (`date_to − date_from + 1 ≤ 90`). No hay límite hacia el pasado para `date_from`.  # noqa: E501
# AC-003-07 · Art. 10 (borde: 1, 89, 90 días y pasado lejano)
@pytest.mark.parametrize(
    ("date_from", "date_to"),
    [
        ("2026-09-10", "2026-09-10"),
        ("2026-06-01", "2026-08-28"),
        ("2026-06-01", "2026-08-29"),
        ("2019-01-01", "2019-01-31"),
    ],
    ids=["one_day", "89_days", "90_days", "far_past"],
)
async def test_ac_003_07_consultar_transacciones__valid_range_length__succeeds(
    date_from: str, date_to: str
) -> None:
    """AC-003-07: rangos de 1, 89, 90 días y de 2019 responden con éxito."""
    async with _harness() as h:
        is_error, structured, _ = await h.consult(date_from=date_from, date_to=date_to)

        assert is_error is False
        assert structured == {"transactions": [], "refinement_required": False}


# Regla: RN-003-10 — Tope de 50 transacciones. Sin transacciones en el rango, la respuesta es exitosa con lista vacía y `refinement_required = false`. Con 1 a 50 se devuelven todas con `refinement_required = false`. Con más de 50, la respuesta es exitosa, **sin ninguna transacción** y con `refinement_required = true` para que se acote el rango.  # noqa: E501
# AC-003-08 · Art. 10 (borde: 49, 50 y 51)
@pytest.mark.parametrize(
    ("count", "returned", "flag"),
    [(49, 49, False), (50, 50, False), (51, 0, True)],
    ids=["49_all", "50_all", "51_refine"],
)
async def test_ac_003_08_consultar_transacciones__result_cap__refines_above_50(
    count: int, returned: int, flag: bool
) -> None:
    """AC-003-08: con 51 no se devuelve ninguna y se pide acotar el rango."""
    txs = [_tx(f"T-{n:03d}", _sept(1 + n % 28, 8 + n // 28)) for n in range(count)]
    async with _harness(txs) as h:
        is_error, structured, _ = await h.consult()

        assert is_error is False
        assert len(structured["transactions"]) == returned
        assert structured["refinement_required"] is flag


# Regla: RN-003-06 — Validación de entrada: ... `date_to` no posterior a hoy ...
# Regla: RN-003-07 — "Hoy" es la fecha del reloj inyectado en la zona horaria `America/Bogota` (UTC−05:00), igual que RN-002-08.  # noqa: E501
# AC-003-10 · Art. 7 (filas exitosas; borde: medianoche de Bogotá)
@pytest.mark.parametrize(
    ("now", "date_to"),
    [
        (datetime(2026, 10, 17, 15, 0, tzinfo=UTC), "2026-10-17"),
        (datetime(2026, 10, 18, 5, 0, tzinfo=UTC), "2026-10-18"),
    ],
    ids=["today_in_bogota", "already_next_day_in_bogota"],
)
async def test_ac_003_10_consultar_transacciones__today_in_bogota__accepts_date_to(
    now: datetime, date_to: str
) -> None:
    """AC-003-10: `date_to` igual a hoy en Bogotá se acepta."""
    async with _harness(now=now) as h:
        is_error, structured, _ = await h.consult(date_from="2026-10-01", date_to=date_to)

        assert is_error is False
        assert structured == {"transactions": [], "refinement_required": False}


# Regla: RN-003-12 — Cada transacción devuelta contiene **solo**: `transaction_id`, `occurred_at`, `merchant`, `amount`, `currency`, `status`, `card_id` y `masked_card`.  # noqa: E501
# Regla: RN-003-13 — La respuesta nunca contiene el número completo de ninguna tarjeta, el documento del cliente ni su nombre, ni datos de otros clientes.  # noqa: E501
# AC-003-14 · Art. 7 (mínima exposición)
async def test_ac_003_14_consultar_transacciones__success__exposes_no_sensitive_data() -> None:
    """AC-003-14: solo los campos del contrato y ningún PAN, documento ni nombre."""
    async with _harness([_tx("T-1", _sept(10)), _tx("T-2", _sept(11))]) as h:
        is_error, structured, text = await h.consult()

        assert is_error is False
        assert set(structured) == {"transactions", "refinement_required"}
        assert set(json.loads(text)) == set(structured)
        for item in structured["transactions"]:
            assert set(item) == _RESPONSE_FIELDS
            assert item["masked_card"] == "**** 4321"
            assert _PAN not in item["card_id"]
        serialized = json.dumps(structured, ensure_ascii=False) + text
        for forbidden in (_PAN, "D-1001", "Laura Méndez"):
            assert forbidden not in serialized


# Regla: RN-003-11 — Las transacciones se ordenan de la más reciente a la más antigua por `occurred_at`; si dos tienen el mismo instante, por `transaction_id` ascendente (resultado determinista).  # noqa: E501
# AC-003-15 · Art. 7 (borde: instantes iguales)
async def test_ac_003_15_consultar_transacciones__same_instant__orders_by_transaction_id() -> None:
    """AC-003-15: la del 16 primero y luego las dos del 15 por `transaction_id`."""
    txs = [
        _tx("T-B", _sept(15)),
        _tx("T-A", _sept(15)),
        _tx("T-C", datetime(2026, 9, 16, 8, 0, tzinfo=_BOGOTA)),
    ]
    async with _harness(txs) as h:
        is_error, structured, _ = await h.consult()

        assert is_error is False
        assert _ids(structured) == ["T-C", "T-A", "T-B"]


# Regla: RN-003-09 — Se devuelven transacciones en cualquier estado: confirmada (`CONFIRMED`), pendiente (`PENDING`) o reversada (`REVERSED`). El monto es siempre el original y positivo; la reversión se ve solo en el estado.  # noqa: E501
# Regla: RN-003-12 — Cada transacción devuelta contiene **solo**: `transaction_id`, `occurred_at`, `merchant`, `amount` (texto decimal positivo con exactamente 2 decimales, p. ej. `"125000.00"`), `currency` (código ISO 4217, p. ej. `COP`, `USD`), `status`, `card_id` y `masked_card`.  # noqa: E501
# AC-003-16 · Art. 7
@pytest.mark.parametrize(
    ("registered", "currency", "expected"),
    [("125000", "COP", "125000.00"), ("49.9", "USD", "49.90"), ("0.05", "USD", "0.05")],
    ids=["cop_integer", "usd_one_decimal", "usd_cents"],
)
async def test_ac_003_16_consultar_transacciones__amount__two_decimals_and_currency(
    registered: str, currency: str, expected: str
) -> None:
    """AC-003-16: el monto sale con exactamente 2 decimales y la moneda registrada."""
    txs = [_tx("T-1", _sept(10), amount=registered, currency=currency)]
    async with _harness(txs) as h:
        is_error, structured, _ = await h.consult()

        assert is_error is False
        item = structured["transactions"][0]
        assert (item["amount"], item["currency"]) == (expected, currency)
