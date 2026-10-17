from datetime import date

import pytest

from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.identity import (
    MAX_FAILED_ATTEMPTS,
    IdentityRecord,
    VerificationState,
)


# Regla: RN-002-04 — máximo 3 fallos por conversación; el 3.er fallo bloquea y
# `attempts_remaining` = 3 − fallos acumulados
# AC-002-05 · Art. 10 (ante la duda, escalar)
@pytest.mark.parametrize(
    ("failures", "remaining", "locked"),
    [
        pytest.param(0, 3, False, id="no_failures"),
        pytest.param(1, 2, False, id="one_failure"),
        pytest.param(2, 1, False, id="two_failures"),
        pytest.param(3, 0, True, id="three_failures_locks"),
    ],
)
def test_ac_002_05_state_attempts_remaining_and_lock_boundaries(
    failures: int, remaining: int, locked: bool
) -> None:
    """AC-002-05: tras 3 fallos el estado queda bloqueado."""
    state = VerificationState(failed_attempts=failures)
    assert MAX_FAILED_ATTEMPTS == 3
    assert state.attempts_remaining == remaining
    assert state.is_locked is locked


# Regla: RN-002-13 — una conversación sin verificación exitosa se considera no verificada
# AC-002-13 · Art. 7
def test_ac_002_13_empty_state_is_not_verified() -> None:
    """AC-002-13: una conversación desconocida no está verificada."""
    state = VerificationState()
    assert state.verified_customer_id is None
    assert state.failed_attempts == 0
    assert state.is_verified_for("C-001") is False


# Invariante: Art. 7 — with_failure suma un fallo y with_verified fija el cliente,
# devolviendo estados nuevos
# AC-002-05 · Art. 7
def test_with_failure_and_with_verified_return_new_states() -> None:
    """Invariante Art. 7: with_failure suma uno; with_verified fija el cliente."""
    state = VerificationState().with_failure()
    assert state.failed_attempts == 1
    verified = state.with_verified("C-001")
    assert verified.is_verified_for("C-001")
    assert not verified.is_verified_for("C-002")


# Invariante: Art. 7 — los fallos acumulados siempre están en 0..3
# AC-002-05 · Art. 7
@pytest.mark.parametrize(
    "failures", [pytest.param(-1, id="negative"), pytest.param(4, id="above_max")]
)
def test_ac_002_05_rejects_failed_attempts_out_of_range(failures: int) -> None:
    """Invariante Art. 7: failed_attempts fuera de 0-3 es inválido."""
    with pytest.raises(InvalidInputError):
        VerificationState(failed_attempts=failures)


# Invariante: Art. 7 — un estado no puede estar verificado y bloqueado a la vez
# AC-002-05 · Art. 7
def test_state_rejects_verified_and_locked_at_once() -> None:
    """Invariante Art. 7: no puede estar verificado y bloqueado a la vez."""
    with pytest.raises(InvalidInputError):
        VerificationState(verified_customer_id="C-001", failed_attempts=3)


# Regla: RN-002-07 — `document_issue_date` no anterior a `birth_date` (pueden ser iguales);
# toda violación ⇒ `INVALID_INPUT`
# AC-002-03 · Art. 7
def test_identity_record_rejects_issue_date_before_birth_date() -> None:
    """Invariante Art. 7: la expedición no puede ser anterior al nacimiento."""
    with pytest.raises(InvalidInputError):
        IdentityRecord(date(2000, 1, 2), date(2000, 1, 1))
    record = IdentityRecord(date(2000, 1, 1), date(2000, 1, 1))
    assert record.document_issue_date == date(2000, 1, 1)
