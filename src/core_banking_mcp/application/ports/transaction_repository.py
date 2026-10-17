"""Puerto de salida: consulta de tarjetas y transacciones del core."""

from datetime import datetime
from typing import Protocol

from core_banking_mcp.domain.models.transaction import CustomerCard, Transaction


class TransactionRepository(Protocol):
    def find_customer_cards(self, customer_id: str, last4: str) -> list[CustomerCard]:
        """Tarjetas del cliente con esos últimos 4 dígitos (cualquier estado), por card_id."""
        ...

    def find_transactions(
        self, card_ids: list[str], start: datetime, end: datetime, limit: int
    ) -> list[Transaction]:
        """Transacciones con start <= occurred_at < end, más recientes primero."""
        ...
