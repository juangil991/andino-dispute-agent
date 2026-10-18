"""Puerto de salida: persistencia de disputas."""

from datetime import datetime
from typing import Protocol

from core_banking_mcp.domain.models.dispute import Dispute, DisputeReason, DisputeStatus


class DisputeRepository(Protocol):
    def find_by_idempotency_key(self, conversation_id: str, idempotency_key: str) -> Dispute | None:
        """Disputa de esa conversación con esa clave de idempotencia, si existe."""
        ...

    def find_open_by_transaction(self, transaction_id: str) -> Dispute | None:
        """Disputa vigente (ni CLOSED ni REJECTED) de la transacción, si existe."""
        ...

    def find_by_id(self, dispute_id: str) -> Dispute | None:
        """Disputa con ese identificador, si existe."""
        ...

    def add(
        self,
        conversation_id: str,
        idempotency_key: str,
        transaction_id: str,
        reason: DisputeReason,
        status: DisputeStatus,
        opened_at: datetime,
    ) -> Dispute:
        """Persiste la disputa asignándole su identificador."""
        ...
