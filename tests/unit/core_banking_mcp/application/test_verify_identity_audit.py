"""Tests de auditoría del caso de uso VerifyIdentity (spec 002)."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

import pytest
from tests.fakes.failing_customer_repository import FailingCustomerRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_customer_repository import FakeCustomerRepository
from tests.fakes.fake_verification_store import FakeVerificationStore
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder

from core_banking_mcp.application.errors import CoreUnavailableError
from core_banking_mcp.application.ports.customer_repository import CustomerRepository
from core_banking_mcp.application.use_cases.verify_identity import (
    VerifyIdentity,
    VerifyIdentityCommand,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.identity import IdentityRecord

CONVERSATION = "conv-1"
LAURA_BIRTH = "1990-03-15"
LAURA_ISSUE = "2008-04-20"
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
DATE_VALUES = ("1990-03-15", "2008-04-20", "1990-03-16", "2008-04-21", "1985-07-02")


def _identities() -> dict[str, IdentityRecord]:
    return {
        "C-0001": IdentityBuilder()
        .with_birth_date(date(1990, 3, 15))
        .with_issue_date(date(2008, 4, 20))
        .build(),
        "C-0002": IdentityBuilder()
        .with_birth_date(date(1985, 7, 2))
        .with_issue_date(date(2003, 8, 10))
        .build(),
    }


def _command(
    customer_id: str | None = "C-0001",
    birth_date: str | None = LAURA_BIRTH,
    issue_date: str | None = LAURA_ISSUE,
    conversation_id: str | None = CONVERSATION,
) -> VerifyIdentityCommand:
    return VerifyIdentityCommand(conversation_id, customer_id, birth_date, issue_date)


@dataclass(frozen=True)
class Case:
    command: VerifyIdentityCommand
    store: FakeVerificationStore
    outcome: str
    rule: str
    error_code: str | None = None
    intento: int | None = None
    raises: type[Exception] | None = None
    failing_repository: bool = False


def _cases() -> dict[str, Callable[[], Case]]:
    return {
        "verified": lambda: Case(_command(), FakeVerificationStore(), "verified", "RN-002-02"),
        "already_verified": lambda: Case(
            _command(),
            FakeVerificationStore().with_verified(CONVERSATION, "C-0001"),
            "already_verified",
            "RN-002-11",
        ),
        "first_failure": lambda: Case(
            _command(birth_date="1990-03-16"),
            FakeVerificationStore(),
            "failed",
            "RN-002-03",
            intento=1,
        ),
        "third_failure_locks": lambda: Case(
            _command(birth_date="1990-03-16"),
            FakeVerificationStore().with_failures(CONVERSATION, 2),
            "locked",
            "RN-002-04",
        ),
        "already_locked": lambda: Case(
            _command(),
            FakeVerificationStore().with_failures(CONVERSATION, 3),
            "locked",
            "RN-002-05",
        ),
        "other_customer": lambda: Case(
            _command(customer_id="C-0002", birth_date="1985-07-02", issue_date="2003-08-10"),
            FakeVerificationStore().with_verified(CONVERSATION, "C-0001"),
            "other_customer",
            "RN-002-10",
        ),
        "invalid_input": lambda: Case(
            _command(birth_date="1990-03-16", issue_date="no-es-fecha"),
            FakeVerificationStore(),
            "error",
            "RN-002-07",
            error_code="INVALID_INPUT",
            raises=InvalidInputError,
        ),
        "unexpected_failure": lambda: Case(
            _command(),
            FakeVerificationStore(),
            "error",
            "RN-002-16",
            error_code="INTERNAL",
            raises=CoreUnavailableError,
            failing_repository=True,
        ),
    }


# Regla: RN-002-15 — cada invocación deja exactamente un registro sin fechas.
# AC-002-15 · Art. 8 (auditoría de cada invocación)
@pytest.mark.parametrize("name", list(_cases()), ids=list(_cases()))
def test_ac_002_15_each_invocation_records_exactly_one_event(name: str) -> None:
    """AC-002-15: un solo evento con conversación, reloj, resultado y sin fechas."""
    case = _cases()[name]()
    repository: CustomerRepository = (
        FailingCustomerRepository()
        if case.failing_repository
        else FakeCustomerRepository(identities=_identities())
    )
    audit = FakeAuditLog()
    use_case = VerifyIdentity(repository, case.store, audit, FixedClock(NOW))

    if case.raises is not None:
        with pytest.raises(case.raises):
            use_case.execute(case.command)
    else:
        use_case.execute(case.command)

    assert len(audit.events) == 1
    event = audit.events[0]
    assert event.conversation_id == CONVERSATION
    assert event.timestamp == NOW
    assert event.tool == "verificar_identidad"
    assert event.customer_id == case.command.customer_id
    assert event.input is None
    assert event.outcome == case.outcome
    assert event.error_code == case.error_code
    assert event.intento == case.intento
    assert event.rule == case.rule
    assert event.reason
    serialized = str(asdict(event))
    for value in (*DATE_VALUES, "no-es-fecha"):
        assert value not in serialized


# Regla: RN-002-15 — sin conversation_id se registra un identificador vacío.
# AC-002-15 · Art. 8 (auditoría de cada invocación)
def test_ac_002_15_missing_conversation_id_records_empty_conversation() -> None:
    """AC-002-15: conversation_id ausente se registra como cadena vacía."""
    audit = FakeAuditLog()
    use_case = VerifyIdentity(
        FakeCustomerRepository(identities=_identities()),
        FakeVerificationStore(),
        audit,
        FixedClock(NOW),
    )

    with pytest.raises(InvalidInputError):
        use_case.execute(_command(conversation_id=None))

    assert len(audit.events) == 1
    assert audit.events[0].conversation_id == ""
    assert audit.events[0].error_code == "INVALID_INPUT"
