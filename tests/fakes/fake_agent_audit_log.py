"""Log de auditoría del agente en memoria."""

from dispute_agent.application.ports.audit_log import AgentAuditEvent


class FakeAgentAuditLog:
    def __init__(self) -> None:
        self.events: list[AgentAuditEvent] = []

    def record(self, event: AgentAuditEvent) -> None:
        self.events.append(event)
