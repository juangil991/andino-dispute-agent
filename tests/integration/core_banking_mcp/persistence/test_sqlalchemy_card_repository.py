"""Integración del repositorio de tarjetas sobre SQLite en memoria (AC-005-04, 05, 08, 12, 14)."""

# ruff: noqa: E501  (los enunciados de RN de la trazabilidad se citan en una sola línea)

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.identity_builder import IdentityBuilder

from core_banking_mcp.domain.models.card_block import BlockReason, OwnedCard
from core_banking_mcp.domain.models.customer import Card, CardStatus
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

_BOGOTA = timezone(timedelta(hours=-5))
_BLOCKED_AT = datetime(2026, 10, 17, 5, 0, tzinfo=_BOGOTA)
_REASON = BlockReason.FRAUD_SUSPECTED

# Laura (C-0001): 1234 y 4321 ACTIVE, 5555 BLOCKED sin registro. Pedro (C-0002): 9999.
_LAURA = "C-0001"
_CARD_1234 = "CARD-0001"
_CARD_4321 = "CARD-0002"
_CARD_BLOCKED = "CARD-0003"
_CARD_PEDRO = "CARD-0004"


@pytest.fixture
def session() -> Session:
    engine = create_engine_from_url("sqlite:///:memory:")
    create_schema(engine)
    session = session_factory(engine)()
    customers = SqlAlchemyCustomerRepository(session)
    laura = (
        CustomerBuilder()
        .with_id(_LAURA)
        .with_document("DOC-0001")
        .with_cards(
            Card("1234", CardStatus.ACTIVE),
            Card("4321", CardStatus.ACTIVE),
            Card("5555", CardStatus.BLOCKED),
        )
        .build()
    )
    pedro = (
        CustomerBuilder()
        .with_id("C-0002")
        .with_document("DOC-0002")
        .with_cards(Card("9999", CardStatus.ACTIVE))
        .build()
    )
    customers.add(laura, identity=IdentityBuilder().build())
    customers.add(pedro, identity=IdentityBuilder().build())
    return session


@pytest.fixture
def repo(session: Session) -> SqlAlchemyCardRepository:
    return SqlAlchemyCardRepository(session)


def _block(
    repo: SqlAlchemyCardRepository,
    card: str = _CARD_1234,
    conversation: str = "A",
    key: str = "K-1",
):  # type: ignore[no-untyped-def]
    return repo.block(conversation, key, card, _REASON, _BLOCKED_AT)


def _status(repo: SqlAlchemyCardRepository, card: str) -> CardStatus:
    found = repo.find_customer_card(_LAURA, card)
    assert found is not None
    return found.status


def _count_blocks(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(CardBlockRow)) or 0


# Regla: RN-005-04 — La tarjeta debe pertenecer al cliente verificado en la conversación. Si no es así, porque es de otro cliente o porque no existe, se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en ambos casos y sin datos de ningún cliente.
# AC-005-08 · Art. 7 (identidad verificada)
def test_ac_005_08_find_customer_card__other_customer_or_missing__returns_none(
    repo: SqlAlchemyCardRepository,
) -> None:
    """AC-005-08: tarjeta de otro cliente o inexistente devuelve None; la propia, OwnedCard."""
    assert repo.find_customer_card(_LAURA, _CARD_PEDRO) is None
    assert repo.find_customer_card(_LAURA, "CARD-9999") is None
    assert repo.find_customer_card(_LAURA, _CARD_4321) == OwnedCard(
        _CARD_4321, "4321", CardStatus.ACTIVE
    )


# Regla: RN-005-12 — Bloquear una tarjeta solo cambia el estado de esa tarjeta y registra el bloqueo y la clave de reintento. No cambia las demás tarjetas del cliente, sus transacciones, sus disputas ni el estado de verificación de la conversación. No decide si hay fraude, no abre disputas ni escala.
# AC-005-12 · Art. 5
def test_ac_005_12_block__other_cards_of_customer__remain_unchanged(
    repo: SqlAlchemyCardRepository, session: Session
) -> None:
    """AC-005-12: la tarjeta 4321 queda BLOCKED, 1 fila en card_blocks y 1234 sigue ACTIVE."""
    _block(repo, card=_CARD_4321)

    assert _status(repo, _CARD_4321) is CardStatus.BLOCKED
    assert _status(repo, _CARD_1234) is CardStatus.ACTIVE
    assert _count_blocks(session) == 1


