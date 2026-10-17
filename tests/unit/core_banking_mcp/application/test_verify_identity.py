"""Tests del caso de uso VerifyIdentity (spec 002)."""

from dataclasses import fields
from datetime import UTC, date, datetime

import pytest
from tests.fakes.failing_customer_repository import FailingCustomerRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_customer_repository import FakeCustomerRepository
from tests.fakes.fake_verification_store import FakeVerificationStore
from tests.fakes.fixed_clock import FixedClock
from tests.fakes.identity_builder import IdentityBuilder

from core_banking_mcp.application.errors import CoreUnavailableError
from core_banking_mcp.application.use_cases.verify_identity import (
    VerificationResult,
    VerifyIdentity,
    VerifyIdentityCommand,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.identity import IdentityRecord, VerificationState

CONVERSATION = "conv-1"
LAURA_BIRTH = "1990-03-15"
LAURA_ISSUE = "2008-04-20"
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)


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


def _build(
    store: FakeVerificationStore | None = None,
    now: datetime = NOW,
) -> tuple[VerifyIdentity, FakeVerificationStore]:
    store = store or FakeVerificationStore()
    use_case = VerifyIdentity(
        FakeCustomerRepository(identities=_identities()),
        store,
        FakeAuditLog(),
        FixedClock(now),
    )
    return use_case, store


def _command(
    customer_id: str | None = "C-0001",
    birth_date: str | None = LAURA_BIRTH,
    issue_date: str | None = LAURA_ISSUE,
    conversation_id: str | None = CONVERSATION,
) -> VerifyIdentityCommand:
    return VerifyIdentityCommand(conversation_id, customer_id, birth_date, issue_date)


def _wrong() -> VerifyIdentityCommand:
    return _command(birth_date="1990-03-16")


# Regla: RN-002-02 — ambas fechas correctas verifican al cliente.
# AC-002-01 · Art. 7
def test_ac_002_01_correct_dates_verify_and_store_customer() -> None:
    """AC-002-01: fechas correctas verifican y el almacén indica C-0001."""
    use_case, store = _build()

    result = use_case.execute(_command())

    assert result == VerificationResult(True, 3, False)
    assert store.get(CONVERSATION).verified_customer_id == "C-0001"


# Regla: RN-002-05 — fechas correctas verifican aunque haya fallos previos.
# AC-002-06 · Art. 7
def test_ac_002_06_correct_dates_after_two_failures_verify() -> None:
    """AC-002-06: con 2 fallos, fechas correctas verifican con 1 restante."""
    use_case, store = _build(FakeVerificationStore().with_failures(CONVERSATION, 2))

    result = use_case.execute(_command())

    assert result == VerificationResult(True, 1, False)
    assert store.get(CONVERSATION).verified_customer_id == "C-0001"


# Regla: RN-002-05 — conversación bloqueada no verifica ni con fechas correctas.
# AC-002-07 · Art. 10 (escalar al agotar intentos)
def test_ac_002_07_locked_conversation_rejects_correct_dates() -> None:
    """AC-002-07: bloqueada responde falso, 0 restantes y escalamiento."""
    use_case, store = _build(FakeVerificationStore().with_failures(CONVERSATION, 3))

    result = use_case.execute(_command())

    assert result == VerificationResult(False, 0, True)
    assert store.get(CONVERSATION).verified_customer_id is None


# Regla: RN-002-02 — basta una fecha incorrecta para no verificar.
# AC-002-02 · Art. 7
@pytest.mark.parametrize(
    ("birth", "issue"),
    [
        ("1990-03-16", "2008-04-20"),
        ("1990-03-15", "2008-04-21"),
        ("1990-03-16", "2008-04-21"),
    ],
    ids=["birth_wrong", "issue_wrong", "both_wrong"],
)
def test_ac_002_02_one_wrong_date_does_not_verify(birth: str, issue: str) -> None:
    """AC-002-02: fecha incorrecta devuelve falso, 2 restantes y no verifica."""
    use_case, store = _build()

    result = use_case.execute(_command(birth_date=birth, issue_date=issue))

    assert result == VerificationResult(False, 2, False)
    assert store.get(CONVERSATION).verified_customer_id is None


