"""Repositorio de transacciones en memoria que replica filtro, orden y límite."""

from collections.abc import Iterable, Mapping
from datetime import datetime

from core_banking_mcp.domain.models.transaction import CustomerCard, Transaction


class FakeTransactionRepository:
    def __init__(
        self,
        cards: Mapping[str, Iterable[CustomerCard]] | None = None,
        transactions: Iterable[Transaction] = (),
    ) -> None:
        self._cards = {customer: list(items) for customer, items in (cards or {}).items()}
        self._transactions = list(transactions)
        self.called = False

    def find_customer_cards(self, customer_id: str, last4: str) -> list[CustomerCard]:
        self.called = True
        matches = [c for c in self._cards.get(customer_id, []) if c.last4 == last4]
        return sorted(matches, key=lambda c: c.card_id)

    def find_transactions(
        self, card_ids: list[str], start: datetime, end: datetime, limit: int
    ) -> list[Transaction]:
        self.called = True
        matches = [
            t for t in self._transactions if t.card_id in card_ids and start <= t.occurred_at < end
        ]
        matches.sort(key=lambda t: t.transaction_id)
        matches.sort(key=lambda t: t.occurred_at, reverse=True)
        return matches[:limit]
