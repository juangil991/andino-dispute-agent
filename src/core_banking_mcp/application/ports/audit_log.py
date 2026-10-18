"""Puerto de salida: auditoría del lado del servidor (RN-001-12)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AuditInput:
    """Entrada auditada; el documento va enmascarado."""

    document: str | None
    full_name: str | None
    card_last4: str | None


@dataclass(frozen=True)
class AuditEvent:
    conversation_id: str | None
    timestamp: datetime
    tool: str
    input: AuditInput | None
    outcome: str
    count: int | None
    customer_ids: tuple[str, ...]
    error_code: str | None
    rule: str | None
    reason: str | None
    customer_id: str | None = None
    intento: int | None = None
    masked_card: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    transaction_ids: tuple[str, ...] = ()
    transaction_id: str | None = None
    dispute_reason: str | None = None
    idempotency_key: str | None = None
    dispute_id: str | None = None
    card_id: str | None = None
    block_reason: str | None = None
    escalation_reason: str | None = None
    escalation_id: str | None = None
    note: str | None = None
    prior_actions: tuple[str, ...] = ()
    identity_verified: bool | None = None


class AuditLogPort(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Registra un evento de auditoría."""
        ...
