"""Puerto de auditoría del agente."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

AuditEventType = Literal[
    "tool_call", "tool_blocked", "decision", "escalation", "conversation_closed", "llm_response"
]


@dataclass(frozen=True)
class AgentAuditEvent:
    conversation_id: str
    at: datetime
    event_type: AuditEventType
    tool: str | None = None
    input: dict[str, object] | None = None
    output: dict[str, object] | None = None
    rule: str | None = None
    reason: str | None = None


class AuditLogPort(Protocol):
    def record(self, event: AgentAuditEvent) -> None: ...