# Regla: RN-002-03 — cliente inexistente responde igual que fechas incorrectas.
# AC-002-04 · Art. 7
def test_ac_002_04_unknown_customer_answers_like_wrong_dates() -> None:
    """AC-002-04: C-9999 responde idéntico a fechas incorrectas y cuenta un fallo."""
    wrong_dates, _ = _build()
    unknown, store = _build()

    expected = wrong_dates.execute(_wrong())
    result = unknown.execute(_command(customer_id="C-9999"))

    assert result == expected == VerificationResult(False, 2, False)
    assert store.get(CONVERSATION) == VerificationState(None, 1)


# Regla: RN-002-10 — una conversación verifica un solo cliente.
# AC-002-11 · Art. 7
@pytest.mark.parametrize(
    ("customer", "birth", "issue"),
    [
        ("C-0002", "1985-07-02", "2003-08-10"),
        ("C-0002", "1985-07-03", "2003-08-10"),
        ("C-9999", LAURA_BIRTH, LAURA_ISSUE),
    ],
    ids=["other_correct", "other_wrong", "unknown"],
)
def test_ac_002_11_other_customer_is_rejected_without_changes(
    customer: str, birth: str, issue: str
) -> None:
    """AC-002-11: otro cliente no verifica, no cuenta intento ni cambia el verificado."""
    use_case, store = _build(FakeVerificationStore().with_verified(CONVERSATION, "C-0001"))

    result = use_case.execute(_command(customer_id=customer, birth_date=birth, issue_date=issue))

    assert result == VerificationResult(False, 3, False)
    assert store.get(CONVERSATION) == VerificationState("C-0001", 0)


# Regla: RN-002-11 — re-verificar al mismo cliente es idempotente y no consulta.
# AC-002-12 · Art. 7
@pytest.mark.parametrize(
    "birth",
    [LAURA_BIRTH, "1990-03-16"],
    ids=["correct", "wrong"],
)
def test_ac_002_12_same_customer_is_idempotent_without_repository(birth: str) -> None:
    """AC-002-12: ya verificada responde verdadero sin consultar identidades."""
    store = FakeVerificationStore().with_verified(CONVERSATION, "C-0001")
    use_case = VerifyIdentity(FailingCustomerRepository(), store, FakeAuditLog(), FixedClock(NOW))

    result = use_case.execute(_command(birth_date=birth))

    assert result == VerificationResult(True, 3, False)
    assert store.get(CONVERSATION) == VerificationState("C-0001", 0)


# Regla: RN-002-12 — la verificación pertenece a su conversación.
# AC-002-13 · Art. 7
def test_ac_002_13_verification_is_per_conversation() -> None:
    """AC-002-13: A verificada; B sin estado y con su propio contador."""
    use_case, store = _build(FakeVerificationStore().with_verified("A", "C-0001"))

    assert store.get("B").verified_customer_id is None
    result = use_case.execute(_command(birth_date="1990-03-16", conversation_id="B"))

    assert result == VerificationResult(False, 2, False)
    assert store.get("A").verified_customer_id == "C-0001"


_INVALID = [
    _command(birth_date=""),
    _command(issue_date=""),
    _command(birth_date=None),
    _command(issue_date=None),
    _command(birth_date="1990-02-31"),
    _command(issue_date="2008-02-31"),
    _command(birth_date="15/03/1990"),
    _command(birth_date="2026-10-18"),
    _command(issue_date="2026-10-18"),
    _command(birth_date="1990-03-15", issue_date="1990-03-14"),
    _command(customer_id=None),
    _command(customer_id=""),
    _command(customer_id="   "),
    _command(customer_id="C" * 33),
    _command(conversation_id=None),
    _command(conversation_id=""),
    _command(conversation_id="   "),
]
_INVALID_IDS = [
    "birth_empty",
    "issue_empty",
    "birth_none",
    "issue_none",
    "birth_nonexistent",
    "issue_nonexistent",
    "birth_format",
    "birth_future",
    "issue_future",
    "issue_before_birth",
    "customer_none",
    "customer_empty",
    "customer_blank",
    "customer_too_long",
    "conversation_none",
    "conversation_empty",
    "conversation_blank",
]


