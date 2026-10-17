"""Log de auditoría en memoria."""

from core_banking_mcp.application.ports.audit_log import AuditEvent


class FakeAuditLog:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)
