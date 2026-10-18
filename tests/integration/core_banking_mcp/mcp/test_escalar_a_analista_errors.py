"""Integración de `escalar_a_analista`: errores, identidad y auditoría (spec 006 §7)."""

import io
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.failing_escalation_repository import FailingEscalationRepository
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.ports.escalation_repository import EscalationRepository
from core_banking_mcp.application.use_cases.escalate_to_analyst import EscalateToAnalyst
from core_banking_mcp.application.use_cases.verify_identity import VerifyIdentity
from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.dispute import DisputeReason, DisputeStatus
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.infrastructure.inbound.mcp.escalation_tools import (
    register_escalation_tools,
)
from core_banking_mcp.infrastructure.inbound.mcp.identity_tools import register_identity_tools
from core_banking_mcp.infrastructure.outbound.audit.json_audit_log import JsonAuditLog
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    CardRow,
    DisputeRow,
    EscalationRow,
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

_PAN = "4111111111114321"
_PAN_PEDRO = "5500000000001234"
_BOGOTA = timezone(timedelta(hours=-5))
_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_CARD_L1 = "CARD-0001"  # CARD-L1 de la spec: de C-0001, terminada en 4321
_CARD_L2 = "CARD-0002"  # CARD-L2: de C-0001, terminada en 8765
_CARD_P1 = "CARD-0003"  # CARD-P1: de C-0002, terminada en 1234
_ABSENT = object()
_ERROR_FIELDS = {"code", "message", "retryable"}
_VALID: dict[str, Any] = {
    "conversation_id": "A",
    "reason": "FRAUD_SUSPECTED",
    "idempotency_key": "K-1",
}
# Las disputas de la spec (D-1, D-2, D-P1) se siembran en este orden: ids DSP-000001…
_DISPUTE_SEEDS = (("D-1", "TX-L1"), ("D-2", "TX-L2"), ("D-P1", "TX-P1"))


