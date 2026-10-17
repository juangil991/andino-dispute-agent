"""Pruebas de los fakes de test y puertos de aplicación (habilitan AC-001-01..14)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.failing_customer_repository import FailingCustomerRepository
from tests.fakes.failing_transaction_repository import FailingTransactionRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_customer_repository import FakeCustomerRepository
from tests.fakes.fake_transaction_repository import FakeTransactionRepository
from tests.fakes.fake_verification_store import FakeVerificationStore
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder
from tests.fakes.transaction_builder import TransactionBuilder

from core_banking_mcp.application.errors import CardNotFoundError, IdentityNotVerifiedError
from core_banking_mcp.application.ports.audit_log import AuditEvent, AuditInput
from core_banking_mcp.application.ports.clock import Clock
from core_banking_mcp.application.ports.transaction_repository import TransactionRepository
from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.identity import IdentityRecord, VerificationState
from core_banking_mcp.domain.models.search import SearchCriteria
from core_banking_mcp.domain.models.transaction import CustomerCard, TransactionStatus


# Regla: RN-001-01 — varios criterios se combinan con AND; RN-001-11 — orden por customer_id.
# AC-001-01 · Art. 3 (soporte: el fake replica el filtro del repositorio real)
def test_fake_customer_repository_filters_with_and_and_orders_by_id() -> None:
    """Habilita AC-001-01..07: filtro AND normalizado, orden por customer_id y limit."""
    c3 = CustomerBuilder().with_id("C-003").with_name("María Pérez").with_document("AB-1").build()
    c1 = (
        CustomerBuilder()
        .with_id("C-001")
        .with_name("Maria Perez")
        .with_document("ab-1")
        .with_cards(Card("1234", CardStatus.CANCELLED))
        .build()
    )
    c2 = CustomerBuilder().with_id("C-002").with_name("Otro Nombre").with_document("ZZ-9").build()
    repo = FakeCustomerRepository([c3, c2, c1])

    by_name = repo.find_matching(SearchCriteria.create(None, "  MARIA   perez ", None), 10)
    assert [c.customer_id for c in by_name] == ["C-001", "C-003"]

    limited = repo.find_matching(SearchCriteria.create(None, "maria perez", None), 1)
    assert [c.customer_id for c in limited] == ["C-001"]

    both = repo.find_matching(SearchCriteria.create("AB-1", "maria perez", "1234"), 10)
    assert [c.customer_id for c in both] == ["C-001"]

    none = repo.find_matching(SearchCriteria.create("ZZ-9", "maria perez", None), 10)
    assert none == []


# Regla: RN-001-12 — la fecha y hora del registro de auditoría salen del reloj inyectado.
# AC-001-13 · Art. 3 (soporte: reloj determinista)
def test_fixed_clock_returns_given_instant() -> None:
    """Habilita AC-001-13: reloj inyectado determinista."""
    instant = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock: Clock = FixedClock(instant)
    assert clock.now() == instant


# Regla: RN-001-12 — cada invocación genera un registro de auditoría.
# AC-001-13 · Art. 8 (soporte: el log falso acumula los eventos)
def test_fake_audit_log_accumulates_events() -> None:
    """Habilita AC-001-13: el log falso acumula eventos."""
    log = FakeAuditLog()
    event = AuditEvent(
        conversation_id="conv-1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        tool="buscar_cliente",
        input=AuditInput(document="****1234", full_name=None, card_last4=None),
        outcome="FOUND",
        count=1,
        customer_ids=("C-001",),
        error_code=None,
        rule="RN-001-01",
        reason=None,
    )
    log.record(event)
    log.record(event)
    assert log.events == [event, event]


# Regla: RN-001-13 — una falla inesperada del repositorio no es un error de dominio.
# AC-001-14 · Art. 10 (soporte: el fake simula la caída del core)
def test_failing_customer_repository_raises_non_domain_error() -> None:
    """Habilita AC-001-14: falla inesperada que no es de dominio."""
    from core_banking_mcp.domain.errors import InvalidInputError

    repo = FailingCustomerRepository()
    with pytest.raises(RuntimeError) as exc:
        repo.find_matching(SearchCriteria.create("x", None, None), 6)
    assert not isinstance(exc.value, InvalidInputError)


# Soporte de tests: FakeVerificationStore (estado por conversación) · Art. 3
def test_fake_verification_store_unknown_conversation_is_not_verified() -> None:
    """Conversación desconocida => estado vacío; save aísla por conversación."""
    store = FakeVerificationStore()
    assert store.get("conv-x") == VerificationState()

    store.save("conv-a", VerificationState().with_failure())
    assert store.get("conv-a").failed_attempts == 1
    assert store.get("conv-b") == VerificationState()


# Soporte de tests: helpers Given de FakeVerificationStore · Art. 3
def test_fake_verification_store_helpers_build_given_states() -> None:
    """with_verified y with_failures preparan estados."""
    store = FakeVerificationStore()
    store.with_verified("conv-1", "C-001").with_failures("conv-2", 3)
    assert store.get("conv-1").is_verified_for("C-001")
    assert store.get("conv-2").is_locked


# Soporte de tests: IdentityBuilder y FakeCustomerRepository.find_identity · Art. 3
def test_identity_builder_and_fake_repository_find_identity() -> None:
    """Builder con fechas por defecto y find_identity del fake."""
    default = IdentityBuilder().build()
    assert default.document_issue_date >= default.birth_date
    custom = (
        IdentityBuilder()
        .with_birth_date(date(1990, 5, 17))
        .with_issue_date(date(2010, 6, 1))
        .build()
    )
    assert custom == IdentityRecord(date(1990, 5, 17), date(2010, 6, 1))

    repo = FakeCustomerRepository([], identities={"C-001": custom})
    assert repo.find_identity("C-001") == custom
    assert repo.find_identity("C-999") is None
    assert FakeCustomerRepository().find_identity("C-001") is None


# Soporte de tests: FailingCustomerRepository.find_identity · Art. 3
def test_failing_repository_find_identity_raises_runtime_error() -> None:
    """find_identity del repositorio fallido lanza RuntimeError."""
    with pytest.raises(RuntimeError):
        FailingCustomerRepository().find_identity("C-001")


# Soporte de tests: campos nuevos opcionales de AuditEvent · Art. 3
def test_audit_event_new_fields_are_optional() -> None:
    """AuditEvent sin customer_id/intento y con input=None."""
    event = AuditEvent(
        conversation_id=None,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        tool="verificar_identidad",
        input=None,
        outcome="VERIFIED",
        count=None,
        customer_ids=(),
        error_code=None,
        rule=None,
        reason=None,
    )
    assert event.customer_id is None
    assert event.intento is None


# Regla: RN-001-11 — resultado determinista (builder de datos ficticios reproducible).
# AC-001-01 · Art. 1 (soporte: datos de prueba ficticios y deterministas)
def test_customer_builder_is_deterministic() -> None:
    """Habilita AC-001-01..14: el builder genera clientes iguales en cada llamada."""
    assert CustomerBuilder().build() == CustomerBuilder().build()
    assert CustomerBuilder().with_id("C-9").build().customer_id == "C-9"


# Soporte de tests: FakeTransactionRepository filtra, ordena y limita como el real · Art. 3
def test_fake_transaction_repository_filters_by_customer_cards_and_interval() -> None:
    """find_customer_cards por cliente y last4; find_transactions por tarjetas e intervalo."""
    start = datetime(2026, 3, 1, tzinfo=UTC)
    end = datetime(2026, 4, 1, tzinfo=UTC)
    b = TransactionBuilder
    t_in_old = b().with_id("T-2").with_card("K-1", "1234").with_occurred_at(start).build()
    t_in_new_b = (
        b().with_id("T-4").with_card("K-1", "1234").with_occurred_at(end - timedelta(hours=1))
    )
    t_in_new_a = (
        b().with_id("T-3").with_card("K-2", "1234").with_occurred_at(end - timedelta(hours=1))
    )
    t_at_end = b().with_id("T-5").with_card("K-1", "1234").with_occurred_at(end).build()
    t_before = (
        b()
        .with_id("T-6")
        .with_card("K-1", "1234")
        .with_occurred_at(start - timedelta(seconds=1))
        .build()
    )
    t_other_card = b().with_id("T-7").with_card("K-9", "9999").with_occurred_at(start).build()
    repo: TransactionRepository = FakeTransactionRepository(
        cards={
            "C-0001": [CustomerCard("K-2", "1234"), CustomerCard("K-1", "1234")],
            "C-0002": [CustomerCard("K-9", "1234")],
        },
        transactions=[
            t_in_old,
            t_in_new_b.build(),
            t_in_new_a.build(),
            t_at_end,
            t_before,
            t_other_card,
        ],
    )

    assert repo.find_customer_cards("C-0001", "1234") == [
        CustomerCard("K-1", "1234"),
        CustomerCard("K-2", "1234"),
    ]
    assert repo.find_customer_cards("C-0001", "0000") == []
    assert repo.find_customer_cards("C-9999", "1234") == []

    found = repo.find_transactions(["K-1", "K-2"], start, end, 10)
    assert [t.transaction_id for t in found] == ["T-3", "T-4", "T-2"]
    limited = repo.find_transactions(["K-1", "K-2"], start, end, 2)
    assert [t.transaction_id for t in limited] == ["T-3", "T-4"]
    assert repo.find_transactions([], start, end, 10) == []


# Soporte de tests: FakeTransactionRepository registra si fue invocado · Art. 3
def test_fake_transaction_repository_records_invocation() -> None:
    """Permite comprobar que no se consulta antes de tiempo."""
    repo = FakeTransactionRepository()
    assert repo.called is False
    repo.find_customer_cards("C-0001", "1234")
    assert repo.called is True
    other = FakeTransactionRepository()
    other.find_transactions(
        [], datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC), 1
    )
    assert other.called is True


# Soporte de tests: TransactionBuilder válido, determinista y con setters · Art. 3
def test_transaction_builder_builds_valid_transaction_with_setters() -> None:
    """Builder por defecto válido y admite with_* de fecha, estado, importe, divisa, tarjeta, id."""
    assert TransactionBuilder().build() == TransactionBuilder().build()
    when = datetime(2026, 5, 5, 10, 0, tzinfo=UTC)
    tx = (
        TransactionBuilder()
        .with_id("T-77")
        .with_card("K-7", "4321")
        .with_occurred_at(when)
        .with_status(TransactionStatus.REVERSED)
        .with_amount(Decimal("12.50"))
        .with_currency("USD")
        .build()
    )
    assert tx.transaction_id == "T-77"
    assert (tx.card_id, tx.card_last4) == ("K-7", "4321")
    assert tx.occurred_at == when
    assert tx.status is TransactionStatus.REVERSED
    assert tx.amount == Decimal("12.50")
    assert tx.currency == "USD"


# Soporte de tests: FailingTransactionRepository simula la caída del core · Art. 3
@pytest.mark.parametrize("method", ["find_customer_cards", "find_transactions"])
def test_failing_transaction_repository_raises_runtime_error(method: str) -> None:
    """Ambos métodos lanzan RuntimeError."""
    repo = FailingTransactionRepository()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(RuntimeError):
        if method == "find_customer_cards":
            repo.find_customer_cards("C-0001", "1234")
        else:
            repo.find_transactions(["K-1"], start, start + timedelta(days=1), 5)


# Soporte de tests: errores de aplicación de 003 existen y son excepciones · Art. 3
def test_transaction_application_errors_exist() -> None:
    """IdentityNotVerifiedError y CardNotFoundError son Exception."""
    assert issubclass(IdentityNotVerifiedError, Exception)
    assert issubclass(CardNotFoundError, Exception)


# Soporte de tests: campos nuevos opcionales de AuditEvent para 003 · Art. 3
def test_audit_event_transaction_fields_default_to_empty() -> None:
    """AuditEvent sin masked_card/date_from/date_to/transaction_ids usa None / ()."""
    event = AuditEvent(
        conversation_id=None,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        tool="consultar_transacciones",
        input=None,
        outcome="OK",
        count=None,
        customer_ids=(),
        error_code=None,
        rule=None,
        reason=None,
    )
    assert event.masked_card is None
    assert event.date_from is None
    assert event.date_to is None
    assert event.transaction_ids == ()