# Regla: RN-002-07 — toda entrada inválida es INVALID_INPUT sin tocar el estado.
# AC-002-08 · Art. 7
@pytest.mark.parametrize("command", _INVALID, ids=_INVALID_IDS)
def test_ac_002_08_invalid_input_raises_without_state_change(
    command: VerifyIdentityCommand,
) -> None:
    """AC-002-08: entrada inválida lanza InvalidInputError sin estado ni consulta."""
    store = FakeVerificationStore()
    use_case = VerifyIdentity(FailingCustomerRepository(), store, FakeAuditLog(), FixedClock(NOW))

    with pytest.raises(InvalidInputError):
        use_case.execute(command)

    assert store.get(CONVERSATION) == VerificationState()


# Regla: RN-002-07 — fechas intercambiadas (expedición anterior al nacimiento) son inválidas.
# AC-002-03 · Art. 7
def test_ac_002_03_swapped_dates_are_invalid_input() -> None:
    """AC-002-03: fechas intercambiadas lanzan InvalidInputError sin intentos."""
    use_case, store = _build()

    with pytest.raises(InvalidInputError):
        use_case.execute(_command(birth_date=LAURA_ISSUE, issue_date=LAURA_BIRTH))

    assert store.get(CONVERSATION) == VerificationState()


# Regla: RN-002-08 — "hoy" es la fecha en America/Bogota (bordes de zona horaria).
# AC-002-09 · Art. 7
@pytest.mark.parametrize(
    ("instant", "issue", "valid"),
    [
        (datetime(2026, 10, 17, 15, 0, tzinfo=UTC), "2026-10-17", True),
        (datetime(2026, 10, 18, 3, 0, tzinfo=UTC), "2026-10-18", False),
        (datetime(2026, 10, 18, 5, 0, tzinfo=UTC), "2026-10-18", True),
        (datetime(2026, 10, 17, 15, 0, tzinfo=UTC), "1990-03-15", True),
    ],
    ids=["today_bogota", "still_17_in_bogota", "already_18_in_bogota", "issue_equals_birth"],
)
def test_ac_002_09_today_uses_bogota_timezone(instant: datetime, issue: str, valid: bool) -> None:
    """AC-002-09: los límites de fecha usan el día de Bogotá del reloj inyectado."""
    use_case, _ = _build(now=instant)
    command = _command(customer_id="C-9999", issue_date=issue)

    if valid:
        assert use_case.execute(command) == VerificationResult(False, 2, False)
    else:
        with pytest.raises(InvalidInputError):
            use_case.execute(command)


# Regla: RN-002-04 y RN-002-07 — los datos inválidos no consumen intentos.
# AC-002-10 · Art. 7
def test_ac_002_10_invalid_input_does_not_consume_attempts() -> None:
    """AC-002-10: con 2 fallos, un dato inválido no bloquea y luego verifica."""
    use_case, _ = _build(FakeVerificationStore().with_failures(CONVERSATION, 2))

    with pytest.raises(InvalidInputError):
        use_case.execute(_command(birth_date="1990-02-31"))
    result = use_case.execute(_command())

    assert result.verified is True


# Regla: RN-002-14 — la respuesta contiene solo tres campos.
# AC-002-14 · Art. 7
def test_ac_002_14_result_has_only_three_fields() -> None:
    """AC-002-14: VerificationResult expone solo verified, attempts_remaining, escalation."""
    use_case, _ = _build()

    result = use_case.execute(_command())

    assert [f.name for f in fields(result)] == [
        "verified",
        "attempts_remaining",
        "escalation_required",
    ]


# Regla: RN-002-16 — falla inesperada es CoreUnavailableError sin cambiar el estado.
# AC-002-16 · Art. 10 (falla no recuperable)
def test_ac_002_16_unexpected_failure_raises_core_unavailable() -> None:
    """AC-002-16: falla del repositorio se oculta y no altera el estado."""
    store = FakeVerificationStore()
    use_case = VerifyIdentity(FailingCustomerRepository(), store, FakeAuditLog(), FixedClock(NOW))

    with pytest.raises(CoreUnavailableError) as raised:
        use_case.execute(_command())

    assert "secreto" not in str(raised.value)
    assert "fallo simulado" not in str(raised.value)
    assert store.get(CONVERSATION) == VerificationState()