@dataclass
class _Harness:
    session: ClientSession
    db: Session
    store: InMemoryConversationVerificationStore
    stream: io.StringIO
    repo: EscalationRepository
    dispute_ids: dict[str, str] = field(default_factory=dict)

    async def call(self, **overrides: Any) -> tuple[bool, dict[str, Any], str]:
        """Invoca la herramienta; un override con valor `_ABSENT` omite el argumento."""
        args = {k: v for k, v in {**_VALID, **overrides}.items() if v is not _ABSENT}
        result = await self.session.call_tool("escalar_a_analista", args)
        text = "".join(getattr(block, "text", "") for block in result.content)
        return result.isError, result.structuredContent or {}, text

    async def verify(self, conversation_id: str, *, birth_date: str = "1985-03-14") -> None:
        result = await self.session.call_tool(
            "verificar_identidad",
            {
                "conversation_id": conversation_id,
                "customer_id": "C-0001",
                "birth_date": birth_date,
                "document_issue_date": "2005-04-02",
            },
        )
        assert result.structuredContent is not None

    def fill(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Sustituye los ids simbólicos de la spec (`D-1`, `CARD-L1`…) por los reales del core."""
        symbols = {**self.dispute_ids, "CARD-L1": _CARD_L1, "CARD-L2": _CARD_L2}
        symbols["CARD-P1"] = _CARD_P1
        return {
            key: [symbols.get(v, v) for v in value]
            if isinstance(value, list)
            else symbols.get(value, value)
            if isinstance(value, str)
            else value
            for key, value in entry.items()
        }

    def escalation_ids(self) -> list[str]:
        if isinstance(self.repo, FailingEscalationRepository):
            return [e.escalation_id for e in self.repo.escalations]
        self.db.expire_all()
        return list(self.db.scalars(select(EscalationRow.escalation_id)))

    def card_statuses(self) -> dict[str, str]:
        self.db.expire_all()
        rows = self.db.execute(select(CardRow.card_ref, CardRow.status))
        return {card_ref: status for card_ref, status in rows}

    def dispute_statuses(self) -> list[str]:
        self.db.expire_all()
        return list(self.db.scalars(select(DisputeRow.status).order_by(DisputeRow.dispute_id)))

    def set_card_status(self, card_ref: str, status: CardStatus) -> None:
        self.db.execute(
            update(CardRow).where(CardRow.card_ref == card_ref).values(status=status.value)
        )
        self.db.commit()

    def audit_lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]

    def clear_audit(self) -> None:
        self.stream.seek(0)
        self.stream.truncate(0)


@asynccontextmanager
async def _harness(
    *,
    verified: bool = True,
    failing: bool = False,
    disputes: tuple[str, ...] = (),
    card_l1_status: CardStatus = CardStatus.ACTIVE,
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
        .with_cards(Card("4321", card_l1_status), Card("8765", CardStatus.ACTIVE))
        .build(),
        pans,
        identity=IdentityBuilder().build(),
    )
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
    transactions = SqlAlchemyTransactionRepository(db)
    tx_date = datetime(2026, 10, 10, 12, 0, tzinfo=_BOGOTA)
    for card_ref, last4, tx_id in (
        (_CARD_L1, "4321", "TX-L1"),
        (_CARD_L1, "4321", "TX-L2"),
        (_CARD_P1, "1234", "TX-P1"),
    ):
        transactions.add(
            card_ref,
            TransactionBuilder(merchant="Tienda Aurora")
            .with_id(tx_id)
            .with_card(card_ref, last4)
            .with_occurred_at(tx_date)
            .with_amount(Decimal("85000.00"))
            .build(),
        )
    dispute_repo = SqlAlchemyDisputeRepository(db)
    dispute_ids: dict[str, str] = {}
    for name, tx_id in _DISPUTE_SEEDS:
        if name in disputes:
            dispute = dispute_repo.add(
                "seed", name, tx_id, DisputeReason.UNRECOGNIZED_CHARGE, DisputeStatus.OPEN, _NOW
            )
            dispute_ids[name] = dispute.dispute_id
    repo: EscalationRepository = (
        FailingEscalationRepository() if failing else SqlAlchemyEscalationRepository(db)
    )
    store = InMemoryConversationVerificationStore()
    if verified:
        store.save("A", VerificationState().with_verified("C-0001"))
    stream = io.StringIO()
    audit = JsonAuditLog(stream=stream)
    clock = FixedClock(_NOW)
    mcp = FastMCP("core-banking-test")
    register_escalation_tools(
        mcp,
        EscalateToAnalyst(
            transactions,
            SqlAlchemyCardRepository(db),
            dispute_repo,
            repo,
            store,
            audit,
            clock,
        ),
    )
    register_identity_tools(mcp, VerifyIdentity(customers, store, audit, clock))
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        yield _Harness(client, db, store, stream, repo, dispute_ids)


def _assert_error(structured: dict[str, Any], code: str) -> None:
    assert set(structured) == _ERROR_FIELDS
    assert structured["code"] == code
    assert structured["retryable"] is False


_LEAKS_PEDRO = ("Pedro", "D-1002", _PAN_PEDRO, "1234", "C-0002", _CARD_P1, "TX-P1")


# Regla: RN-006-03 — La derivación **no** exige identidad verificada. Si la solicitud no trae datos del cliente, se registra en cualquier conversación: verificada, sin verificar, bloqueada por agotar sus intentos o desconocida para el servidor. Si trae algún dato del cliente (`transaction_id`, `card_id` o `dispute_id`), la conversación debe estar verificada en el servidor (estado de RN-002-13); si no, se rechaza con `IDENTITY_NOT_VERIFIED`. La verificación no se traslada: estar verificada en otra conversación no cuenta.  # noqa: E501
# AC-006-05 · Art. 7 (las 6 filas de la tabla)
@pytest.mark.parametrize(
    ("situation", "datum"),
    [
        ("never_verified", {"transaction_id": "TX-L1"}),
        ("never_verified", {"card_id": "CARD-L1"}),
        ("one_failed_attempt", {"transaction_id": "TX-L1"}),
        ("locked", {"transaction_id": "TX-L1"}),
        ("verified_in_a_not_in_b", {"card_id": "CARD-L1"}),
        (
            "never_verified",
            {
                "prior_actions": ["DISPUTE_OPENED"],
                "transaction_id": "TX-L1",
                "dispute_id": "D-1",
            },
        ),
    ],
    ids=[
        "never-verified-transaction",
        "never-verified-card",
        "one-failed-attempt",
        "locked",
        "verified-in-other-conversation",
        "never-verified-dispute-opened",
    ],
)
async def test_ac_006_05_escalar_a_analista__customer_data_without_verification__returns_identity_not_verified(  # noqa: E501
    situation: str, datum: dict[str, Any]
) -> None:
    """AC-006-05: datos del cliente en una conversación B sin verificar se rechazan."""
    async with _harness(verified=situation == "verified_in_a_not_in_b") as h:
        match situation:
            case "one_failed_attempt":
                await h.verify("B", birth_date="1990-01-01")
                assert h.store.get("B").failed_attempts == 1
            case "locked":
                for _ in range(3):
                    await h.verify("B", birth_date="1990-01-01")
                assert h.store.get("B").is_locked
        before = {key: h.store.get(key) for key in ("A", "B")}
        if situation == "verified_in_a_not_in_b":
            assert before["A"].verified_customer_id == "C-0001"
            assert before["B"].verified_customer_id is None

        is_error, structured, _ = await h.call(conversation_id="B", **h.fill(datum))

        assert is_error is True
        _assert_error(structured, "IDENTITY_NOT_VERIFIED")
        assert h.escalation_ids() == []
        assert {key: h.store.get(key) for key in before} == before


# Regla: RN-006-02 — El motivo es un código de un catálogo cerrado que distingue mayúsculas: `FRAUD_SUSPECTED` (sospecha de fraude), `AMOUNT_OVER_THRESHOLD` (monto sobre el umbral), `INSUFFICIENT_OR_CONTRADICTORY_INFO` (información insuficiente o contradictoria), `INCONCLUSIVE_RULES` (reglas no concluyentes), `UNRECOVERABLE_SYSTEM_FAILURE` (falla no recuperable del sistema), `IDENTITY_VERIFICATION_FAILED` (verificación de identidad fallida o agotada) y `OTHER` (otro). Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`.  # noqa: E501
# Regla: RN-006-10 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-006-02; `transaction_id`, `card_id` y `dispute_id` opcionales (ausentes o `null`) y, si se envían, de 1 a 64 caracteres tras recortar (vacío o solo espacios ⇒ `INVALID_INPUT`); `prior_actions` y `note` según RN-006-05 y RN-006-07. Toda violación ⇒ `INVALID_INPUT`, sin derivación registrada.  # noqa: E501
# AC-006-03 · Art. 10 (las 5 filas de la tabla; ausente y null por separado)
@pytest.mark.parametrize(
    "reason",
    ["FRAUD", "fraud_suspected", "sospecha de fraude", "", _ABSENT, None],
    ids=["not_in_catalog", "lowercase", "free_text", "empty", "absent", "null"],
)
async def test_ac_006_03_escalar_a_analista__invalid_reason__returns_invalid_input(
    reason: Any,
) -> None:
    """AC-006-03: un motivo fuera del catálogo devuelve INVALID_INPUT sin derivación."""
    async with _harness() as h:
        is_error, structured, _ = await h.call(reason=reason)

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert h.escalation_ids() == []


# Regla: RN-006-05 — `prior_actions` es una lista de códigos de un catálogo cerrado que distingue mayúsculas: `DISPUTE_OPENED` (se abrió una disputa) y `CARD_BLOCKED` (se bloqueó la tarjeta). Ausente, `null` o vacía significa que no se realizó ninguna acción. Coherencia: `DISPUTE_OPENED` exige `dispute_id` y `transaction_id`; `dispute_id` sin `DISPUTE_OPENED` no se admite; `CARD_BLOCKED` exige `card_id`. Un código fuera del catálogo, un código repetido o una incoherencia ⇒ `INVALID_INPUT`.  # noqa: E501
# Regla: RN-006-10 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-006-02; `transaction_id`, `card_id` y `dispute_id` opcionales (ausentes o `null`) y, si se envían, de 1 a 64 caracteres tras recortar (vacío o solo espacios ⇒ `INVALID_INPUT`); `prior_actions` y `note` según RN-006-05 y RN-006-07. Toda violación ⇒ `INVALID_INPUT`, sin derivación registrada.  # noqa: E501
# AC-006-07 · Art. 10 (las 7 filas de la tabla)
@pytest.mark.parametrize(
    "entry",
    [
        {"prior_actions": ["DISPUTE_OPENED"], "transaction_id": "TX-L1"},
        {"prior_actions": ["DISPUTE_OPENED"], "dispute_id": "D-1"},
        {"dispute_id": "D-1", "transaction_id": "TX-L1"},
        {"prior_actions": ["CARD_BLOCKED"]},
        {"prior_actions": ["CARD_BLOCKED", "CARD_BLOCKED"], "card_id": "CARD-L1"},
        {"prior_actions": ["CARD_CANCELLED"]},
        {"prior_actions": ["card_blocked"], "card_id": "CARD-L1"},
    ],
    ids=[
        "dispute-opened-without-dispute-id",
        "dispute-opened-without-transaction",
        "dispute-id-without-dispute-opened",
        "card-blocked-without-card",
        "repeated-code",
        "not-in-catalog",
        "lowercase",
    ],
)
async def test_ac_006_07_escalar_a_analista__incoherent_prior_actions__returns_invalid_input(
    entry: dict[str, Any],
) -> None:
    """AC-006-07: acciones previas incoherentes devuelven INVALID_INPUT sin derivación."""
    async with _harness(disputes=("D-1",), card_l1_status=CardStatus.BLOCKED) as h:
        is_error, structured, _ = await h.call(**h.fill(entry))

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert h.escalation_ids() == []


# Regla: RN-006-04 — Los datos del cliente indicados deben pertenecer al cliente verificado en la conversación, sea cual sea el estado de la transacción o de la tarjeta (salvo RN-006-06): la transacción a una tarjeta suya, la tarjeta a él y, si se indican ambas, la transacción a **esa** tarjeta. Si algún dato no cumple, porque es de otro cliente, de otra tarjeta o porque no existe, se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en todos los casos y sin datos de ningún cliente.  # noqa: E501
# Regla: RN-006-06 — Las acciones previas se contrastan con el core: con `DISPUTE_OPENED`, la disputa `dispute_id` debe existir y ser de la transacción `transaction_id` (en cualquier estado de la disputa); con `CARD_BLOCKED`, la tarjeta `card_id` debe estar en estado `BLOCKED`. Si no se cumple ⇒ `NOT_FOUND` con el mensaje fijo de RN-006-04.  # noqa: E501
# AC-006-08 · Art. 7 (las 4 filas de la tabla)
@pytest.mark.parametrize(
    "entry",
    [
        {"transaction_id": "TX-L1", "prior_actions": ["DISPUTE_OPENED"], "dispute_id": "D-2"},
        {"transaction_id": "TX-L1", "prior_actions": ["DISPUTE_OPENED"], "dispute_id": "D-P1"},
        {"transaction_id": "TX-L1", "prior_actions": ["DISPUTE_OPENED"], "dispute_id": "D-9999"},
        {"card_id": "CARD-L1", "prior_actions": ["CARD_BLOCKED"]},
    ],
    ids=["dispute-of-other-transaction", "dispute-of-other-customer", "unknown-dispute", "active"],
)
async def test_ac_006_08_escalar_a_analista__prior_actions_not_in_core__returns_same_not_found(
    entry: dict[str, Any],
) -> None:
    """AC-006-08: acciones previas que el core no refleja devuelven el NOT_FOUND de AC-006-12."""
    async with _harness(disputes=("D-2", "D-P1")) as h:
        reference = await h.call(transaction_id="TX-9999", idempotency_key="K-REF")
        assert reference[0] is True

        is_error, structured, text = await h.call(**h.fill(entry))

        assert is_error is True
        _assert_error(structured, "NOT_FOUND")
        assert structured == reference[1]
        assert h.escalation_ids() == []
        for leaked in (*_LEAKS_PEDRO, h.dispute_ids["D-P1"]):
            assert leaked not in text


# Regla: RN-006-07 — `note` es opcional. Se recorta; vacía o solo espacios equivale a sin nota (`null`). Tras recortar admite de 1 a 300 caracteres; más ⇒ `INVALID_INPUT`. Toda secuencia de 13 a 19 dígitos seguidos que contenga se guarda, se devuelve y se audita sustituida por `[REDACTED]`. La nota es información para el analista y nunca se interpreta como instrucción (RN-006-14).  # noqa: E501
# Regla: RN-006-10 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-006-02; `transaction_id`, `card_id` y `dispute_id` opcionales (ausentes o `null`) y, si se envían, de 1 a 64 caracteres tras recortar (vacío o solo espacios ⇒ `INVALID_INPUT`); `prior_actions` y `note` según RN-006-05 y RN-006-07. Toda violación ⇒ `INVALID_INPUT`, sin derivación registrada.  # noqa: E501
# AC-006-09 · Art. 10 (fila de 301 caracteres; borde superior)
async def test_ac_006_09_escalar_a_analista__note_over_300_chars__returns_invalid_input() -> None:
    """AC-006-09: una nota de 301 caracteres devuelve INVALID_INPUT sin derivación."""
    async with _harness() as h:
        is_error, structured, text = await h.call(reason="OTHER", note="n" * 301)

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert "n" * 301 not in text
        assert h.escalation_ids() == []


# Regla: RN-006-04 — Los datos del cliente indicados deben pertenecer al cliente verificado en la conversación, sea cual sea el estado de la transacción o de la tarjeta (salvo RN-006-06): la transacción a una tarjeta suya, la tarjeta a él y, si se indican ambas, la transacción a **esa** tarjeta. Si algún dato no cumple, porque es de otro cliente, de otra tarjeta o porque no existe, se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en todos los casos y sin datos de ningún cliente.  # noqa: E501
# Regla: RN-006-13 — La respuesta nunca contiene el número completo de ninguna tarjeta, el documento del cliente ni su nombre, ni datos de otros clientes.  # noqa: E501
# AC-006-12 · Art. 7 (las 5 filas de la tabla; tarjeta/transacción ajena frente a inexistente)
async def test_ac_006_12_escalar_a_analista__foreign_or_unknown_data__same_not_found() -> None:
    """AC-006-12: datos ajenos, inexistentes o cruzados devuelven el mismo NOT_FOUND."""
    entries = [
        {"transaction_id": "TX-P1"},
        {"transaction_id": "TX-9999"},
        {"card_id": _CARD_P1},
        {"card_id": "CARD-9999"},
        {"transaction_id": "TX-L1", "card_id": _CARD_L2},
    ]
    async with _harness() as h:
        results = [
            await h.call(idempotency_key=f"K-{index}", **entry)
            for index, entry in enumerate(entries, start=1)
        ]

        for is_error, structured, text in results:
            assert is_error is True
            _assert_error(structured, "NOT_FOUND")
            for leaked in _LEAKS_PEDRO:
                assert leaked not in text
        assert all(structured == results[0][1] for _, structured, _ in results)
        assert h.escalation_ids() == []


# Regla: RN-006-09 — La clave de reintento es única **dentro de cada conversación** y solo se registra cuando se crea una derivación nueva. Si la conversación ya usó la clave con **exactamente los mismos** datos (`reason`, `transaction_id`, `card_id`, `prior_actions`, `dispute_id` y `note`, comparados tras recortar y normalizar según RN-006-07 y RN-006-10, con `prior_actions` comparada como conjunto), se devuelve la derivación que creó esa solicitud (mismo `escalation_id`, `escalated_at` y resumen) sin registrar otra. Si alguno de esos datos difiere, se rechaza con `INVALID_INPUT` y no se registra nada. La misma clave en otra conversación es una solicitud independiente.  # noqa: E501
# AC-006-14 · Art. 10 (las 5 filas de la tabla)
@pytest.mark.parametrize(
    "overrides",
    [
        {"reason": "OTHER"},
        {"transaction_id": "TX-L2"},
        {"card_id": "CARD-L1"},
        {"note": "revisar urgente"},
        {"note": _ABSENT},
    ],
    ids=["other-reason", "other-transaction", "added-card", "other-note", "omitted-note"],
)
async def test_ac_006_14_escalar_a_analista__key_reused_with_other_data__returns_invalid_input(
    overrides: dict[str, Any],
) -> None:
    """AC-006-14: reutilizar K-1 con otro contenido devuelve INVALID_INPUT sin derivación extra."""
    first_entry = {"transaction_id": "TX-L1", "note": "revisar"}
    async with _harness() as h:
        first = await h.call(**first_entry)
        assert first[0] is False
        before = h.escalation_ids()
        assert len(before) == 1

        is_error, structured, _ = await h.call(
            idempotency_key="K-1", **{**first_entry, **h.fill(overrides)}
        )

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert h.escalation_ids() == before


# Regla: RN-006-10 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-006-02; `transaction_id`, `card_id` y `dispute_id` opcionales (ausentes o `null`) y, si se envían, de 1 a 64 caracteres tras recortar (vacío o solo espacios ⇒ `INVALID_INPUT`); `prior_actions` y `note` según RN-006-05 y RN-006-07. Toda violación ⇒ `INVALID_INPUT`, sin derivación registrada.  # noqa: E501
# AC-006-16 · Art. 10 (las 9 filas de la tabla; ausente, null, vacío y solo espacios por separado)
@pytest.mark.parametrize(
    "overrides",
    [
        {"idempotency_key": _ABSENT},
        {"idempotency_key": None},
        {"idempotency_key": ""},
        {"idempotency_key": "   "},
        {"idempotency_key": "k" * 65},
        {"conversation_id": _ABSENT},
        {"conversation_id": ""},
        {"conversation_id": "   "},
        {"transaction_id": ""},
        {"transaction_id": "   "},
        {"transaction_id": "T" * 65},
        {"card_id": ""},
        {"card_id": "   "},
        {"card_id": "C" * 65},
        {"dispute_id": "", "prior_actions": ["DISPUTE_OPENED"], "transaction_id": "TX-L1"},
        {"dispute_id": "   ", "prior_actions": ["DISPUTE_OPENED"], "transaction_id": "TX-L1"},
    ],
    ids=[
        "key_absent",
        "key_null",
        "key_empty",
        "key_blank",
        "key_65_chars",
        "conversation_absent",
        "conversation_empty",
        "conversation_blank",
        "transaction_empty",
        "transaction_blank",
        "transaction_65_chars",
        "card_empty",
        "card_blank",
        "card_65_chars",
        "dispute_empty",
        "dispute_blank",
    ],
)
async def test_ac_006_16_escalar_a_analista__invalid_fields__returns_invalid_input(
    overrides: dict[str, Any],
) -> None:
    """AC-006-16: cada dato inválido devuelve INVALID_INPUT, retryable=false y sin derivación."""
    async with _harness() as h:
        is_error, structured, _ = await h.call(**overrides)

        assert is_error is True
        _assert_error(structured, "INVALID_INPUT")
        assert h.escalation_ids() == []


# Regla: RN-006-11 — Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada y coherencia → `INVALID_INPUT`; (2) si hay datos del cliente, identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) clave de reintento ya usada en la conversación → la derivación existente (misma solicitud) o `INVALID_INPUT` (solicitud distinta); (4) pertenencia de los datos al cliente verificado → `NOT_FOUND`; (5) acciones previas contra el core → `NOT_FOUND`; (6) registro de la derivación.  # noqa: E501
# AC-006-17 · Art. 7 (las 6 filas de la tabla)
@pytest.mark.parametrize(
    "row",
    [
        "unverified_invalid_reason",
        "unverified_incoherent_prior_actions",
        "unverified_unknown_transaction",
        "key_reused_unknown_transaction",
        "key_replay_after_card_unblocked",
        "foreign_blocked_card",
    ],
)
async def test_ac_006_17_escalar_a_analista__multiple_failures__returns_first_check_result(
    row: str,
) -> None:
    """AC-006-17: se devuelve el primer resultado en el orden de comprobaciones de RN-006-11."""
    kwargs: dict[str, Any] = {}
    conversation = "B"
    entry: dict[str, Any]
    match row:
        case "unverified_invalid_reason":
            expected, entry = "INVALID_INPUT", {"reason": "FRAUD", "transaction_id": "TX-L1"}
        case "unverified_incoherent_prior_actions":
            expected, entry = "INVALID_INPUT", {"prior_actions": ["CARD_BLOCKED"]}
        case "unverified_unknown_transaction":
            expected, entry = "IDENTITY_NOT_VERIFIED", {"transaction_id": "TX-9999"}
        case "key_reused_unknown_transaction":
            expected, conversation = "INVALID_INPUT", "A"
            entry = {"transaction_id": "TX-9999", "idempotency_key": "K-1"}
        case "key_replay_after_card_unblocked":
            expected, conversation = "replayed", "A"
            entry = {
                "card_id": _CARD_L1,
                "prior_actions": ["CARD_BLOCKED"],
                "idempotency_key": "K-1",
            }
            kwargs = {"card_l1_status": CardStatus.BLOCKED}
        case _:
            expected, conversation = "NOT_FOUND", "A"
            entry = {"card_id": _CARD_P1, "prior_actions": ["CARD_BLOCKED"]}
            kwargs = {"pedro_status": CardStatus.BLOCKED}
    async with _harness(**kwargs) as h:
        first: tuple[bool, dict[str, Any], str] | None = None
        if row == "key_reused_unknown_transaction":
            first = await h.call(transaction_id="TX-L1")
            assert first[0] is False
        if row == "key_replay_after_card_unblocked":
            first = await h.call(**entry)
            assert first[0] is False
            h.set_card_status(_CARD_L1, CardStatus.ACTIVE)
            assert h.card_statuses()[_CARD_L1] == "ACTIVE"

        is_error, structured, _ = await h.call(conversation_id=conversation, **entry)

        if expected == "replayed":
            assert first is not None
            assert is_error is False
            assert structured == first[1]
            assert h.escalation_ids() == [first[1]["escalation_id"]]
        else:
            assert is_error is True
            _assert_error(structured, expected)
            assert len(h.escalation_ids()) == (1 if first is not None else 0)


# Regla: RN-006-15 — Ante una falla inesperada (p. ej. el repositorio de derivaciones no responde al registrar), la herramienta devuelve `INTERNAL` con `retryable = false` y sin detalles internos (trazas, SQL, texto de la excepción). La operación es atómica: no queda ninguna derivación ni clave de reintento registrada.  # noqa: E501
# AC-006-19 · Art. 10 (retryable=false implica escalar)
async def test_ac_006_19_escalar_a_analista__repository_fails__returns_internal() -> None:
    """AC-006-19: una falla al registrar da INTERNAL y la clave K-1 queda libre."""
    async with _harness(failing=True) as h:
        is_error, structured, text = await h.call(reason="UNRECOVERABLE_SYSTEM_FAILURE")

        assert is_error is True
        _assert_error(structured, "INTERNAL")
        for leaked in ("detalle interno secreto", "RuntimeError", "Traceback", "SELECT"):
            assert leaked not in structured["message"]
            assert leaked not in text
        assert h.escalation_ids() == []

        assert isinstance(h.repo, FailingEscalationRepository)
        h.repo.repair()
        retry_error, retry, _ = await h.call(reason="UNRECOVERABLE_SYSTEM_FAILURE")

        assert retry_error is False
        assert retry["status"] == "PENDING"
        assert h.escalation_ids() == [retry["escalation_id"]]


# Regla: RN-006-16 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "escalar_a_analista"`; el `reason`, la `idempotency_key`, el `transaction_id`, el `card_id`, el `dispute_id`, las `prior_actions` y la `note` recibidos (cada uno vacío si no llegó o no es válido según RN-006-10, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); `identity_verified` (si la conversación estaba verificada); y el resultado. El resultado es `escalated` con el `escalation_id` creado, `replayed` con el `escalation_id` existente, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INTERNAL`). Como `idempotency_key`, `transaction_id`, `card_id`, `dispute_id` y `note` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente.  # noqa: E501
# AC-006-20 · Art. 8 (trazabilidad total; los 9 casos de la tabla)
@pytest.mark.parametrize(
    "case",
    [
        "escalated",
        "replayed",
        "unverified_escalated",
        "not_found",
        "invalid",
        "unverified_customer_data",
        "pan_in_card_id",
        "pan_in_note",
        "internal",
    ],
)
async def test_ac_006_20_escalar_a_analista__any_case__audits_one_line_without_personal_data(
    case: str,
) -> None:
    """AC-006-20: una sola línea JSON con herramienta, datos recibidos y resultado, sin PAN."""
    conversation = "A"
    overrides: dict[str, Any] = {}
    kwargs: dict[str, Any] = {}
    expected: dict[str, Any] = {
        "escalation_reason": "FRAUD_SUSPECTED",
        "idempotency_key": "K-1",
        "identity_verified": True,
    }
    match case:
        case "escalated" | "replayed":
            overrides = {"card_id": _CARD_L1}
            expected |= {"card_id": _CARD_L1, "masked_card": "**** 4321", "outcome": case}
        case "unverified_escalated":
            conversation = "B"
            expected |= {"identity_verified": False, "outcome": "escalated"}
        case "not_found":
            overrides = {"transaction_id": "TX-P1"}
            expected |= {"transaction_id": "TX-P1", "error_code": "NOT_FOUND"}
        case "invalid":
            overrides = {"reason": "FRAUD"}
            expected |= {
                "escalation_reason": None,
                "identity_verified": None,
                "error_code": "INVALID_INPUT",
            }
        case "unverified_customer_data":
            conversation = "B"
            overrides = {"card_id": _CARD_L1}
            expected |= {
                "card_id": _CARD_L1,
                "identity_verified": False,
                "error_code": "IDENTITY_NOT_VERIFIED",
            }
        case "pan_in_card_id":
            overrides = {"card_id": _PAN}
            expected |= {"card_id": "[REDACTED]", "error_code": "NOT_FOUND"}
        case "pan_in_note":
            overrides = {"note": f"tarjeta {_PAN}"}
            expected |= {"note": "tarjeta [REDACTED]", "outcome": "escalated"}
        case "internal":
            kwargs = {"failing": True}
            expected |= {"error_code": "INTERNAL"}
    async with _harness(**kwargs) as h:
        if case == "replayed":
            first = await h.call(**overrides)
            assert first[0] is False
            h.clear_audit()

        is_error, structured, _ = await h.call(conversation_id=conversation, **overrides)

        lines = h.audit_lines()
        assert len(lines) == 1
        line = lines[0]
        assert line["tool"] == "escalar_a_analista"
        assert line["conversation_id"] == conversation
        assert line["timestamp"] == _NOW.isoformat()
        for key in (
            "escalation_reason",
            "idempotency_key",
            "transaction_id",
            "card_id",
            "dispute_id",
            "note",
            "masked_card",
            "identity_verified",
        ):
            assert line.get(key) == expected.get(key), key
        assert line.get("prior_actions") in (None, [])
        if "error_code" in expected:
            assert line["error_code"] == expected["error_code"]
            assert is_error is True
        else:
            assert line["outcome"] == expected["outcome"]
            assert line["escalation_id"] == structured["escalation_id"]
        raw = h.stream.getvalue()
        assert _PAN not in raw
        assert "D-1001" not in raw
