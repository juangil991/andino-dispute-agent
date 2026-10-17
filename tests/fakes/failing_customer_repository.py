"""Repositorio que siempre falla con una excepción que no es de dominio."""

from core_banking_mcp.domain.models.customer import Customer
from core_banking_mcp.domain.models.identity import IdentityRecord
from core_banking_mcp.domain.models.search import SearchCriteria


class FailingCustomerRepository:
    def find_matching(self, criteria: SearchCriteria, limit: int) -> list[Customer]:
        raise RuntimeError("fallo simulado del core (detalle interno secreto)")

    def find_identity(self, customer_id: str) -> IdentityRecord | None:
        raise RuntimeError("fallo simulado del core (detalle interno secreto)")
