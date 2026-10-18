"""Integración del repositorio de derivaciones sobre SQLite en memoria (AC-006-04, 06, 10, 13, 15, 19)."""

# ruff: noqa: E501  (los enunciados de RN de la trazabilidad se citan en una sola línea)

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.dispute import DisputeReason, DisputeStatus
from core_banking_mcp.domain.models.escalation import (
    Escalation,
    EscalationReason,
    EscalationStatus,
    PriorAction,
)
from core_banking_mcp.infrastructure.outbound.persistence.database import (
    create_engine_from_url,
    create_schema,
    session_factory,
)
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import EscalationRow
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

_BOGOTA = timezone(timedelta(hours=-5))
_AT = datetime(2026, 10, 17, 5, 0, tzinfo=_BOGOTA)
_CUSTOMER = "C-0001"
_CARD_4321 = "CARD-0002"
_BOTH = frozenset({PriorAction.CARD_BLOCKED, PriorAction.DISPUTE_OPENED})


@pytest.fixture
def session() -> Session:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    session = session_factory(engine)()
    customer = (
        CustomerBuilder()
        .with_id(_CUSTOMER)
        .with_cards(Card("1234", CardStatus.ACTIVE), Card("4321", CardStatus.BLOCKED))
        .build()
    )
    SqlAlchemyCustomerRepository(session).add(customer, identity=IdentityBuilder().build())
    SqlAlchemyTransactionRepository(session).add(
        _CARD_4321,
        TransactionBuilder().with_id("TX-L1").with_card(_CARD_4321, "4321").build(),
    )
    SqlAlchemyDisputeRepository(session).add(
        "A", "D-K", "TX-L1", DisputeReason.UNRECOGNIZED_CHARGE, DisputeStatus.OPEN, _AT
    )
    return session


@pytest.fixture
def repo(session: Session) -> SqlAlchemyEscalationRepository:
    return SqlAlchemyEscalationRepository(session)


def _full(
    repo: SqlAlchemyEscalationRepository,
    conversation: str = "A",
    key: str = "K-1",
    note: str | None = "revisar",
) -> Escalation:
    return repo.add(
        conversation,
        key,
        EscalationReason.FRAUD_SUSPECTED,
        _AT,
        True,
        _CUSTOMER,
        "TX-L1",
        _CARD_4321,
        _BOTH,
        "DSP-000001",
        note,
    )


def _limited(
    repo: SqlAlchemyEscalationRepository, conversation: str = "B", key: str = "K-1"
) -> Escalation:
    return repo.add(
        conversation,
        key,
        EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE,
        _AT,
        False,
        None,
        None,
        None,
        frozenset(),
        None,
        None,
    )


def _row(session: Session, escalation_id: str) -> EscalationRow:
    row = session.scalar(select(EscalationRow).where(EscalationRow.escalation_id == escalation_id))
    assert row is not None
    return row


def _count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(EscalationRow)) or 0


# Regla: RN-006-09 — La clave de reintento es única **dentro de cada conversación** y solo se registra cuando se crea una derivación nueva. Si la conversación ya usó la clave con **exactamente los mismos** datos (`reason`, `transaction_id`, `card_id`, `prior_actions`, `dispute_id` y `note`, comparados tras recortar y normalizar según RN-006-07 y RN-006-10, con `prior_actions` comparada como conjunto), se devuelve la derivación que creó esa solicitud (mismo `escalation_id`, `escalated_at` y resumen) sin registrar otra. Si alguno de esos datos difiere, se rechaza con `INVALID_INPUT` y no se registra nada. La misma clave en otra conversación es una solicitud independiente.
# AC-006-13 · Art. 10 (ante la duda, escalar)
def test_ac_006_13_escalation_repository__find_by_key__returns_only_same_conversation(
    repo: SqlAlchemyEscalationRepository,
) -> None:
    """AC-006-13: la búsqueda por clave se limita a la conversación; la pareja es única."""
    created = _full(repo)

    assert created.escalation_id == "ESC-000001"
    found = repo.find_by_key("A", "K-1")
    assert found == created
    assert found is not None
    assert found.customer_id == _CUSTOMER
    assert found.transaction_id == "TX-L1"
    assert found.card_id == _CARD_4321
    assert found.dispute_id == "DSP-000001"
    assert found.note == "revisar"
    assert found.status is EscalationStatus.PENDING
    assert found.prior_actions == _BOTH
    assert found.escalated_at == datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
    assert found.escalated_at.tzinfo is UTC
    assert repo.find_by_key("B", "K-1") is None

    with pytest.raises(Exception):  # noqa: B017, PT011 - IntegrityError de SQLAlchemy
        _full(repo, conversation="A", key="K-1")


# Regla: RN-006-08 — Una derivación nueva queda con un `escalation_id` opaco y único, no derivado del número de ninguna tarjeta; `status = PENDING`, que esta feature nunca cambia; `escalated_at` igual al instante del reloj inyectado en ISO 8601 con la zona de Bogotá (`−05:00`); el `reason` recibido; y un resumen. El resumen es **completo** si la conversación está verificada (`identity_verified = true`, `customer_id` del cliente verificado y los datos indicados) y **limitado** si no lo está (`identity_verified = false`, `customer_id`, `transaction`, `card` y `dispute_id` en `null` y `prior_actions` vacía). En ambos casos trae `conversation_id` y la nota, si la hay.
# AC-006-04 · Art. 7 (identidad verificada)
def test_ac_006_04_escalation_repository__limited_summary__stores_null_data(
    session: Session, repo: SqlAlchemyEscalationRepository
) -> None:
    """AC-006-04: una derivación limitada guarda identity_verified=0 y datos nulos."""
    created = _limited(repo)

    row = _row(session, created.escalation_id)
    assert row.identity_verified is False
    assert row.customer_id is None
    assert row.transaction_id is None
    assert row.card_id is None
    assert row.dispute_id is None
    assert row.note is None
    assert row.prior_actions == ""
    found = repo.find_by_key("B", "K-1")
    assert found == created
    assert found is not None
    assert found.identity_verified is False
    assert found.prior_actions == frozenset()
    assert found.status is EscalationStatus.PENDING


