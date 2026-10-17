"""Pruebas de los fakes de test y puertos de aplicación (habilitan AC-001-01..14)."""

from datetime import UTC, datetime

import pytest
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.failing_customer_repository import FailingCustomerRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_customer_repository import FakeCustomerRepository
from tests.fakes.fixed_clock import FixedClock

from core_banking_mcp.application.ports.audit_log import AuditEvent, AuditInput
from core_banking_mcp.application.ports.clock import Clock
from core_banking_mcp.domain.models.customer import Card, CardStatus
from core_banking_mcp.domain.models.search import SearchCriteria


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


def test_fixed_clock_returns_given_instant() -> None:
    """Habilita AC-001-13: reloj inyectado determinista."""
    instant = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    clock: Clock = FixedClock(instant)
    assert clock.now() == instant


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


def test_failing_customer_repository_raises_non_domain_error() -> None:
    """Habilita AC-001-14: falla inesperada que no es de dominio."""
    from core_banking_mcp.domain.errors import InvalidInputError

    repo = FailingCustomerRepository()
    with pytest.raises(RuntimeError) as exc:
        repo.find_matching(SearchCriteria.create("x", None, None), 6)
    assert not isinstance(exc.value, InvalidInputError)


def test_customer_builder_is_deterministic() -> None:
    """Habilita AC-001-01..14: el builder genera clientes iguales en cada llamada."""
    assert CustomerBuilder().build() == CustomerBuilder().build()
    assert CustomerBuilder().with_id("C-9").build().customer_id == "C-9"
