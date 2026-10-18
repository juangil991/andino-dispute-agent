"""Value objects de disputas de transacciones."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from core_banking_mcp.domain.errors import InvalidInputError

MAX_ID_LENGTH = 64


class DisputeReason(Enum):
    """Motivo de la disputa (catálogo cerrado, RN-004-02)."""

    UNRECOGNIZED_CHARGE = "UNRECOGNIZED_CHARGE"
    DUPLICATE_CHARGE = "DUPLICATE_CHARGE"
    INCORRECT_AMOUNT = "INCORRECT_AMOUNT"
    NOT_RECEIVED = "NOT_RECEIVED"
    OTHER = "OTHER"


class DisputeStatus(Enum):
    """Estado de una disputa."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


def _require_text(field: str, value: str | None, max_length: int | None = None) -> str:
    """Exige texto no vacío tras recortar (y de a lo sumo `max_length`); devuelve el recortado."""
    if value is None or not value.strip():
        raise InvalidInputError(field, "no puede estar vacío")
    text = value.strip()
    if max_length is not None and len(text) > max_length:
        raise InvalidInputError(field, f"no puede superar {max_length} caracteres")
    return text


@dataclass(frozen=True)
class DisputeRequest:
    """Solicitud de disputa validada."""

    conversation_id: str
    transaction_id: str
    reason: DisputeReason
    idempotency_key: str

    @classmethod
    def create(
        cls,
        conversation_id: str | None,
        transaction_id: str | None,
        reason: str | None,
        idempotency_key: str | None,
    ) -> "DisputeRequest":
        """Valida la entrada cruda (RN-004-02, RN-004-09)."""
        conversation = _require_text("conversation_id", conversation_id)
        transaction = _require_text("transaction_id", transaction_id, MAX_ID_LENGTH)
        key = _require_text("idempotency_key", idempotency_key, MAX_ID_LENGTH)
        try:
            parsed_reason = DisputeReason(reason)
        except ValueError:
            raise InvalidInputError("reason", "motivo no permitido") from None
        return cls(conversation, transaction, parsed_reason, key)


@dataclass(frozen=True)
class Dispute:
    """Disputa registrada."""

    dispute_id: str
    conversation_id: str
    idempotency_key: str
    transaction_id: str
    reason: DisputeReason
    status: DisputeStatus
    opened_at: datetime

    def __post_init__(self) -> None:
        _require_text("dispute_id", self.dispute_id)
        _require_text("conversation_id", self.conversation_id)
        _require_text("idempotency_key", self.idempotency_key)
        _require_text("transaction_id", self.transaction_id)
        if self.opened_at.tzinfo is None or self.opened_at.utcoffset() is None:
            raise InvalidInputError("opened_at", "debe incluir zona horaria")

    def same_request(self, transaction_id: str, reason: DisputeReason) -> bool:
        """Indica si la solicitud coincide en transacción y motivo (RN-004-08)."""
        return self.transaction_id == transaction_id and self.reason is reason
