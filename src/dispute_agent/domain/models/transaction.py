"""Vista del dominio de una transacción devuelta por el core."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from dispute_agent.domain.errors import InvalidTransactionDataError


class TransactionStatus(Enum):
    """Estado de una transacción en el core."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REVERSED = "REVERSED"


def _is_upper_ascii_alpha(value: str, length: int) -> bool:
    return len(value) == length and value.isascii() and value.isalpha() and value.isupper()


@dataclass(frozen=True)
class DisputedTransaction:
    """Transacción sobre la que el cliente puede disputar (plan §4)."""

    transaction_id: str
    card_id: str
    masked_card: str
    occurred_at: datetime
    merchant: str
    amount: Decimal
    currency: str
    merchant_country: str
    status: TransactionStatus

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise InvalidTransactionDataError("occurred_at debe incluir zona horaria")
        if not self.amount.is_finite() or self.amount <= 0:
            raise InvalidTransactionDataError("amount debe ser mayor que 0")
        exponent = self.amount.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -2:
            raise InvalidTransactionDataError("amount admite como máximo 2 decimales")
        if not _is_upper_ascii_alpha(self.currency, 3):
            raise InvalidTransactionDataError("currency debe tener 3 letras en mayúsculas")
        if not _is_upper_ascii_alpha(self.merchant_country, 2):
            raise InvalidTransactionDataError("merchant_country debe tener 2 letras en mayúsculas")
