"""Value objects de transacciones de tarjeta."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum

from core_banking_mcp.domain.dates import parse_iso_date
from core_banking_mcp.domain.errors import InvalidInputError

MAX_RANGE_DAYS = 90
# Misma zona que domain/clock.py (UTC-5 fijo, sin horario de verano).
_BOGOTA = timezone(timedelta(hours=-5))


class TransactionStatus(Enum):
    """Estado de una transacción."""

    CONFIRMED = "CONFIRMED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"


def validate_last4(field: str, value: str) -> None:
    """Exige exactamente 4 dígitos ASCII."""
    if len(value) != 4 or not (value.isascii() and value.isdigit()):
        raise InvalidInputError(field, "debe tener exactamente 4 dígitos")


def _require_text(field: str, value: str) -> None:
    if not value or not value.strip():
        raise InvalidInputError(field, "no puede estar vacío")


@dataclass(frozen=True)
class CustomerCard:
    """Tarjeta de un cliente: identificador opaco y últimos 4 dígitos."""

    card_id: str
    last4: str

    def __post_init__(self) -> None:
        _require_text("card_id", self.card_id)
        validate_last4("last4", self.last4)


@dataclass(frozen=True)
class Transaction:
    """Transacción de una tarjeta."""

    transaction_id: str
    card_id: str
    card_last4: str
    occurred_at: datetime
    merchant: str
    amount: Decimal
    currency: str
    status: TransactionStatus

    def __post_init__(self) -> None:
        _require_text("transaction_id", self.transaction_id)
        _require_text("card_id", self.card_id)
        _require_text("merchant", self.merchant)
        validate_last4("card_last4", self.card_last4)
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise InvalidInputError("occurred_at", "debe incluir zona horaria")
        if not self.amount.is_finite() or self.amount <= 0:
            raise InvalidInputError("amount", "debe ser positivo")
        if self.amount != self.amount.quantize(Decimal("0.01")):
            raise InvalidInputError("amount", "admite como máximo 2 decimales")
        currency = self.currency
        if not (
            len(currency) == 3 and currency.isascii() and currency.isalpha() and currency.isupper()
        ):
            raise InvalidInputError("currency", "debe ser un código ISO 4217")


MAX_TRANSACTIONS = 50


@dataclass(frozen=True)
class TransactionListResult:
    """Resultado acotado (RN-003-10): más de 50 coincidencias piden refinar."""

    transactions: tuple[Transaction, ...]
    refinement_required: bool

    def __post_init__(self) -> None:
        if len(self.transactions) > MAX_TRANSACTIONS:
            raise ValueError("transactions exceeds MAX_TRANSACTIONS")
        if self.refinement_required and self.transactions:
            raise ValueError("refinement_required implies empty transactions")

    @classmethod
    def from_matches(cls, matches: Sequence[Transaction]) -> "TransactionListResult":
        """Aplica RN-003-10: con más de 50 coincidencias devuelve vacío y refinar."""
        if len(matches) > MAX_TRANSACTIONS:
            return cls((), True)
        return cls(tuple(matches), False)


@dataclass(frozen=True)
class BogotaDateRange:
    """Rango de fechas locales de Bogotá, ambos extremos incluidos."""

    date_from: date
    date_to: date

    def __post_init__(self) -> None:
        if self.date_from > self.date_to:
            raise InvalidInputError("date_range", "date_from no puede ser posterior a date_to")
        if (self.date_to - self.date_from).days + 1 > MAX_RANGE_DAYS:
            raise InvalidInputError(
                "date_range", f"el rango no puede superar {MAX_RANGE_DAYS} días"
            )

    def utc_bounds(self) -> tuple[datetime, datetime]:
        """Devuelve `[inicio, fin)` en UTC que cubre los días completos de Bogotá."""
        start = datetime.combine(self.date_from, time.min, tzinfo=_BOGOTA)
        end = datetime.combine(self.date_to + timedelta(days=1), time.min, tzinfo=_BOGOTA)
        return start.astimezone(UTC), end.astimezone(UTC)


@dataclass(frozen=True)
class TransactionQuery:
    """Consulta validada de transacciones de una tarjeta."""

    conversation_id: str
    card_last4: str
    date_range: BogotaDateRange

    @classmethod
    def create(
        cls,
        conversation_id: str | None,
        card_last4: str | None,
        date_from: str | None,
        date_to: str | None,
        today: date,
    ) -> "TransactionQuery":
        """Valida la entrada cruda; `today` es la fecha de hoy en Bogotá."""
        if conversation_id is None:
            raise InvalidInputError("conversation_id", "no puede estar vacío")
        _require_text("conversation_id", conversation_id)
        if card_last4 is None:
            raise InvalidInputError("card_last4", "debe tener exactamente 4 dígitos")
        validate_last4("card_last4", card_last4)
        parsed_from = parse_iso_date("date_from", date_from)
        parsed_to = parse_iso_date("date_to", date_to)
        if parsed_to > today:
            raise InvalidInputError("date_to", "no puede ser posterior a hoy")
        return cls(conversation_id.strip(), card_last4, BogotaDateRange(parsed_from, parsed_to))
