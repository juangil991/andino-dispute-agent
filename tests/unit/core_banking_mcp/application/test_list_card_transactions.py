"""Tests del caso de uso ListCardTransactions (spec 003)."""

# ruff: noqa: E501  (los enunciados de RN de la trazabilidad se citan en una sola línea)

from datetime import UTC, datetime, timedelta, timezone

import pytest
from tests.fakes.failing_transaction_repository import FailingTransactionRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_transaction_repository import FakeTransactionRepository
from tests.fakes.fake_verification_store import FakeVerificationStore
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.errors import (
    CardNotFoundError,
    CoreUnavailableError,
    IdentityNotVerifiedError,
)
from core_banking_mcp.application.use_cases.list_card_transactions import (
    ListCardTransactions,
    ListCardTransactionsCommand,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.domain.models.transaction import (
    CustomerCard,
    Transaction,
    TransactionStatus,
)

CONVERSATION = "conv-1"
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
BOGOTA = timezone(timedelta(hours=-5))
CARD = CustomerCard("K-0001", "4321")


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


def _tx(
    transaction_id: str = "T-0001",
    day: int = 10,
    card: CustomerCard = CARD,
    month: int = 9,
    status: TransactionStatus = TransactionStatus.CONFIRMED,
    hour: int = 10,
) -> Transaction:
    return (
        TransactionBuilder()
        .with_id(transaction_id)
        .with_card(card.card_id, card.last4)
        .with_occurred_at(datetime(2026, month, day, hour, 0, tzinfo=BOGOTA))
        .with_status(status)
        .build()
    )


def _store(verified: bool = True) -> SpyStore:
    store = SpyStore()
    if verified:
        store.with_verified(CONVERSATION, "C-0001")
    return store


def _build(
    transactions: list[Transaction] | None = None,
    cards: dict[str, list[CustomerCard]] | None = None,
    store: SpyStore | None = None,
    now: datetime = NOW,
) -> tuple[ListCardTransactions, FakeTransactionRepository, SpyStore]:
    repository = FakeTransactionRepository(
        cards if cards is not None else {"C-0001": [CARD]}, transactions or []
    )
    store = store if store is not None else _store()
    use_case = ListCardTransactions(repository, store, FakeAuditLog(), FixedClock(now))
    return use_case, repository, store


def _command(
    card_last4: str | None = "4321",
    date_from: str | None = "2026-09-01",
    date_to: str | None = "2026-09-30",
    conversation_id: str | None = CONVERSATION,
) -> ListCardTransactionsCommand:
    return ListCardTransactionsCommand(conversation_id, card_last4, date_from, date_to)


# Regla: RN-003-01 — La solicitud indica la tarjeta por sus últimos 4 dígitos (`card_last4`) y el rango con `date_from` y `date_to` en formato ISO `AAAA-MM-DD`, ambos incluidos.
# Regla: RN-003-05 — Cada transacción tiene un instante `occurred_at` (fecha y hora con zona). Entra en el rango si su **fecha local en `America/Bogota`** está entre `date_from` y `date_to`, ambos incluidos.
# Regla: RN-003-11 — Las transacciones se ordenan de la más reciente a la más antigua por `occurred_at`; si dos tienen el mismo instante, por `transaction_id` ascendente (resultado determinista).
# Regla: RN-003-12 — Cada transacción devuelta contiene **solo**: `transaction_id`, `occurred_at`, `merchant`, `amount`, `currency`, `status`, `card_id` y `masked_card`.
# AC-003-01 · Art. 7
def test_ac_003_01_lists_range_transactions_newest_first() -> None:
    """AC-003-01: devuelve las 3 de septiembre en orden 20, 12, 5 y no la de octubre."""
    use_case, _, _ = _build(
        [
            _tx("T-05", day=5),
            _tx("T-12", day=12),
            _tx("T-20", day=20),
            _tx("T-OCT", day=2, month=10),
        ]
    )

    result = use_case.execute(_command())

    assert [t.transaction_id for t in result.transactions] == ["T-20", "T-12", "T-05"]
    assert result.refinement_required is False


# Regla: RN-003-09 — Se devuelven transacciones en cualquier estado: confirmada (`CONFIRMED`), pendiente (`PENDING`) o reversada (`REVERSED`).
# AC-003-03 · Art. 7
@pytest.mark.parametrize("status", list(TransactionStatus), ids=lambda s: s.value)
def test_ac_003_03_lists_transactions_in_any_status(status: TransactionStatus) -> None:
    """AC-003-03: la transacción aparece con su estado y su monto original."""
    use_case, _, _ = _build([_tx(status=status)])

    result = use_case.execute(_command())

    assert [t.status for t in result.transactions] == [status]
    assert str(result.transactions[0].amount) == "100.00"


# Regla: RN-003-03 — Se consultan **todas** las tarjetas del cliente verificado en la conversación que terminan en `card_last4`, **sea cual sea su estado** (activa, bloqueada, cancelada); sus transacciones se devuelven juntas en una sola lista.
# Regla: RN-003-12 — Cada transacción devuelta contiene **solo**: `transaction_id`, `occurred_at`, `merchant`, `amount`, `currency`, `status`, `card_id` y `masked_card`.
# AC-003-05 · Art. 7
def test_ac_003_05_two_cards_with_same_last4_return_both_transactions() -> None:
    """AC-003-05: dos tarjetas 4321 devuelven 2 transacciones con card_id distintos."""
    other = CustomerCard("K-0002", "4321")
    use_case, _, _ = _build(
        [_tx("T-1", card=CARD), _tx("T-2", card=other)],
        cards={"C-0001": [CARD, other]},
    )

    result = use_case.execute(_command())

    assert len(result.transactions) == 2
    assert {t.card_id for t in result.transactions} == {"K-0001", "K-0002"}
    assert all(t.card_last4 == "4321" for t in result.transactions)


# Regla: RN-003-10 — Tope de 50 transacciones. Sin transacciones en el rango, la respuesta es exitosa con lista vacía y `refinement_required = false`.
# AC-003-06 · Art. 7
def test_ac_003_06_no_transactions_in_range_is_empty_success() -> None:
    """AC-003-06: sin transacciones, lista vacía y sin refinar."""
    use_case, _, _ = _build([])

    result = use_case.execute(_command())

    assert result.transactions == ()
    assert result.refinement_required is False


# Regla: RN-003-06 — Validación de entrada: el rango no supera **90 días contando ambos extremos** (`date_to − date_from + 1 ≤ 90`). No hay límite hacia el pasado para `date_from`.
# AC-003-07 · Art. 7
@pytest.mark.parametrize(
    ("date_from", "date_to", "valid"),
    [
        ("2026-09-10", "2026-09-10", True),
        ("2026-06-01", "2026-08-28", True),
        ("2026-06-01", "2026-08-29", True),
        ("2026-06-01", "2026-08-30", False),
        ("2019-01-01", "2019-01-31", True),
    ],
    ids=["1-dia", "89-dias", "90-dias", "91-dias", "pasado-sin-limite"],
)
def test_ac_003_07_range_is_limited_to_90_days(date_from: str, date_to: str, valid: bool) -> None:
    """AC-003-07: 90 días pasan; 91 son INVALID_INPUT sin consultar nada."""
    use_case, repository, store = _build([])
    command = _command(date_from=date_from, date_to=date_to)

    if valid:
        assert use_case.execute(command).refinement_required is False
        return
    with pytest.raises(InvalidInputError):
        use_case.execute(command)
    assert repository.called is False
    assert store.gets == []


# Regla: RN-003-10 — Con 1 a 50 se devuelven todas con `refinement_required = false`. Con más de 50, la respuesta es exitosa, **sin ninguna transacción** y con `refinement_required = true` para que se acote el rango.
# AC-003-08 · Art. 7
@pytest.mark.parametrize(
    ("count", "returned", "flag"),
    [(49, 49, False), (50, 50, False), (51, 0, True)],
    ids=["49", "50", "51"],
)
def test_ac_003_08_caps_results_at_50(count: int, returned: int, flag: bool) -> None:
    """AC-003-08: con 51 se devuelve vacío y refinement_required."""
    transactions = [_tx(f"T-{i:03d}", day=1 + i % 28, hour=i % 24) for i in range(count)]
    use_case, repository, _ = _build(transactions)
    limits: list[int] = []
    original = repository.find_transactions

    def spy(card_ids: list[str], start: datetime, end: datetime, limit: int) -> list[Transaction]:
        limits.append(limit)
        return original(card_ids, start, end, limit)

    repository.find_transactions = spy  # type: ignore[method-assign]

    result = use_case.execute(_command())

    assert limits == [51]
    assert len(result.transactions) == returned
    assert result.refinement_required is flag


_INVALID = [
    {"date_from": ""},
    {"date_to": ""},
    {"date_from": None},
    {"date_to": None},
    {"date_to": "2026-09-31"},
    {"date_from": "01/09/2026"},
    {"date_from": "2026-09-30", "date_to": "2026-09-01"},
    {"date_from": "2026-10-01", "date_to": "2026-10-18"},
    {"card_last4": None},
    {"card_last4": "432"},
    {"card_last4": "54321"},
    {"card_last4": "43a1"},
    {"conversation_id": None},
    {"conversation_id": ""},
    {"conversation_id": "   "},
]
_INVALID_IDS = [
    "from-vacio",
    "to-vacio",
    "from-nulo",
    "to-nulo",
    "to-inexistente",
    "from-formato",
    "from-posterior",
    "to-futuro",
    "last4-nulo",
    "last4-3-digitos",
    "last4-5-digitos",
    "last4-letras",
    "conversation-nula",
    "conversation-vacia",
    "conversation-espacios",
]


# Regla: RN-003-06 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_last4` obligatorio, exactamente 4 dígitos `0-9`, sin espacios; `date_from` y `date_to` obligatorias, en formato `AAAA-MM-DD` y existentes en el calendario; `date_from` no posterior a `date_to`; `date_to` no posterior a hoy; el rango no supera **90 días contando ambos extremos**. Toda violación ⇒ `INVALID_INPUT`, sin transacciones.
# AC-003-09 · Art. 7
@pytest.mark.parametrize("override", _INVALID, ids=_INVALID_IDS)
def test_ac_003_09_invalid_input_raises_without_querying(override: dict[str, str | None]) -> None:
    """AC-003-09: INVALID_INPUT sin consultar el almacén ni el repositorio."""
    use_case, repository, store = _build([_tx()])
    fields: dict[str, str | None] = {
        "card_last4": "4321",
        "date_from": "2026-09-01",
        "date_to": "2026-09-30",
        "conversation_id": CONVERSATION,
    }
    fields.update(override)

    with pytest.raises(InvalidInputError):
        use_case.execute(ListCardTransactionsCommand(**fields))

    assert repository.called is False
    assert store.gets == []


# Regla: RN-003-06 — Validación de entrada: `date_to` no posterior a hoy.
# Regla: RN-003-07 — "Hoy" es la fecha del reloj inyectado en la zona horaria `America/Bogota` (UTC−05:00), igual que RN-002-08.
# AC-003-10 · Art. 7
@pytest.mark.parametrize(
    ("instant", "date_to", "valid"),
    [
        (datetime(2026, 10, 17, 15, 0, tzinfo=UTC), "2026-10-17", True),
        (datetime(2026, 10, 18, 3, 0, tzinfo=UTC), "2026-10-18", False),
        (datetime(2026, 10, 18, 5, 0, tzinfo=UTC), "2026-10-18", True),
    ],
    ids=["hoy-bogota", "aun-17-en-bogota", "ya-18-en-bogota"],
)
def test_ac_003_10_today_is_computed_in_bogota(
    instant: datetime, date_to: str, valid: bool
) -> None:
    """AC-003-10: 'hoy' sale del reloj inyectado en America/Bogota."""
    use_case, _, _ = _build([], now=instant)
    command = _command(date_from="2026-10-01", date_to=date_to)

    if valid:
        assert use_case.execute(command).transactions == ()
        return
    with pytest.raises(InvalidInputError):
        use_case.execute(command)


def _unverified_stores() -> dict[str, SpyStore]:
    locked = SpyStore().with_failures(CONVERSATION, 3)  # type: ignore[assignment]
    other = SpyStore().with_verified("conv-A", "C-0001")  # type: ignore[assignment]
    failed = SpyStore().with_failures(CONVERSATION, 1)  # type: ignore[assignment]
    return {"nunca-verificada": SpyStore(), "1-fallo": failed, "bloqueada": locked, "otra": other}


# Regla: RN-003-02 — La herramienta exige que la conversación esté verificada en el servidor. Una conversación sin verificación exitosa, desconocida o bloqueada por intentos agotados se rechaza con `IDENTITY_NOT_VERIFIED`. La verificación no se traslada: estar verificada en otra conversación no cuenta.
# Regla: RN-003-14 — La herramienta es de solo lectura: no modifica transacciones, tarjetas ni el estado de verificación de la conversación (cliente verificado e intentos fallidos).
# Invariante: Art. 7 — Ninguna herramienta que devuelva datos de un cliente se invoca antes de que `verificar_identidad` haya tenido éxito en la conversación; el servidor también lo valida.
# AC-003-11 · Art. 7
@pytest.mark.parametrize("situation", list(_unverified_stores()), ids=lambda s: s)
def test_ac_003_11_unverified_conversation_is_rejected(situation: str) -> None:
    """AC-003-11: sin identidad verificada no hay datos, y el almacén no cambia."""
    store = _unverified_stores()[situation]
    before = store.get(CONVERSATION)
    store.gets.clear()
    use_case, repository, _ = _build([_tx()], store=store)

    with pytest.raises(IdentityNotVerifiedError):
        use_case.execute(_command())

    assert repository.called is False
    assert store.saves == []
    assert store.get(CONVERSATION) == before


# Regla: RN-003-08 — Las comprobaciones se evalúan en este orden y se devuelve el primer error: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) tarjeta del cliente verificado → `NOT_FOUND`.
# AC-003-12 · Art. 7
@pytest.mark.parametrize(
    ("verified", "override", "expected"),
    [
        (False, {"card_last4": "43a1"}, InvalidInputError),
        (False, {"card_last4": "0000"}, IdentityNotVerifiedError),
        (True, {"card_last4": "0000", "date_to": "2026-10-18"}, InvalidInputError),
    ],
    ids=["no-verificada-y-invalida", "no-verificada-y-no-existe", "verificada-y-fecha-futura"],
)
def test_ac_003_12_checks_run_in_documented_order(
    verified: bool, override: dict[str, str], expected: type[Exception]
) -> None:
    """AC-003-12: se devuelve el primer error según RN-003-08."""
    use_case, _, _ = _build([_tx()], store=_store(verified))
    fields = {"card_last4": "4321", "date_from": "2026-09-01", "date_to": "2026-09-30"}
    fields.update(override)

    with pytest.raises(expected):
        use_case.execute(_command(**fields))


# Regla: RN-003-04 — Si el cliente verificado no tiene ninguna tarjeta terminada en `card_last4` (porque la tarjeta es de otro cliente o porque no existe), se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en ambos casos, sin datos de ningún cliente.
# Regla: RN-003-13 — La respuesta nunca contiene el número completo de ninguna tarjeta, el documento del cliente ni su nombre, ni datos de otros clientes.
# AC-003-13 · Art. 7
def test_ac_003_13_foreign_and_missing_card_raise_the_same_error() -> None:
    """AC-003-13: tarjeta de C-0002 y 0000 lanzan CardNotFoundError idéntico."""
    foreign = CustomerCard("K-0002", "8765")
    use_case, _, _ = _build(
        [_tx("T-X", card=foreign)],
        cards={"C-0001": [CARD], "C-0002": [foreign]},
    )

    errors = []
    for last4 in ("8765", "0000"):
        with pytest.raises(CardNotFoundError) as info:
            use_case.execute(_command(card_last4=last4))
        errors.append(info.value)

    assert type(errors[0]) is type(errors[1])
    assert str(errors[0]) == str(errors[1])
    assert "8765" not in str(errors[0])


# Regla: RN-003-04 — Si el cliente verificado no tiene ninguna tarjeta terminada en `card_last4` (porque la tarjeta es de otro cliente o porque no existe), se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en ambos casos, sin datos de ningún cliente.
# AC-003-13 · Art. 7
def test_ac_003_13_cards_are_looked_up_with_the_verified_customer() -> None:
    """AC-003-13: el repositorio se consulta con el customer_id del almacén."""
    foreign = CustomerCard("K-0002", "8765")
    store = SpyStore().with_verified(CONVERSATION, "C-0002")  # type: ignore[assignment]
    use_case, _, _ = _build(
        [_tx("T-X", card=foreign)],
        cards={"C-0001": [CARD], "C-0002": [foreign]},
        store=store,
    )

    assert len(use_case.execute(_command(card_last4="8765")).transactions) == 1
    with pytest.raises(CardNotFoundError):
        use_case.execute(_command(card_last4="4321"))


# Regla: RN-003-11 — Las transacciones se ordenan de la más reciente a la más antigua por `occurred_at`; si dos tienen el mismo instante, por `transaction_id` ascendente (resultado determinista).
# AC-003-15 · Art. 7
def test_ac_003_15_repository_order_is_preserved_for_simultaneous_transactions() -> None:
    """AC-003-15: primero la del 16, luego las del 15 por transaction_id ascendente."""
    use_case, _, _ = _build([_tx("T-B", day=15), _tx("T-A", day=15), _tx("T-C", day=16)])

    result = use_case.execute(_command())

    assert [t.transaction_id for t in result.transactions] == ["T-C", "T-A", "T-B"]


# Regla: RN-003-16 — Ante una falla inesperada (p. ej. el repositorio de transacciones no responde), la herramienta devuelve `INTERNAL` con `retryable = false`, sin transacciones ni detalles internos (trazas, SQL, texto de la excepción).
# AC-003-18 · Art. 10
def test_ac_003_18_unexpected_failure_becomes_core_unavailable() -> None:
    """AC-003-18: la falla del repositorio no filtra el texto original."""
    use_case = ListCardTransactions(
        FailingTransactionRepository(), _store(), FakeAuditLog(), FixedClock(NOW)
    )

    with pytest.raises(CoreUnavailableError) as info:
        use_case.execute(_command())

    assert "secreto" not in str(info.value)
    assert "fallo simulado" not in str(info.value)
