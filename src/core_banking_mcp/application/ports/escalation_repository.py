"""Puerto de salida: persistencia de derivaciones a un analista humano."""

from datetime import datetime
from typing import Protocol

from core_banking_mcp.domain.models.escalation import Escalation, EscalationReason, PriorAction


class EscalationRepository(Protocol):
    def find_by_key(self, conversation_id: str, idempotency_key: str) -> Escalation | None:
        """Derivación de esa conversación con esa clave de idempotencia, si existe."""
        ...

    def add(
        self,
        conversation_id: str,
        idempotency_key: str,
        reason: EscalationReason,
        escalated_at: datetime,
        identity_verified: bool,
        customer_id: str | None,
        transaction_id: str | None,
        card_id: str | None,
        prior_actions: frozenset[PriorAction],
        dispute_id: str | None,
        note: str | None,
    ) -> Escalation:
        """Persiste la derivación asignándole su identificador; la operación es atómica."""
        ...
