"""Value objects del bloqueo de tarjetas."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.customer import CardStatus
from core_banking_mcp.domain.models.dispute import MAX_ID_LENGTH, _require_text
from core_banking_mcp.domain.models.transaction import validate_last4


class BlockReason(Enum):
    """Motivo del bloqueo (catálogo cerrado)."""

    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"
    LOST_OR_STOLEN = "LOST_OR_STOLEN"


@dataclass(frozen=True)
class CardBlockRequest:
    """Solicitud de bloqueo validada."""

    conversation_id: str
    card_id: str
    reason: BlockReason
    idempotency_key: str

    @classmethod
    def create(
        cls,
        conversation_id: str | None,
        card_id: str | None,
        reason: str | None,
        idempotency_key: str | None,
    ) -> "CardBlockRequest":
        """Valida la entrada cruda."""
        conversation = _require_text("conversation_id", conversation_id)
        card = _require_text("card_id", card_id, MAX_ID_LENGTH)
        key = _require_text("idempotency_key", idempotency_key, MAX_ID_LENGTH)
        try:
            parsed_reason = BlockReason(reason)
        except ValueError:
            raise InvalidInputError("reason", "motivo no permitido") from None
        return cls(conversation, card, parsed_reason, key)


@dataclass(frozen=True)
class OwnedCard:
    """Tarjeta perteneciente al cliente verificado."""

    card_id: str
    last4: str
    status: CardStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _require_text("card_id", self.card_id))
        validate_last4("last4", self.last4)


@dataclass(frozen=True)
class CardBlock:
    """Bloqueo registrado."""

    card_id: str
    conversation_id: str
    idempotency_key: str
    reason: BlockReason
    blocked_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "card_id", _require_text("card_id", self.card_id))
        object.__setattr__(
            self, "conversation_id", _require_text("conversation_id", self.conversation_id)
        )
        object.__setattr__(
            self, "idempotency_key", _require_text("idempotency_key", self.idempotency_key)
        )
        if self.blocked_at.tzinfo is None or self.blocked_at.utcoffset() is None:
            raise InvalidInputError("blocked_at", "debe incluir zona horaria")

    def same_request(self, card_id: str, reason: BlockReason) -> bool:
        """Indica si la solicitud coincide en tarjeta y motivo."""
        return self.card_id == card_id and self.reason is reason
