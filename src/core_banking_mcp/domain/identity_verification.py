"""Decisión pura de verificación de identidad."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core_banking_mcp.domain.models.identity import (
    IdentityRecord,
    VerificationRequest,
    VerificationState,
)


class VerificationOutcome(Enum):
    VERIFIED = "VERIFIED"
    ALREADY_VERIFIED = "ALREADY_VERIFIED"
    FAILED = "FAILED"
    LOCKED = "LOCKED"
    OTHER_CUSTOMER = "OTHER_CUSTOMER"


@dataclass(frozen=True)
class VerificationDecision:
    """Resultado de evaluar una solicitud: nuevo estado y desenlace."""

    state: VerificationState
    verified: bool
    escalation_required: bool
    outcome: VerificationOutcome


def _dates_match(request: VerificationRequest, identity: IdentityRecord | None) -> bool:
    if identity is None:
        return False
    return (
        request.birth_date == identity.birth_date
        and request.document_issue_date == identity.document_issue_date
    )


def evaluate_verification(
    state: VerificationState,
    request: VerificationRequest,
    identity: IdentityRecord | None,
) -> VerificationDecision:
    """Decide el resultado de verificar a un cliente sin revelar qué dato falló."""
    if state.is_verified_for(request.customer_id):
        return VerificationDecision(state, True, False, VerificationOutcome.ALREADY_VERIFIED)
    if state.verified_customer_id is not None:
        return VerificationDecision(state, False, False, VerificationOutcome.OTHER_CUSTOMER)
    if state.is_locked:
        return VerificationDecision(state, False, True, VerificationOutcome.LOCKED)
    if _dates_match(request, identity):
        verified = state.with_verified(request.customer_id)
        return VerificationDecision(verified, True, False, VerificationOutcome.VERIFIED)
    failed = state.with_failure()
    if failed.is_locked:
        return VerificationDecision(failed, False, True, VerificationOutcome.LOCKED)
    return VerificationDecision(failed, False, False, VerificationOutcome.FAILED)