# Regla: RN-005-07 — La clave de reintento es única **dentro de cada conversación** y solo se registra cuando se crea un bloqueo nuevo. Si la conversación ya usó la clave con la **misma** tarjeta y el **mismo** motivo, se devuelve el resultado de esa solicitud (mismo `blocked_at` y `already_blocked = false`) sin registrar otro bloqueo. Si la usó con otra tarjeta u otro motivo, se rechaza con `INVALID_INPUT` y no se cambia nada. La misma clave en otra conversación es una solicitud independiente.
# AC-005-05 · Art. 10 (ante la duda, escalar)
def test_ac_005_05_find_block_by_key__other_conversation__returns_none(
    repo: SqlAlchemyCardRepository,
) -> None:
    """AC-005-05: búsqueda por clave dentro de la conversación; blocked_at en UTC; pareja única."""
    created = _block(repo, conversation="A", key="K-1")

    found = repo.find_block_by_key("A", "K-1")
    assert found == created
    assert found is not None
    assert found.card_id == _CARD_1234
    assert found.reason is _REASON
    assert found.blocked_at == datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
    assert found.blocked_at.tzinfo is UTC
    assert repo.find_block_by_key("B", "K-1") is None

    with pytest.raises(Exception):  # noqa: B017, PT011 - IntegrityError de SQLAlchemy
        _block(repo, card=_CARD_4321, conversation="A", key="K-1")


# Regla: RN-005-05 — Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada.
# Regla: RN-005-06 — Un bloqueo nuevo registra `blocked_at`, igual al instante del reloj inyectado en ISO 8601 con la zona de Bogotá (`−05:00`), y el `reason` recibido. Si una tarjeta ya bloqueada no tiene un bloqueo registrado (p. ej. por semilla), la respuesta trae `blocked_at = null` y `reason = null`.
# AC-005-04 · Art. 10 (ante la duda, escalar)
def test_ac_005_04_find_block_by_card__seeded_blocked_card__returns_none(
    repo: SqlAlchemyCardRepository,
) -> None:
    """AC-005-04: BLOCKED sin fila en card_blocks devuelve None; tras block, el bloqueo."""
    assert _status(repo, _CARD_BLOCKED) is CardStatus.BLOCKED
    assert repo.find_block_by_card(_CARD_BLOCKED) is None
    assert repo.find_block_by_card(_CARD_1234) is None

    created = _block(repo)

    assert repo.find_block_by_card(_CARD_1234) == created


# Regla: RN-005-13 — Ante una falla inesperada (p. ej. el repositorio de tarjetas no responde al bloquear), la herramienta devuelve `INTERNAL` con `retryable = false` y sin detalles internos (trazas, SQL, texto de la excepción). La operación es atómica: la tarjeta conserva su estado anterior y no queda registrado ningún bloqueo ni clave de reintento.
# AC-005-14 · Art. 10 (ante la duda, escalar)
@pytest.mark.parametrize(
    "failure",
    ["unique_index", "not_active", "after_update"],
    ids=["duplicate_key", "card_not_active", "failure_after_update"],
)
def test_ac_005_14_block__failure__rolls_back_and_session_stays_usable(
    repo: SqlAlchemyCardRepository,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """AC-005-14: tras un block fallido, rollback: tarjeta intacta y sesión usable."""
    _block(repo, card=_CARD_1234, conversation="A", key="K-1")
    if failure == "unique_index":
        target, conversation, key = _CARD_4321, "A", "K-1"
    elif failure == "not_active":
        target, conversation, key = _CARD_BLOCKED, "A", "K-2"
    else:
        target, conversation, key = _CARD_4321, "A", "K-2"

        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("fallo forzado")

        monkeypatch.setattr(session, "add", boom)

    with pytest.raises(Exception):  # noqa: B017, PT011
        _block(repo, card=target, conversation=conversation, key=key)
    monkeypatch.undo()

    assert _count_blocks(session) == 1
    assert repo.find_block_by_key("A", "K-2") is None
    assert _status(repo, _CARD_4321) is CardStatus.ACTIVE
    assert session.scalar(select(CardRow.status).where(CardRow.card_ref == _CARD_BLOCKED)) == (
        CardStatus.BLOCKED.value
    )
    valid = _block(repo, card=_CARD_4321, conversation="A", key="K-3")
    assert repo.find_block_by_key("A", "K-3") == valid
    assert _status(repo, _CARD_4321) is CardStatus.BLOCKED
