"""Puerto de salida: repositorio de clientes."""

from typing import Protocol

from core_banking_mcp.domain.models.customer import Customer
from core_banking_mcp.domain.models.identity import IdentityRecord
from core_banking_mcp.domain.models.search import SearchCriteria


class CustomerRepository(Protocol):
    def find_matching(self, criteria: SearchCriteria, limit: int) -> list[Customer]:
        """Clientes que cumplen todos los criterios (AND), ordenados por customer_id."""
        ...

    def find_identity(self, customer_id: str) -> IdentityRecord | None:
        """Datos de identidad del cliente, o None si no existen."""
        ...