# Regla: RN-006-05 — `prior_actions` es una lista de códigos de un catálogo cerrado que distingue mayúsculas: `DISPUTE_OPENED` (se abrió una disputa) y `CARD_BLOCKED` (se bloqueó la tarjeta). Ausente, `null` o vacía significa que no se realizó ninguna acción. Coherencia: `DISPUTE_OPENED` exige `dispute_id` y `transaction_id`; `dispute_id` sin `DISPUTE_OPENED` no se admite; `CARD_BLOCKED` exige `card_id`. Un código fuera del catálogo, un código repetido o una incoherencia ⇒ `INVALID_INPUT`.
# AC-006-06 · Art. 3 (trazabilidad)
def test_ac_006_06_escalation_repository__prior_actions__stored_in_canonical_text(
    session: Session, repo: SqlAlchemyEscalationRepository
) -> None:
    """AC-006-06: prior_actions se guarda en orden de catálogo y vuelve como conjunto."""
    both = _full(repo, key="K-1")
    none = _limited(repo, key="K-2")

    assert _row(session, both.escalation_id).prior_actions == "DISPUTE_OPENED,CARD_BLOCKED"
    assert _row(session, none.escalation_id).prior_actions == ""
    found = repo.find_by_key("A", "K-1")
    assert found is not None
    assert found.prior_actions == _BOTH
    assert found.ordered_prior_actions() == (PriorAction.DISPUTE_OPENED, PriorAction.CARD_BLOCKED)


# Regla: RN-006-07 — `note` es opcional. Se recorta; vacía o solo espacios equivale a sin nota (`null`). Tras recortar admite de 1 a 300 caracteres; más ⇒ `INVALID_INPUT`. Toda secuencia de 13 a 19 dígitos seguidos que contenga se guarda, se devuelve y se audita sustituida por `[REDACTED]`. La nota es información para el analista y nunca se interpreta como instrucción (RN-006-14).
# AC-006-10 · Art. 7 (no exponer datos de tarjeta)
def test_ac_006_10_escalation_repository__note__stored_as_received(
    session: Session, repo: SqlAlchemyEscalationRepository
) -> None:
    """AC-006-10: la nota (ya redactada) se guarda tal cual, sin el número completo."""
    note = "Cliente dicta la tarjeta [REDACTED] y pide ayuda"
    created = _full(repo, note=note)

    stored = _row(session, created.escalation_id).note
    assert stored == note
    assert "4111111111114321" not in (stored or "")
    found = repo.find_by_key("A", "K-1")
    assert found is not None
    assert found.note == note


# Regla: RN-006-09 — La clave de reintento es única **dentro de cada conversación** y solo se registra cuando se crea una derivación nueva. Si la conversación ya usó la clave con **exactamente los mismos** datos (`reason`, `transaction_id`, `card_id`, `prior_actions`, `dispute_id` y `note`, comparados tras recortar y normalizar según RN-006-07 y RN-006-10, con `prior_actions` comparada como conjunto), se devuelve la derivación que creó esa solicitud (mismo `escalation_id`, `escalated_at` y resumen) sin registrar otra. Si alguno de esos datos difiere, se rechaza con `INVALID_INPUT` y no se registra nada. La misma clave en otra conversación es una solicitud independiente.
# AC-006-15 · Art. 10 (ante la duda, escalar)
def test_ac_006_15_escalation_repository__same_conversation_distinct_keys__two_escalations(
    repo: SqlAlchemyEscalationRepository,
) -> None:
    """AC-006-15: dos claves distintas en la misma conversación dan ESC-000001 y ESC-000002."""
    first = _full(repo, key="K-1")
    second = _full(repo, key="K-2")

    assert (first.escalation_id, second.escalation_id) == ("ESC-000001", "ESC-000002")
    assert repo.find_by_key("A", "K-1") == first


# Regla: RN-006-15 — Ante una falla inesperada (p. ej. el repositorio de derivaciones no responde al registrar), la herramienta devuelve `INTERNAL` con `retryable = false` y sin detalles internos (trazas, SQL, texto de la excepción). La operación es atómica: no queda ninguna derivación ni clave de reintento registrada.
# AC-006-19 · Art. 10 (ante la duda, escalar)
def test_ac_006_19_escalation_repository__failed_add__rolls_back_and_session_stays_usable(
    session: Session, repo: SqlAlchemyEscalationRepository
) -> None:
    """AC-006-19: tras un add fallido, rollback: sin fila y sesión usable."""
    _full(repo, key="K-1")

    with pytest.raises(Exception):  # noqa: B017, PT011 - IntegrityError de SQLAlchemy
        _full(repo, key="K-1")

    assert _count(session) == 1
    assert session.execute(text("select 1")).scalar() == 1
    assert repo.find_by_key("A", "K-1") is not None
    valid = _full(repo, key="K-2")
    assert repo.find_by_key("A", "K-2") == valid
    assert _count(session) == 2
