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
    input: AuditInput
    outcome: str
    count: int | None
    customer_ids: tuple[str, ...]
    error_code: str | None
    rule: str | None
    reason: str | None


class AuditLogPort(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Registra un evento de auditoría."""
        ...
