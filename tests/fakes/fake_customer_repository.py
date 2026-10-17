"""Repositorio en memoria que filtra con las funciones de normalización."""

from collections.abc import Iterable

from core_banking_mcp.domain.models.customer import Customer
from core_banking_mcp.domain.models.search import SearchCriteria
from core_banking_mcp.domain.normalization import normalize_document, normalize_name


class FakeCustomerRepository:
    def __init__(self, customers: Iterable[Customer] = ()) -> None:
        self._customers = list(customers)

    def find_matching(self, criteria: SearchCriteria, limit: int) -> list[Customer]:
        matches = [c for c in self._customers if self._matches(c, criteria)]
        matches.sort(key=lambda c: c.customer_id)
        return matches[:limit]

    @staticmethod
    def _matches(customer: Customer, criteria: SearchCriteria) -> bool:
        if criteria.document is not None and (
            normalize_document(customer.document) != criteria.document
        ):
            return False
        if criteria.full_name is not None and (
            normalize_name(customer.full_name) != criteria.full_name
        ):
            return False
        return criteria.card_last4 is None or any(
            card.last4 == criteria.card_last4 for card in customer.cards
        )
