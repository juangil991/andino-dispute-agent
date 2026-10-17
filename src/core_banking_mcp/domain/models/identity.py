"""Value objects de verificación de identidad."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from core_banking_mcp.domain.dates import parse_iso_date
from core_banking_mcp.domain.errors import InvalidInputError

MAX_FAILED_ATTEMPTS = 3
MAX_ID_LENGTH = 32


def _clean_id(field: str, value: str | None) -> str:
    cleaned = (value or "").strip()
    if not 1 <= len(cleaned) <= MAX_ID_LENGTH:
        raise InvalidInputError(field, f"debe tener entre 1 y {MAX_ID_LENGTH} caracteres")
    return cleaned


def _parse_date(field: str, value: str | None, today: date) -> date:
    parsed = parse_iso_date(field, value)
    if parsed > today:
        raise InvalidInputError(field, "no puede ser posterior a hoy")
    return parsed


@dataclass(frozen=True)
class VerificationRequest:
    """Solicitud de verificación validada."""

    conversation_id: str
    customer_id: str
    birth_date: date
    document_issue_date: date

    @classmethod
    def create(
        cls,
        conversation_id: str | None,
        customer_id: str | None,
        birth_date: str | None,
        document_issue_date: str | None,
        today: date,
    ) -> VerificationRequest:
        conversation = _clean_id("conversation_id", conversation_id)
        customer = _clean_id("customer_id", customer_id)
        birth = _parse_date("birth_date", birth_date, today)
        issued = _parse_date("document_issue_date", document_issue_date, today)
        if issued < birth:
            raise InvalidInputError("document_issue_date", "no puede ser anterior a birth_date")
        return cls(conversation, customer, birth, issued)


@dataclass(frozen=True)
class IdentityRecord:
    """Datos de identidad almacenados de un cliente."""

    birth_date: date
    document_issue_date: date

    def __post_init__(self) -> None:
        if self.document_issue_date < self.birth_date:
            raise InvalidInputError("document_issue_date", "no puede ser anterior a birth_date")


@dataclass(frozen=True)
class VerificationState:
    """Estado de verificación de una conversación."""

    verified_customer_id: str | None = None
    failed_attempts: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.failed_attempts <= MAX_FAILED_ATTEMPTS:
            raise InvalidInputError(
                "failed_attempts", f"debe estar entre 0 y {MAX_FAILED_ATTEMPTS}"
            )
        if self.verified_customer_id is not None and self.is_locked:
            raise InvalidInputError(
                "verified_customer_id", "un estado bloqueado no puede estar verificado"
            )

    @property
    def attempts_remaining(self) -> int:
        return MAX_FAILED_ATTEMPTS - self.failed_attempts

    @property
    def is_locked(self) -> bool:
        return self.failed_attempts >= MAX_FAILED_ATTEMPTS

    def is_verified_for(self, customer_id: str) -> bool:
        return self.verified_customer_id == customer_id

    def with_failure(self) -> VerificationState:
        return replace(self, failed_attempts=self.failed_attempts + 1)

    def with_verified(self, customer_id: str) -> VerificationState:
        return replace(self, verified_customer_id=customer_id)
