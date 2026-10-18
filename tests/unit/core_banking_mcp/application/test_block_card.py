"""Tests del caso de uso BlockCard (spec 005, comportamiento)."""

# ruff: noqa: E501  (los enunciados de RN de la trazabilidad se citan en una sola línea)

from datetime import UTC, datetime, timedelta, timezone

import pytest
from tests.fakes.card_block_builder import CardBlockBuilder
from tests.fakes.failing_card_repository import FailingCardRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_card_repository import FakeCardRepository
from tests.fakes.fake_verification_store import FakeVerificationStore
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.owned_card_builder import OwnedCardBuilder

from core_banking_mcp.application.errors import (
    CardNotBlockableError,
    CardNotFoundError,
    CoreUnavailableError,
    IdentityNotVerifiedError,
)
from core_banking_mcp.application.use_cases.block_card import (
    BlockCard,
    BlockCardCommand,
    BlockCardResult,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.card_block import BlockReason, OwnedCard
from core_banking_mcp.domain.models.customer import CardStatus
from core_banking_mcp.domain.models.identity import VerificationState

NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
BOGOTA = timezone(timedelta(hours=-5))
CONV = "A"


class SpyStore(FakeVerificationStore):
    """Almacén que registra lecturas y escrituras."""

    def __init__(self) -> None:
        super().__init__()
        self.gets: list[str] = []
        self.saves: list[str] = []

    def get(self, conversation_id: str) -> VerificationState:
        self.gets.append(conversation_id)
        return super().get(conversation_id)

    def save(self, conversation_id: str, state: VerificationState) -> None:
        self.saves.append(conversation_id)
        super().save(conversation_id, state)


class SpyCards(FakeCardRepository):
    """Repositorio que registra las consultas."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.calls: list[str] = []
        self.customer_ids: list[str] = []

    def find_customer_card(self, customer_id: str, card_id: str) -> OwnedCard | None:
        self.calls.append("find_customer_card")
        self.customer_ids.append(customer_id)
        return super().find_customer_card(customer_id, card_id)

    def find_block_by_key(self, conversation_id: str, idempotency_key: str):  # type: ignore[no-untyped-def]
        self.calls.append("find_block_by_key")
        return super().find_block_by_key(conversation_id, idempotency_key)

    def find_block_by_card(self, card_id: str):  # type: ignore[no-untyped-def]
        self.calls.append("find_block_by_card")
        return super().find_block_by_card(card_id)


def _card(
    card_id: str = "CARD-L1", last4: str = "4321", status: CardStatus = CardStatus.ACTIVE
) -> OwnedCard:
    return OwnedCardBuilder().with_id(card_id).with_last4(last4).with_status(status).build()


def _cards(*extra: OwnedCard, first: OwnedCard | None = None) -> dict[str, list[OwnedCard]]:
    return {
        "C-0001": [first or _card(), *extra],
        "C-0002": [_card("CARD-P1", "1234")],
    }


def _store(*conversations: str) -> SpyStore:
    store = SpyStore()
    for conversation in conversations:
        store.with_verified(conversation, "C-0001")
    return store


def _use_case(
    cards: FakeCardRepository, store: FakeVerificationStore, now: datetime = NOW
) -> BlockCard:
    return BlockCard(cards, store, FakeAuditLog(), FixedClock(now))


def _command(
    conversation_id: str | None = CONV,
    card_id: str | None = "CARD-L1",
    reason: str | None = "FRAUD_SUSPECTED",
    key: str | None = "K-1",
) -> BlockCardCommand:
    return BlockCardCommand(conversation_id, card_id, reason, key)


def _status(repo: FakeCardRepository, customer_id: str, card_id: str) -> CardStatus:
    card = repo.find_customer_card(customer_id, card_id)
    assert card is not None
    return card.status


# Regla: RN-005-01 — La solicitud indica la tarjeta por su `card_id`, el identificador opaco que devuelve `consultar_transacciones` (RN-003-12); además indica el motivo (`reason`) y una clave de reintento (`idempotency_key`) generada por el consumidor.
# Regla: RN-005-05 — Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada.
# Regla: RN-005-06 — Un bloqueo nuevo registra `blocked_at`, igual al instante del reloj inyectado en ISO 8601 con la zona de Bogotá (`−05:00`), y el `reason` recibido. Si una tarjeta ya bloqueada no tiene un bloqueo registrado (p. ej. por semilla), la respuesta trae `blocked_at = null` y `reason = null`.
# AC-005-01 · Art. 3
def test_ac_005_01_blocks_active_card() -> None:
    """AC-005-01: bloquear una tarjeta activa."""
    repo = FakeCardRepository(_cards())
    store = _store(CONV)
    before = store.get(CONV)
    result = _use_case(repo, store).execute(_command())

    assert isinstance(result, BlockCardResult)
    assert result.outcome == "blocked"
    assert result.card == _card(status=CardStatus.BLOCKED)
    assert result.block is not None
    assert result.block.blocked_at == NOW
    assert result.block.reason is BlockReason.FRAUD_SUSPECTED
    assert _status(repo, "C-0001", "CARD-L1") is CardStatus.BLOCKED
    assert len(repo.blocks) == 1
    assert repo.blocks[0] == result.block
    assert store.get(CONV) == before
    assert store.saves == []


# Regla: RN-005-02 — El motivo es un código de un catálogo cerrado que distingue mayúsculas: `FRAUD_SUSPECTED` (sospecha de fraude) y `LOST_OR_STOLEN` (tarjeta perdida o robada). Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`.
# AC-005-02 · Art. 3
@pytest.mark.parametrize("reason", ["FRAUD_SUSPECTED", "LOST_OR_STOLEN"])
def test_ac_005_02_accepts_each_reason(reason: str) -> None:
    """AC-005-02: motivos permitidos."""
    repo = FakeCardRepository(_cards())
    result = _use_case(repo, _store(CONV)).execute(_command(reason=reason))

    assert result.outcome == "blocked"
    assert result.block is not None
    assert result.block.reason is BlockReason(reason)
    assert _status(repo, "C-0001", "CARD-L1") is CardStatus.BLOCKED


# Regla: RN-005-02 — El motivo es un código de un catálogo cerrado que distingue mayúsculas: `FRAUD_SUSPECTED` (sospecha de fraude) y `LOST_OR_STOLEN` (tarjeta perdida o robada). Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`.
# Regla: RN-005-08 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_id` obligatorio, de 1 a 64 caracteres tras recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-005-02. Toda violación ⇒ `INVALID_INPUT`, sin cambiar ninguna tarjeta.
# AC-005-03 · Art. 3
@pytest.mark.parametrize(
    "reason",
    ["STOLEN", "fraud_suspected", "sospecha de fraude", "", None],
    ids=["fuera-del-catalogo", "minusculas", "texto", "vacio", "ausente"],
)
def test_ac_005_03_rejects_invalid_reason(reason: str | None) -> None:
    """AC-005-03: motivo inválido."""
    repo = SpyCards(_cards())
    store = _store(CONV)
    with pytest.raises(InvalidInputError):
        _use_case(repo, store).execute(_command(reason=reason))

    assert store.gets == []
    assert repo.calls == []
    assert not repo.block_called
    assert _status(repo, "C-0001", "CARD-L1") is CardStatus.ACTIVE
    assert repo.blocks == []


# Regla: RN-005-08 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_id` obligatorio, de 1 a 64 caracteres tras recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-005-02. Toda violación ⇒ `INVALID_INPUT`, sin cambiar ninguna tarjeta.
# AC-005-10 · Art. 3
@pytest.mark.parametrize(
    "overrides",
    [
        {"card_id": None},
        {"card_id": ""},
        {"card_id": "   "},
        {"card_id": "X" * 65},
        {"key": None},
        {"key": ""},
        {"key": "   "},
        {"key": "K" * 65},
        {"conversation_id": None},
        {"conversation_id": ""},
        {"conversation_id": "   "},
    ],
    ids=[
        "card-ausente",
        "card-vacio",
        "card-espacios",
        "card-65",
        "key-ausente",
        "key-vacia",
        "key-espacios",
        "key-65",
        "conv-ausente",
        "conv-vacia",
        "conv-espacios",
    ],
)
def test_ac_005_10_rejects_invalid_request_data(overrides: dict[str, str | None]) -> None:
    """AC-005-10: datos de la solicitud inválidos."""
    repo = SpyCards(_cards())
    store = _store(CONV)
    with pytest.raises(InvalidInputError):
        _use_case(repo, store).execute(_command(**overrides))  # type: ignore[arg-type]

    assert store.gets == []
    assert repo.calls == []
    assert not repo.block_called
    assert _status(repo, "C-0001", "CARD-L1") is CardStatus.ACTIVE
    assert repo.blocks == []


# Regla: RN-005-05 — Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada.
# Regla: RN-005-12 — Bloquear una tarjeta solo cambia el estado de esa tarjeta y registra el bloqueo y la clave de reintento. No cambia las demás tarjetas del cliente, sus transacciones, sus disputas ni el estado de verificación de la conversación. No decide si hay fraude, no abre disputas ni escala.
# AC-005-04 · Art. 3
def test_ac_005_04_previous_state_active() -> None:
    """AC-005-04: estado previo ACTIVE."""
    repo = FakeCardRepository(_cards())
    result = _use_case(repo, _store(CONV)).execute(_command())

    assert result.outcome == "blocked"
    assert _status(repo, "C-0001", "CARD-L1") is CardStatus.BLOCKED
    assert len(repo.blocks) == 1


# Regla: RN-005-05 — Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada.
# AC-005-04 · Art. 3
def test_ac_005_04_previous_state_blocked_with_block() -> None:
    """AC-005-04: estado previo BLOCKED con bloqueo registrado."""
    original = (
        CardBlockBuilder()
        .with_card("CARD-L1")
        .with_conversation("OLD")
        .with_key("K-0")
        .with_reason(BlockReason.LOST_OR_STOLEN)
        .with_blocked_at(datetime(2026, 10, 15, 9, 0, tzinfo=BOGOTA))
        .build()
    )
    repo = FakeCardRepository(_cards(first=_card(status=CardStatus.BLOCKED)), [original])
    result = _use_case(repo, _store(CONV)).execute(_command())

    assert result.outcome == "already_blocked"
    assert result.block == original
    assert result.card.status is CardStatus.BLOCKED
    assert not repo.block_called
    assert repo.blocks == [original]


# Regla: RN-005-05 — Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada.
# Regla: RN-005-06 — Un bloqueo nuevo registra `blocked_at`, igual al instante del reloj inyectado en ISO 8601 con la zona de Bogotá (`−05:00`), y el `reason` recibido. Si una tarjeta ya bloqueada no tiene un bloqueo registrado (p. ej. por semilla), la respuesta trae `blocked_at = null` y `reason = null`.
# AC-005-04 · Art. 3
def test_ac_005_04_previous_state_blocked_without_block() -> None:
    """AC-005-04: estado previo BLOCKED sin bloqueo registrado (semilla)."""
    repo = FakeCardRepository(_cards(first=_card(status=CardStatus.BLOCKED)))
    result = _use_case(repo, _store(CONV)).execute(_command())

    assert result.outcome == "already_blocked"
    assert result.block is None
    assert result.card.status is CardStatus.BLOCKED
    assert not repo.block_called
    assert repo.blocks == []


# Regla: RN-005-05 — Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada.
# AC-005-04 · Art. 3
def test_ac_005_04_previous_state_cancelled() -> None:
    """AC-005-04: estado previo CANCELLED."""
    repo = FakeCardRepository(_cards(first=_card(status=CardStatus.CANCELLED)))
    with pytest.raises(CardNotBlockableError):
        _use_case(repo, _store(CONV)).execute(_command())

    assert not repo.block_called
    assert _status(repo, "C-0001", "CARD-L1") is CardStatus.CANCELLED
    assert repo.blocks == []


# Regla: RN-005-07 — La clave de reintento es única **dentro de cada conversación** y solo se registra cuando se crea un bloqueo nuevo. Si la conversación ya usó la clave con la **misma** tarjeta y el **mismo** motivo, se devuelve el resultado de esa solicitud (mismo `blocked_at` y `already_blocked = false`) sin registrar otro bloqueo. Si la usó con otra tarjeta u otro motivo, se rechaza con `INVALID_INPUT` y no se cambia nada. La misma clave en otra conversación es una solicitud independiente.
# Regla: RN-005-09 — Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) clave de reintento ya usada en la conversación → el bloqueo existente (misma solicitud) o `INVALID_INPUT` (solicitud distinta); (4) tarjeta del cliente verificado → `NOT_FOUND`; (5) estado de la tarjeta → `CARD_NOT_BLOCKABLE` (cancelada), `already_blocked` (bloqueada) o bloqueo nuevo (activa).
# AC-005-05 · Art. 3
def test_ac_005_05_repeated_request_does_not_duplicate_block() -> None:
    """AC-005-05: repetir la misma solicitud no duplica el bloqueo."""
    repo = FakeCardRepository(_cards())
    store = _store(CONV)
    first = _use_case(repo, store).execute(_command())
    second = _use_case(repo, store, NOW + timedelta(hours=1)).execute(_command())

    assert first.outcome == "blocked"
    assert second.outcome == "replayed"
    assert second.block == first.block
    assert second.block is not None
    assert second.block.blocked_at == NOW
    assert len(repo.blocks) == 1


# Regla: RN-005-07 — La clave de reintento es única **dentro de cada conversación** y solo se registra cuando se crea un bloqueo nuevo. Si la conversación ya usó la clave con la **misma** tarjeta y el **mismo** motivo, se devuelve el resultado de esa solicitud (mismo `blocked_at` y `already_blocked = false`) sin registrar otro bloqueo. Si la usó con otra tarjeta u otro motivo, se rechaza con `INVALID_INPUT` y no se cambia nada. La misma clave en otra conversación es una solicitud independiente.
# AC-005-06 · Art. 3
@pytest.mark.parametrize(
    ("card_id", "reason"),
    [("CARD-L2", "FRAUD_SUSPECTED"), ("CARD-L1", "LOST_OR_STOLEN")],
    ids=["otra-tarjeta", "otro-motivo"],
)
def test_ac_005_06_reused_key_with_other_data_is_rejected(card_id: str, reason: str) -> None:
    """AC-005-06: una clave de reintento reutilizada con otros datos se rechaza."""
    other = _card("CARD-L2", "8765")
    repo = FakeCardRepository(_cards(other))
    store = _store(CONV)
    _use_case(repo, store).execute(_command())
    block_before = repo.blocks

    with pytest.raises(InvalidInputError):
        _use_case(repo, store).execute(_command(card_id=card_id, reason=reason))

    assert _status(repo, "C-0001", "CARD-L2") is CardStatus.ACTIVE
    assert repo.blocks == block_before


# Regla: RN-005-07 — La clave de reintento es única **dentro de cada conversación** y solo se registra cuando se crea un bloqueo nuevo. Si la conversación ya usó la clave con la **misma** tarjeta y el **mismo** motivo, se devuelve el resultado de esa solicitud (mismo `blocked_at` y `already_blocked = false`) sin registrar otro bloqueo. Si la usó con otra tarjeta u otro motivo, se rechaza con `INVALID_INPUT` y no se cambia nada. La misma clave en otra conversación es una solicitud independiente.
# AC-005-07 · Art. 3
def test_ac_005_07_key_belongs_to_its_conversation() -> None:
    """AC-005-07: la clave de reintento pertenece a su conversación."""
    repo = FakeCardRepository(_cards())
    store = _store("A", "B")
    first = _use_case(repo, store).execute(_command(conversation_id="A"))
    result = _use_case(repo, store).execute(_command(conversation_id="B"))

    assert result.outcome == "already_blocked"
    assert result.block == first.block
    assert len(repo.blocks) == 1


# Regla: RN-005-04 — La tarjeta debe pertenecer al cliente verificado en la conversación. Si no es así, porque es de otro cliente o porque no existe, se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en ambos casos y sin datos de ningún cliente.
# AC-005-08 · Art. 3
def test_ac_005_08_foreign_or_missing_card_is_not_found() -> None:
    """AC-005-08: una tarjeta ajena o inexistente recibe la misma respuesta."""
    repo = SpyCards(_cards())
    store = _store(CONV)
    use_case = _use_case(repo, store)

    messages = []
    for card_id, key in (("CARD-P1", "K-1"), ("CARD-9999", "K-2")):
        with pytest.raises(CardNotFoundError) as excinfo:
            use_case.execute(_command(card_id=card_id, key=key))
        messages.append(str(excinfo.value))

    assert messages[0] == messages[1]
    assert repo.customer_ids == ["C-0001", "C-0001"]
    assert not repo.block_called
    assert _status(repo, "C-0002", "CARD-P1") is CardStatus.ACTIVE
    assert repo.blocks == []


def _unverified_store(situation: str) -> SpyStore:
    store = SpyStore()
    if situation == "nunca-verificada":
        return store
    if situation == "un-intento-fallido":
        return store.with_failures(CONV, 1)  # type: ignore[return-value]
    if situation == "bloqueada":
        return store.with_failures(CONV, 3)  # type: ignore[return-value]
    return store.with_verified("A", "C-0001")  # type: ignore[return-value]


# Regla: RN-005-03 — La herramienta exige que la conversación esté verificada en el servidor (estado de RN-002-13). Se rechaza con `IDENTITY_NOT_VERIFIED` toda conversación sin verificación exitosa, desconocida o bloqueada por agotar sus intentos. La verificación no se traslada: estar verificada en otra conversación no cuenta.
# Regla: RN-005-12 — Bloquear una tarjeta solo cambia el estado de esa tarjeta y registra el bloqueo y la clave de reintento. No cambia las demás tarjetas del cliente, sus transacciones, sus disputas ni el estado de verificación de la conversación. No decide si hay fraude, no abre disputas ni escala.
# AC-005-09 · Art. 3
@pytest.mark.parametrize(
    "situation",
    ["nunca-verificada", "un-intento-fallido", "bloqueada", "verificada-en-otra"],
)
def test_ac_005_09_unverified_conversation_is_rejected(situation: str) -> None:
    """AC-005-09: no se bloquea una tarjeta sin la identidad verificada."""
    repo = SpyCards(_cards())
    store = _unverified_store(situation)
    snapshot = {c: store.get(c) for c in ("A", CONV)}
    request_conversation = "B" if situation == "verificada-en-otra" else CONV
    store.gets.clear()

    with pytest.raises(IdentityNotVerifiedError):
        _use_case(repo, store).execute(_command(conversation_id=request_conversation))

    assert repo.calls == []
    assert not repo.block_called
    assert _status(repo, "C-0001", "CARD-L1") is CardStatus.ACTIVE
    assert repo.blocks == []
    assert store.saves == []
    assert {c: store.get(c) for c in ("A", CONV)} == snapshot


# Regla: RN-005-09 — Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) clave de reintento ya usada en la conversación → el bloqueo existente (misma solicitud) o `INVALID_INPUT` (solicitud distinta); (4) tarjeta del cliente verificado → `NOT_FOUND`; (5) estado de la tarjeta → `CARD_NOT_BLOCKABLE` (cancelada), `already_blocked` (bloqueada) o bloqueo nuevo (activa).
# AC-005-11 · Art. 3
def test_ac_005_11_order_invalid_input_before_identity() -> None:
    """AC-005-11: fila 1, validación antes que identidad."""
    repo = FakeCardRepository(_cards())
    with pytest.raises(InvalidInputError):
        _use_case(repo, SpyStore()).execute(_command(reason="STOLEN"))


# Regla: RN-005-09 — Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) clave de reintento ya usada en la conversación → el bloqueo existente (misma solicitud) o `INVALID_INPUT` (solicitud distinta); (4) tarjeta del cliente verificado → `NOT_FOUND`; (5) estado de la tarjeta → `CARD_NOT_BLOCKABLE` (cancelada), `already_blocked` (bloqueada) o bloqueo nuevo (activa).
# AC-005-11 · Art. 3
def test_ac_005_11_order_identity_before_card() -> None:
    """AC-005-11: fila 2, identidad antes que tarjeta."""
    repo = FakeCardRepository(_cards())
    with pytest.raises(IdentityNotVerifiedError):
        _use_case(repo, SpyStore()).execute(_command(card_id="CARD-9999"))


# Regla: RN-005-09 — Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) clave de reintento ya usada en la conversación → el bloqueo existente (misma solicitud) o `INVALID_INPUT` (solicitud distinta); (4) tarjeta del cliente verificado → `NOT_FOUND`; (5) estado de la tarjeta → `CARD_NOT_BLOCKABLE` (cancelada), `already_blocked` (bloqueada) o bloqueo nuevo (activa).
# AC-005-11 · Art. 3
def test_ac_005_11_order_key_before_card() -> None:
    """AC-005-11: fila 3, clave de reintento antes que tarjeta."""
    repo = FakeCardRepository(_cards())
    store = _store(CONV)
    _use_case(repo, store).execute(_command())
    with pytest.raises(InvalidInputError):
        _use_case(repo, store).execute(_command(card_id="CARD-9999", key="K-1"))


# Regla: RN-005-09 — Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) clave de reintento ya usada en la conversación → el bloqueo existente (misma solicitud) o `INVALID_INPUT` (solicitud distinta); (4) tarjeta del cliente verificado → `NOT_FOUND`; (5) estado de la tarjeta → `CARD_NOT_BLOCKABLE` (cancelada), `already_blocked` (bloqueada) o bloqueo nuevo (activa).
# AC-005-11 · Art. 3
def test_ac_005_11_order_card_before_state() -> None:
    """AC-005-11: fila 4, tarjeta del cliente antes que estado."""
    cards = _cards()
    cards["C-0002"] = [_card("CARD-P1", "1234", CardStatus.CANCELLED)]
    repo = FakeCardRepository(cards)
    with pytest.raises(CardNotFoundError):
        _use_case(repo, _store(CONV)).execute(_command(card_id="CARD-P1"))


# Regla: RN-005-09 — Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) clave de reintento ya usada en la conversación → el bloqueo existente (misma solicitud) o `INVALID_INPUT` (solicitud distinta); (4) tarjeta del cliente verificado → `NOT_FOUND`; (5) estado de la tarjeta → `CARD_NOT_BLOCKABLE` (cancelada), `already_blocked` (bloqueada) o bloqueo nuevo (activa).
# AC-005-11 · Art. 3
def test_ac_005_11_order_key_before_state() -> None:
    """AC-005-11: fila 5, repetición tras cancelar la tarjeta."""
    original = (
        CardBlockBuilder()
        .with_card("CARD-L1")
        .with_conversation(CONV)
        .with_key("K-1")
        .with_blocked_at(NOW)
        .build()
    )
    repo = FakeCardRepository(_cards(first=_card(status=CardStatus.CANCELLED)), [original])
    result = _use_case(repo, _store(CONV), NOW + timedelta(hours=1)).execute(_command())

    assert result.outcome == "replayed"
    assert result.block == original
    assert not repo.block_called


# Regla: RN-005-12 — Bloquear una tarjeta solo cambia el estado de esa tarjeta y registra el bloqueo y la clave de reintento. No cambia las demás tarjetas del cliente, sus transacciones, sus disputas ni el estado de verificación de la conversación. No decide si hay fraude, no abre disputas ni escala.
# AC-005-12 · Art. 3
def test_ac_005_12_blocking_does_not_affect_other_cards() -> None:
    """AC-005-12: bloquear una tarjeta no afecta a las demás."""
    repo = FakeCardRepository(_cards(_card("CARD-L2", "8765")))
    _use_case(repo, _store(CONV)).execute(_command())

    assert _status(repo, "C-0001", "CARD-L1") is CardStatus.BLOCKED
    assert _status(repo, "C-0001", "CARD-L2") is CardStatus.ACTIVE
    assert repo.find_block_by_card("CARD-L2") is None


# Regla: RN-005-13 — Ante una falla inesperada (p. ej. el repositorio de tarjetas no responde al bloquear), la herramienta devuelve `INTERNAL` con `retryable = false` y sin detalles internos (trazas, SQL, texto de la excepción). La operación es atómica: la tarjeta conserva su estado anterior y no queda registrado ningún bloqueo ni clave de reintento.
# AC-005-14 · Art. 3
def test_ac_005_14_failure_leaves_card_untouched_and_hides_detail() -> None:
    """AC-005-14: una falla al bloquear no deja la tarjeta a medias."""
    repo = FailingCardRepository(_cards())
    store = _store(CONV)
    with pytest.raises(CoreUnavailableError) as excinfo:
        _use_case(repo, store).execute(_command())

    assert "secreto" not in str(excinfo.value)
    assert "fallo simulado" not in str(excinfo.value)
    assert _status(repo, "C-0001", "CARD-L1") is CardStatus.ACTIVE
    assert repo.blocks == []

    repo.repair()
    result = _use_case(repo, store).execute(_command())
    assert result.outcome == "blocked"
    assert len(repo.blocks) == 1
