"""Tests de la decisión pura de verificación de identidad."""

from __future__ import annotations

from datetime import date

import pytest

from core_banking_mcp.domain.identity_verification import (
    VerificationDecision,
    VerificationOutcome,
    evaluate_verification,
)
from core_banking_mcp.domain.models.identity import (
    IdentityRecord,
    VerificationRequest,
    VerificationState,
)

TODAY = date(2026, 10, 17)
BIRTH = "1985-03-12"
ISSUE = "2005-04-20"
IDENTITY = IdentityRecord(date(1985, 3, 12), date(2005, 4, 20))


def _request(
    birth: str = BIRTH, issue: str = ISSUE, customer_id: str = "C-0001"
) -> VerificationRequest:
    return VerificationRequest.create("conv-1", customer_id, birth, issue, TODAY)


# Regla: RN-002-03 — la respuesta no distingue cuál dato falló.
# AC-002-02 · Art. 7 (sin identificación no hay datos del cliente)
@pytest.mark.parametrize(
    ("birth", "issue"),
    [
        pytest.param("1985-03-13", ISSUE, id="wrong_birth_date"),
        pytest.param(BIRTH, "2005-04-21", id="wrong_issue_date"),
        pytest.param("1985-03-13", "2005-04-21", id="both_wrong"),
    ],
)
def test_ac_002_02_any_wrong_date_fails_without_revealing_which(birth: str, issue: str) -> None:
    """AC-002-02: cualquier fecha incorrecta falla sin revelar cuál."""
    decision = evaluate_verification(VerificationState(), _request(birth, issue), IDENTITY)

    assert decision.outcome is VerificationOutcome.FAILED
    assert decision.verified is False
    assert decision.escalation_required is False
    assert decision.state.attempts_remaining == 2
    assert decision.state.verified_customer_id is None
    assert set(vars(decision)) == {"state", "verified", "escalation_required", "outcome"}


# Regla: RN-002-02 — ambas fechas coinciden: cliente verificado.
# AC-002-01 · Art. 7
def test_ac_002_01_both_dates_correct_verifies() -> None:
    """AC-002-01: ambas fechas correctas verifican al cliente."""
    decision = evaluate_verification(VerificationState(), _request(), IDENTITY)

    assert decision.outcome is VerificationOutcome.VERIFIED
    assert decision.verified is True
    assert decision.escalation_required is False
    assert decision.state.verified_customer_id == "C-0001"
    assert decision.state.attempts_remaining == 3


# Regla: RN-002-03 — cliente inexistente indistinguible de fechas incorrectas.
# AC-002-04 · Art. 7
def test_ac_002_04_unknown_customer_same_as_wrong_dates() -> None:
    """AC-002-04: identidad inexistente produce la misma decisión y suma un fallo."""
    unknown = evaluate_verification(VerificationState(), _request(), None)
    wrong = evaluate_verification(VerificationState(), _request("1985-03-13"), IDENTITY)

    assert unknown == wrong
    assert unknown.outcome is VerificationOutcome.FAILED
    assert unknown.state.failed_attempts == 1


# Regla: RN-002-04 — los fallos se cuentan por conversación; máximo 3: con 1 o 2 fallos se admite
# un nuevo intento y el 3.º fallo bloquea la verificación; attempts_remaining = 3 − fallos (mín. 0).
# AC-002-05 · Art. 10 · borde exacto: 3.er fallo
@pytest.mark.parametrize(
    ("previous", "remaining", "escalates"),
    [
        pytest.param(0, 2, False, id="first_failure"),
        pytest.param(1, 1, False, id="second_failure"),
        pytest.param(2, 0, True, id="third_failure_locks"),
    ],
)
def test_ac_002_05_failure_count_boundary_locks_on_third(
    previous: int, remaining: int, escalates: bool
) -> None:
    """AC-002-05: el tercer fallo bloquea y escala."""
    state = VerificationState(failed_attempts=previous)

    decision = evaluate_verification(state, _request("1985-03-13"), IDENTITY)

    assert decision.state.attempts_remaining == remaining
    assert decision.escalation_required is escalates
    assert decision.verified is False
    expected = VerificationOutcome.LOCKED if escalates else VerificationOutcome.FAILED
    assert decision.outcome is expected


# Regla: RN-002-05 — con fallos previos, fechas correctas verifican mientras no haya bloqueo.
# AC-002-06 · Art. 7
def test_ac_002_06_success_after_two_failures_keeps_one_remaining() -> None:
    """AC-002-06: verificación correcta tras dos fallos deja 1 intento."""
    state = VerificationState(failed_attempts=2)

    decision = evaluate_verification(state, _request(), IDENTITY)

    assert decision.outcome is VerificationOutcome.VERIFIED
    assert decision.state.attempts_remaining == 1
    assert decision.state.verified_customer_id == "C-0001"


# Regla: RN-002-05 — conversación bloqueada: no se verifica aunque las fechas sean correctas.
# AC-002-07 · Art. 10 (ante la duda, escalar)
def test_ac_002_07_locked_state_with_correct_dates_stays_locked() -> None:
    """AC-002-07: bloqueada con fechas correctas sigue bloqueada y escala."""
    state = VerificationState(failed_attempts=3)

    decision = evaluate_verification(state, _request(), IDENTITY)

    assert decision.outcome is VerificationOutcome.LOCKED
    assert decision.verified is False
    assert decision.escalation_required is True
    assert decision.state.attempts_remaining == 0
    assert decision.state.verified_customer_id is None


# Regla: RN-002-10 — una conversación verificada no verifica a otro cliente.
# AC-002-11 · Art. 7
@pytest.mark.parametrize(
    ("birth", "issue", "identity"),
    [
        pytest.param(BIRTH, ISSUE, IDENTITY, id="correct_dates"),
        pytest.param("1985-03-13", ISSUE, IDENTITY, id="wrong_dates"),
        pytest.param(BIRTH, ISSUE, None, id="unknown_identity"),
    ],
)
def test_ac_002_11_other_customer_is_rejected_without_state_change(
    birth: str, issue: str, identity: IdentityRecord | None
) -> None:
    """AC-002-11: verificada para C-0001, solicitud para otro cliente se rechaza."""
    state = VerificationState(verified_customer_id="C-0001")

    decision = evaluate_verification(state, _request(birth, issue, "C-0002"), identity)

    assert decision.outcome is VerificationOutcome.OTHER_CUSTOMER
    assert decision.escalation_required is False
    assert decision.state == state
    assert decision.state.attempts_remaining == 3


# Regla: RN-002-11 — repetir la verificación del mismo cliente es idempotente.
# AC-002-12 · Art. 7
@pytest.mark.parametrize(
    ("birth", "issue"),
    [
        pytest.param(BIRTH, ISSUE, id="correct_dates"),
        pytest.param("1985-03-13", ISSUE, id="wrong_dates"),
    ],
)
def test_ac_002_12_same_customer_already_verified_is_idempotent(birth: str, issue: str) -> None:
    """AC-002-12: mismo cliente ya verificado conserva el estado."""
    state = VerificationState(verified_customer_id="C-0001")

    decision: VerificationDecision = evaluate_verification(state, _request(birth, issue), IDENTITY)

    assert decision.outcome is VerificationOutcome.ALREADY_VERIFIED
    assert decision.verified is True
    assert decision.escalation_required is False
    assert decision.state == state
