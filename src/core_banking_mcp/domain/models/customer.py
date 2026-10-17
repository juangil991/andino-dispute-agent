"""Entidades Customer y Card (el dominio no almacena el PAN)."""

from dataclasses import dataclass
from enum import Enum

from core_banking_mcp.domain.errors import InvalidInputError


class CardStatus(Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Card:
    last4: str
    status: CardStatus

    def __post_init__(self) -> None:
        if not (len(self.last4) == 4 and self.last4.isascii() and self.last4.isdigit()):
            raise InvalidInputError("last4", "debe tener exactamente 4 dígitos")


@dataclass(frozen=True)
class Customer:
    customer_id: str
    full_name: str
    document: str
    cards: tuple[Card, ...] = ()

    def __post_init__(self) -> None:
        for name in ("customer_id", "full_name", "document"):
            if not getattr(self, name).strip():
                raise InvalidInputError(name, "no puede estar vacío")
