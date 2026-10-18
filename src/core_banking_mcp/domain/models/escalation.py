"""Value objects de la derivación de un caso a un analista humano."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.masking import redact_card_numbers
from core_banking_mcp.domain.models.dispute import MAX_ID_LENGTH, _require_text

MAX_NOTE_LENGTH = 300


class EscalationReason(Enum):
    """Motivo de la derivación (catálogo cerrado, RN-006-02)."""

    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"
    AMOUNT_OVER_THRESHOLD = "AMOUNT_OVER_THRESHOLD"
    INSUFFICIENT_OR_CONTRADICTORY_INFO = "INSUFFICIENT_OR_CONTRADICTORY_INFO"
    INCONCLUSIVE_RULES = "INCONCLUSIVE_RULES"
    UNRECOVERABLE_SYSTEM_FAILURE = "UNRECOVERABLE_SYSTEM_FAILURE"
    IDENTITY_VERIFICATION_FAILED = "IDENTITY_VERIFICATION_FAILED"
    OTHER = "OTHER"


class PriorAction(Enum):
    """Acción previa a la derivación; el orden de declaración es el canónico (RN-006-05)."""

    DISPUTE_OPENED = "DISPUTE_OPENED"
    CARD_BLOCKED = "CARD_BLOCKED"


class EscalationStatus(Enum):
    """Estado de una derivación."""

    PENDING = "PENDING"


def _optional_id(field: str, value: str | None) -> str | None:
    """Valida un id opcional: `None` o de 1 a `MAX_ID_LENGTH` caracteres tras recortar."""
    if value is None:
        return None
    return _require_text(field, value, MAX_ID_LENGTH)


def _parse_prior_actions(values: Sequence[str] | None) -> frozenset[PriorAction]:
    """Convierte los códigos recibidos; rechaza los desconocidos y los repetidos."""
    parsed: list[PriorAction] = []
    for value in values or ():
        try:
            parsed.append(PriorAction(value))
        except ValueError:
            raise InvalidInputError("prior_actions", "acción previa no permitida") from None
    if len(set(parsed)) != len(parsed):
        raise InvalidInputError("prior_actions", "acción previa repetida")
    return frozenset(parsed)


def _normalize_note(note: str | None) -> str | None:
    """Recorta la nota, la vacía es `None`, limita su longitud y redacta números de tarjeta."""
    if note is None or not note.strip():
        return None
    text = note.strip()
    if len(text) > MAX_NOTE_LENGTH:
        raise InvalidInputError("note", f"no puede superar {MAX_NOTE_LENGTH} caracteres")
    return redact_card_numbers(text)


@dataclass(frozen=True)
class EscalationRequest:
    """Solicitud de derivación validada."""

    conversation_id: str
    reason: EscalationReason
    idempotency_key: str
    transaction_id: str | None
    card_id: str | None
    prior_actions: frozenset[PriorAction]
    dispute_id: str | None
    note: str | None

    @classmethod
    def create(
        cls,
        conversation_id: str | None,
        reason: str | None,
        idempotency_key: str | None,
        transaction_id: str | None = None,
        card_id: str | None = None,
        prior_actions: Sequence[str] | None = None,
        dispute_id: str | None = None,
        note: str | None = None,
    ) -> "EscalationRequest":
        """Valida la entrada cruda (RN-006-02, RN-006-05, RN-006-07, RN-006-10)."""
        conversation = _require_text("conversation_id", conversation_id)
        key = _require_text("idempotency_key", idempotency_key, MAX_ID_LENGTH)
        try:
            parsed_reason = EscalationReason(reason)
        except ValueError:
            raise InvalidInputError("reason", "motivo no permitido") from None
        transaction = _optional_id("transaction_id", transaction_id)
        card = _optional_id("card_id", card_id)
        dispute = _optional_id("dispute_id", dispute_id)
        actions = _parse_prior_actions(prior_actions)
        if PriorAction.DISPUTE_OPENED in actions and (dispute is None or transaction is None):
            raise InvalidInputError(
                "prior_actions", "DISPUTE_OPENED exige dispute_id y transaction_id"
            )
        if dispute is not None and PriorAction.DISPUTE_OPENED not in actions:
            raise InvalidInputError("dispute_id", "exige DISPUTE_OPENED en prior_actions")
        if PriorAction.CARD_BLOCKED in actions and card is None:
            raise InvalidInputError("prior_actions", "CARD_BLOCKED exige card_id")
        return cls(
            conversation,
            parsed_reason,
            key,
            transaction,
            card,
            actions,
            dispute,
            _normalize_note(note),
        )

    @property
    def has_customer_data(self) -> bool:
        """Indica si la solicitud trae datos del cliente (RN-006-03)."""
        return (
            self.transaction_id is not None
            or self.card_id is not None
            or self.dispute_id is not None
        )


@dataclass(frozen=True)
class Escalation:
    """Derivación registrada."""

    escalation_id: str
    conversation_id: str
    idempotency_key: str
    reason: EscalationReason
    status: EscalationStatus
    escalated_at: datetime
    identity_verified: bool
    customer_id: str | None
    transaction_id: str | None
    card_id: str | None
    prior_actions: frozenset[PriorAction]
    dispute_id: str | None
    note: str | None

    def __post_init__(self) -> None:
        _require_text("escalation_id", self.escalation_id)
        _require_text("conversation_id", self.conversation_id)
        _require_text("idempotency_key", self.idempotency_key)
        if self.escalated_at.tzinfo is None or self.escalated_at.utcoffset() is None:
            raise InvalidInputError("escalated_at", "debe incluir zona horaria")
        if not self.identity_verified and (
            self.customer_id is not None
            or self.transaction_id is not None
            or self.card_id is not None
            or self.dispute_id is not None
            or self.prior_actions
        ):
            raise InvalidInputError(
                "identity_verified", "un resumen limitado no admite datos del cliente"
            )

    def same_request(self, request: EscalationRequest) -> bool:
        """Indica si la solicitud coincide en todos sus datos normalizados (RN-006-09)."""
        return (
            self.reason is request.reason
            and self.transaction_id == request.transaction_id
            and self.card_id == request.card_id
            and self.prior_actions == request.prior_actions
            and self.dispute_id == request.dispute_id
            and self.note == request.note
        )

    def ordered_prior_actions(self) -> tuple[PriorAction, ...]:
        """Devuelve las acciones previas en el orden del catálogo."""
        return tuple(action for action in PriorAction if action in self.prior_actions)
