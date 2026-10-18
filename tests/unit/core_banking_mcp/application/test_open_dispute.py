"""Tests del caso de uso OpenDispute (spec 004, comportamiento)."""

# ruff: noqa: E501  (los enunciados de RN de la trazabilidad se citan en una sola línea)

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest
from tests.fakes.dispute_builder import DisputeBuilder
from tests.fakes.failing_dispute_repository import FailingDisputeRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_dispute_repository import FakeDisputeRepository
from tests.fakes.fake_transaction_repository import FakeTransactionRepository
from tests.fakes.fake_verification_store import FakeVerificationStore
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.errors import (
    CoreUnavailableError,
    DisputeAlreadyOpenError,
    IdentityNotVerifiedError,
    TransactionNotDisputableError,
    TransactionNotFoundError,
)
from core_banking_mcp.application.use_cases.open_dispute import (
    OpenDispute,
    OpenDisputeCommand,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.dispute import Dispute, DisputeReason, DisputeStatus
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.domain.models.transaction import (
    CustomerCard,
    Transaction,
    TransactionStatus,
)

NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
BOGOTA = timezone(timedelta(hours=-5))
CARD = CustomerCard("K-0001", "4321")
OTHER_CARD = CustomerCard("K-0002", "8765")


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


class SpyTransactions(FakeTransactionRepository):
    """Repositorio que registra el cliente con el que se consulta."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.customer_ids: list[str] = []

    def find_customer_transaction(
        self, customer_id: str, transaction_id: str
    ) -> Transaction | None:
        self.customer_ids.append(customer_id)
        return super().find_customer_transaction(customer_id, transaction_id)


def _tx(
    transaction_id: str = "TX-L1",
    status: TransactionStatus = TransactionStatus.CONFIRMED,
    occurred_at: datetime = datetime(2026, 10, 10, 12, 0, tzinfo=BOGOTA),
    card: CustomerCard = CARD,
) -> Transaction:
    return (
        TransactionBuilder()
        .with_id(transaction_id)
        .with_card(card.card_id, card.last4)
        .with_occurred_at(occurred_at)
        .with_status(status)
        .build()
    )


@dataclass
class Env:
    use_case: OpenDispute
    transactions: SpyTransactions
    disputes: FakeDisputeRepository
    store: SpyStore
    audit: FakeAuditLog
    clock: FixedClock


def _env(
    transactions: list[Transaction] | None = None,
    disputes: FakeDisputeRepository | None = None,
    store: SpyStore | None = None,
    verified: bool = True,
) -> Env:
    spy_store = store if store is not None else SpyStore()
    if store is None and verified:
        spy_store.with_verified("A", "C-0001")
    tx_repo = SpyTransactions(
        cards={"C-0001": [CARD], "C-0002": [OTHER_CARD]},
        transactions=transactions if transactions is not None else [_tx()],
    )
    dispute_repo = disputes if disputes is not None else FakeDisputeRepository()
    audit = FakeAuditLog()
    clock = FixedClock(NOW)
    return Env(
        OpenDispute(tx_repo, dispute_repo, spy_store, audit, clock),
        tx_repo,
        dispute_repo,
        spy_store,
        audit,
        clock,
    )


def _cmd(
    conversation_id: str | None = "A",
    transaction_id: str | None = "TX-L1",
    reason: str | None = "UNRECOGNIZED_CHARGE",
    idempotency_key: str | None = "K-1",
) -> OpenDisputeCommand:
    return OpenDisputeCommand(conversation_id, transaction_id, reason, idempotency_key)


def _repos_untouched(env: Env) -> bool:
    return not env.transactions.called and not env.disputes.called


# Regla: RN-004-01 — La solicitud indica la transacción por el `transaction_id` que devuelve `consultar_transacciones`, el motivo (`reason`) y una clave de reintento (`idempotency_key`) generada por el consumidor.
# Regla: RN-004-11 — Una disputa nueva queda con `status = OPEN`, un `dispute_id` opaco y único que no se deriva del número de la tarjeta, y `opened_at` igual al instante del reloj inyectado expresado en ISO 8601 con la zona de Bogotá (`−05:00`).
# Regla: RN-004-12 — La respuesta exitosa contiene solo `dispute_id`, `status`, `opened_at`, `reason` (el código) y `transaction` con los campos de `TransactionItem`.
# Regla: RN-004-14 — Abrir una disputa solo registra la disputa y la clave de reintento usada. No cambia la transacción, la tarjeta ni el estado de verificación de la conversación.
# AC-004-01 · Art. 6
def test_ac_004_01_opens_dispute_on_confirmed_transaction() -> None:
    """AC-004-01: abre la disputa OPEN, con opened_at del reloj, y no cambia el almacén."""
    env = _env()
    state_before = env.store.get("A")

    result = env.use_case.execute(_cmd())

    assert result.dispute.status is DisputeStatus.OPEN
    assert result.dispute.dispute_id != ""
    assert result.dispute.opened_at == NOW
    assert result.dispute.reason is DisputeReason.UNRECOGNIZED_CHARGE
    assert result.dispute.transaction_id == "TX-L1"
    assert result.transaction == _tx()
    assert result.replayed is False
    assert env.disputes.disputes == [result.dispute]
    assert env.store.get("A") == state_before
    assert env.store.saves == []


# Regla: RN-004-02 — El motivo es un código de un catálogo cerrado: UNRECOGNIZED_CHARGE, DUPLICATE_CHARGE, INCORRECT_AMOUNT, NOT_RECEIVED y OTHER.
# AC-004-02 · Art. 6
@pytest.mark.parametrize("reason", [r.value for r in DisputeReason])
def test_ac_004_02_accepts_every_catalog_reason(reason: str) -> None:
    """AC-004-02: cada motivo del catálogo abre la disputa OPEN con ese motivo."""
    env = _env()

    result = env.use_case.execute(_cmd(reason=reason))

    assert result.dispute.status is DisputeStatus.OPEN
    assert result.dispute.reason is DisputeReason(reason)
    assert len(env.disputes.disputes) == 1


# Regla: RN-004-02 — El motivo es un código de un catálogo cerrado, sensible a mayúsculas. Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`.
# Regla: RN-004-09 — Validación de entrada: `reason` obligatorio y del catálogo de RN-004-02. Toda violación ⇒ `INVALID_INPUT`, sin disputa registrada.
# AC-004-03 · Art. 7
@pytest.mark.parametrize(
    "reason",
    ["FRAUD", "unrecognized_charge", "no reconoce el cargo", "", None],
    ids=["fuera-catalogo", "minusculas", "texto", "vacio", "ausente"],
)
def test_ac_004_03_rejects_invalid_reason(reason: str | None) -> None:
    """AC-004-03: motivo inválido lanza InvalidInputError sin consultar almacén ni repositorios."""
    env = _env()

    with pytest.raises(InvalidInputError):
        env.use_case.execute(_cmd(reason=reason))

    assert env.store.gets == []
    assert _repos_untouched(env)
    assert env.disputes.disputes == []


# Regla: RN-004-05 — Solo se puede disputar una transacción `CONFIRMED`. Una transacción `PENDING` o `REVERSED` se rechaza con `TRANSACTION_NOT_DISPUTABLE` y no se registra nada.
# AC-004-04 · Art. 6
@pytest.mark.parametrize(
    "status",
    [TransactionStatus.PENDING, TransactionStatus.REVERSED],
)
def test_ac_004_04_rejects_non_confirmed_transaction(status: TransactionStatus) -> None:
    """AC-004-04: PENDING y REVERSED lanzan TransactionNotDisputableError sin llamar a add."""
    env = _env(transactions=[_tx(status=status)])

    with pytest.raises(TransactionNotDisputableError):
        env.use_case.execute(_cmd())

    assert env.disputes.disputes == []


# Regla: RN-004-05 — Solo se puede disputar una transacción `CONFIRMED`.
# AC-004-04 · Art. 6
def test_ac_004_04_confirmed_transaction_opens_dispute() -> None:
    """AC-004-04: una transacción CONFIRMED abre la disputa OPEN."""
    env = _env(transactions=[_tx(status=TransactionStatus.CONFIRMED)])

    result = env.use_case.execute(_cmd())

    assert result.dispute.status is DisputeStatus.OPEN
    assert len(env.disputes.disputes) == 1


# Regla: RN-004-06 — No hay plazo máximo para disputar una transacción confirmada: su antigüedad no influye en esta herramienta.
# AC-004-05 · Art. 6
@pytest.mark.parametrize(
    "occurred_at",
    [
        datetime(2026, 10, 16, 12, 0, tzinfo=BOGOTA),
        datetime(2026, 7, 19, 12, 0, tzinfo=BOGOTA),
        datetime(2025, 9, 12, 12, 0, tzinfo=BOGOTA),
    ],
    ids=["1-dia", "90-dias", "400-dias"],
)
def test_ac_004_05_has_no_maximum_age(occurred_at: datetime) -> None:
    """AC-004-05: transacciones de hace 1, 90 y 400 días abren la disputa OPEN."""
    env = _env(transactions=[_tx(occurred_at=occurred_at)])

    result = env.use_case.execute(_cmd())

    assert result.dispute.status is DisputeStatus.OPEN
    assert len(env.disputes.disputes) == 1


# Regla: RN-004-07 — Una transacción tiene como máximo una disputa `OPEN`. Si ya la tiene, la solicitud se rechaza con `DISPUTE_ALREADY_OPEN` cuyo `message` incluye el `dispute_id` de la disputa abierta existente, y no se registra otra.
# AC-004-07 · Art. 6
def test_ac_004_07_open_previous_dispute_is_rejected() -> None:
    """AC-004-07: con D-OLD OPEN lanza DisputeAlreadyOpenError con su ID y una sola disputa."""
    old = DisputeBuilder().with_id("D-OLD").with_transaction("TX-L1").with_key("K-0").build()
    env = _env(disputes=FakeDisputeRepository([old]))

    with pytest.raises(DisputeAlreadyOpenError) as error:
        env.use_case.execute(_cmd(reason="DUPLICATE_CHARGE", idempotency_key="K-2"))

    assert error.value.dispute_id == "D-OLD"
    assert env.disputes.disputes == [old]


# Regla: RN-004-07 — Las disputas previas `CLOSED` o `REJECTED` no impiden abrir una nueva.
# AC-004-07 · Art. 6
@pytest.mark.parametrize("previous", [DisputeStatus.CLOSED, DisputeStatus.REJECTED])
def test_ac_004_07_closed_or_rejected_previous_dispute_allows_new_one(
    previous: DisputeStatus,
) -> None:
    """AC-004-07: con D-OLD CLOSED o REJECTED se abre una disputa nueva con otro ID."""
    old = (
        DisputeBuilder()
        .with_id("D-OLD")
        .with_transaction("TX-L1")
        .with_key("K-0")
        .with_status(previous)
        .build()
    )
    env = _env(disputes=FakeDisputeRepository([old]))

    result = env.use_case.execute(_cmd(reason="DUPLICATE_CHARGE", idempotency_key="K-2"))

    assert result.dispute.status is DisputeStatus.OPEN
    assert result.dispute.dispute_id != "D-OLD"
    assert len(env.disputes.disputes) == 2


# Regla: RN-004-08 — Si la conversación ya usó la clave con la misma transacción y el mismo motivo, se devuelve la disputa que creó esa solicitud (mismo `dispute_id` y `opened_at`) sin registrar otra.
# Regla: RN-004-10 — Las comprobaciones se evalúan en este orden: (3) clave de reintento ya usada en la conversación → la disputa existente (misma solicitud).
# AC-004-08 · Art. 6
def test_ac_004_08_repeating_same_request_returns_same_dispute() -> None:
    """AC-004-08: repetir K-1 con el reloj una hora después devuelve la misma disputa."""
    env = _env()
    first = env.use_case.execute(_cmd())
    later = OpenDispute(
        env.transactions,
        env.disputes,
        env.store,
        env.audit,
        FixedClock(NOW + timedelta(hours=1)),
    )

    second = later.execute(_cmd())

    assert second.dispute == first.dispute
    assert second.dispute.dispute_id == first.dispute.dispute_id
    assert second.dispute.opened_at == first.dispute.opened_at == NOW
    assert second.replayed is True
    assert second.transaction == _tx()
    assert len(env.disputes.disputes) == 1


# Regla: RN-004-08 — Si la usó con otra transacción u otro motivo, se rechaza con `INVALID_INPUT` sin registrar nada.
# AC-004-09 · Art. 7
@pytest.mark.parametrize(
    ("transaction_id", "reason"),
    [("TX-L2", "UNRECOGNIZED_CHARGE"), ("TX-L1", "DUPLICATE_CHARGE")],
    ids=["otra-transaccion", "otro-motivo"],
)
def test_ac_004_09_key_reused_with_other_data_is_rejected(transaction_id: str, reason: str) -> None:
    """AC-004-09: K-1 con TX-L2 o con DUPLICATE_CHARGE lanza InvalidInputError sin llamar a add."""
    env = _env(transactions=[_tx(), _tx("TX-L2")])
    first = env.use_case.execute(_cmd())

    with pytest.raises(InvalidInputError):
        env.use_case.execute(_cmd(transaction_id=transaction_id, reason=reason))

    assert env.disputes.disputes == [first.dispute]


# Regla: RN-004-08 — La misma clave en otra conversación es una solicitud independiente.
# AC-004-10 · Art. 6
def test_ac_004_10_key_belongs_to_its_conversation() -> None:
    """AC-004-10: K-1 usado en A no aplica en B; B recibe DisputeAlreadyOpenError con el ID de A."""
    store = SpyStore().with_verified("A", "C-0001").with_verified("B", "C-0001")  # type: ignore[assignment]
    env = _env(store=store)
    first = env.use_case.execute(_cmd(conversation_id="A"))

    with pytest.raises(DisputeAlreadyOpenError) as error:
        env.use_case.execute(_cmd(conversation_id="B"))

    assert error.value.dispute_id == first.dispute.dispute_id
    assert len(env.disputes.disputes) == 1


# Regla: RN-004-04 — Si la transacción es de otro cliente o no existe, se devuelve `NOT_FOUND` con un mensaje fijo, idéntico en ambos casos, sin datos de ningún cliente.
# Regla: RN-004-13 — La respuesta nunca contiene el número completo de ninguna tarjeta, el documento del cliente ni su nombre, ni datos de otros clientes.
# AC-004-11 · Art. 7
def test_ac_004_11_foreign_and_missing_transactions_are_not_found() -> None:
    """AC-004-11: TX-P1 de C-0002 y TX-9999 lanzan TransactionNotFoundError con el cliente del almacén."""
    env = _env(transactions=[_tx(), _tx("TX-P1", card=OTHER_CARD)])
    messages = []

    for transaction_id, key in (("TX-P1", "K-1"), ("TX-9999", "K-2")):
        with pytest.raises(TransactionNotFoundError) as error:
            env.use_case.execute(_cmd(transaction_id=transaction_id, idempotency_key=key))
        messages.append(str(error.value))

    assert messages[0] == messages[1]
    assert env.transactions.customer_ids == ["C-0001", "C-0001"]
    assert env.disputes.disputes == []


# Regla: RN-004-03 — Una conversación sin verificación exitosa, desconocida o bloqueada por intentos agotados se rechaza con `IDENTITY_NOT_VERIFIED`. La verificación no se traslada: estar verificada en otra conversación no cuenta.
# Regla: RN-004-14 — Abrir una disputa no cambia el estado de verificación de la conversación.
# AC-004-12 · Art. 7
@pytest.mark.parametrize(
    "situation",
    ["nunca-verificada", "un-intento-fallido", "bloqueada", "verificada-en-otra"],
)
def test_ac_004_12_requires_verified_identity(situation: str) -> None:
    """AC-004-12: las 4 situaciones lanzan IdentityNotVerifiedError sin llamar a los repositorios."""
    store = SpyStore()
    if situation == "un-intento-fallido":
        store.with_failures("A", 1)
    elif situation == "bloqueada":
        store.with_failures("A", 3)
    elif situation == "verificada-en-otra":
        store.with_verified("A", "C-0001")
    conversation = "B" if situation == "verificada-en-otra" else "A"
    env = _env(store=store)
    state_before = env.store.get(conversation)

    with pytest.raises(IdentityNotVerifiedError):
        env.use_case.execute(_cmd(conversation_id=conversation))

    assert _repos_untouched(env)
    assert env.disputes.disputes == []
    assert env.store.get(conversation) == state_before
    assert env.store.saves == []


# Regla: RN-004-09 — `conversation_id` obligatorio y no vacío tras recortar; `transaction_id` obligatorio, de 1 a 64 caracteres tras recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar. Toda violación ⇒ `INVALID_INPUT`, sin disputa registrada.
# AC-004-13 · Art. 7
@pytest.mark.parametrize(
    "overrides",
    [
        {"transaction_id": None},
        {"transaction_id": ""},
        {"transaction_id": "   "},
        {"transaction_id": "T" * 65},
        {"idempotency_key": None},
        {"idempotency_key": ""},
        {"idempotency_key": "   "},
        {"idempotency_key": "K" * 65},
        {"conversation_id": None},
        {"conversation_id": ""},
        {"conversation_id": "   "},
    ],
    ids=[
        "tx-ausente",
        "tx-vacio",
        "tx-espacios",
        "tx-65",
        "key-ausente",
        "key-vacia",
        "key-espacios",
        "key-65",
        "conv-ausente",
        "conv-vacia",
        "conv-espacios",
    ],
)
def test_ac_004_13_rejects_invalid_request_data(overrides: dict[str, str | None]) -> None:
    """AC-004-13: datos inválidos lanzan InvalidInputError sin consultar almacén ni repositorios."""
    env = _env()
    command = OpenDisputeCommand(
        conversation_id=overrides.get("conversation_id", "A"),
        transaction_id=overrides.get("transaction_id", "TX-L1"),
        reason="UNRECOGNIZED_CHARGE",
        idempotency_key=overrides.get("idempotency_key", "K-1"),
    )

    with pytest.raises(InvalidInputError):
        env.use_case.execute(command)

    assert env.store.gets == []
    assert _repos_untouched(env)
    assert env.disputes.disputes == []


def _scenario_unverified_bad_reason() -> tuple[Env, OpenDisputeCommand, type[Exception]]:
    env = _env(verified=False)
    return env, _cmd(reason="FRAUD"), InvalidInputError


def _scenario_unverified_missing_tx() -> tuple[Env, OpenDisputeCommand, type[Exception]]:
    env = _env(verified=False)
    return env, _cmd(transaction_id="TX-9999"), IdentityNotVerifiedError


def _scenario_key_used_missing_tx() -> tuple[Env, OpenDisputeCommand, type[Exception]]:
    used = DisputeBuilder().with_conversation("A").with_key("K-1").with_transaction("TX-L1").build()
    env = _env(disputes=FakeDisputeRepository([used]))
    return env, _cmd(transaction_id="TX-9999", idempotency_key="K-1"), InvalidInputError


def _scenario_foreign_pending() -> tuple[Env, OpenDisputeCommand, type[Exception]]:
    env = _env(transactions=[_tx(), _tx("TX-P1", TransactionStatus.PENDING, card=OTHER_CARD)])
    return env, _cmd(transaction_id="TX-P1"), TransactionNotFoundError


def _scenario_pending_with_open_dispute() -> tuple[Env, OpenDisputeCommand, type[Exception]]:
    open_dispute = DisputeBuilder().with_transaction("TX-L1").with_key("K-0").build()
    env = _env(
        transactions=[_tx(status=TransactionStatus.PENDING)],
        disputes=FakeDisputeRepository([open_dispute]),
    )
    return env, _cmd(), TransactionNotDisputableError


# Regla: RN-004-10 — Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada; (2) identidad verificada; (3) clave de reintento; (4) transacción del cliente verificado; (5) transacción confirmada; (6) sin disputa abierta.
# AC-004-14 · Art. 7
@pytest.mark.parametrize(
    "scenario",
    [
        _scenario_unverified_bad_reason,
        _scenario_unverified_missing_tx,
        _scenario_key_used_missing_tx,
        _scenario_foreign_pending,
        _scenario_pending_with_open_dispute,
    ],
    ids=[
        "invalida-antes-que-identidad",
        "identidad-antes-que-transaccion",
        "clave-antes-que-transaccion",
        "pertenencia-antes-que-estado",
        "estado-antes-que-disputa-abierta",
    ],
)
def test_ac_004_14_checks_run_in_order(
    scenario: object,
) -> None:
    """AC-004-14: cada fila devuelve el primer resultado según el orden de RN-004-10."""
    env, command, expected = scenario()  # type: ignore[operator]
    before = env.disputes.disputes

    with pytest.raises(expected):
        env.use_case.execute(command)

    assert env.disputes.disputes == before


# Regla: RN-004-15 — Ante una falla inesperada (p. ej. el repositorio de disputas no responde al registrar), la herramienta devuelve `INTERNAL`, sin detalles internos. No queda ninguna disputa ni clave de reintento registrada: el registro es atómico.
# AC-004-16 · Art. 10
def test_ac_004_16_failure_on_add_leaves_nothing_registered() -> None:
    """AC-004-16: la falla de add da CoreUnavailableError sin detalle; tras repair() K-1 crea la disputa."""
    failing = FailingDisputeRepository()
    env = _env(disputes=failing)

    with pytest.raises(CoreUnavailableError) as error:
        env.use_case.execute(_cmd())

    assert "secreto" not in str(error.value)
    assert "detalle interno" not in str(error.value)
    assert failing.disputes == []

    failing.repair()
    result = env.use_case.execute(_cmd())

    assert result.replayed is False
    assert result.dispute.status is DisputeStatus.OPEN
    assert len(failing.disputes) == 1


def test_open_dispute_never_saves_to_store() -> None:
    """Soporte: el caso de uso nunca escribe en el almacén (RN-004-14)."""
    # Soporte de tests: el almacén de verificación es de solo lectura · Art. 3
    env = _env()
    env.use_case.execute(_cmd())
    assert env.store.saves == []


def test_dispute_type_is_exported() -> None:
    """Soporte: Dispute es el tipo devuelto por el caso de uso."""
    # Soporte de tests: tipo del resultado · Art. 3
    env = _env()
    assert isinstance(env.use_case.execute(_cmd()).dispute, Dispute)
