"""Adaptador de auditoría: una línea JSON por evento a stderr, sin PANs (RN-007-28)."""

import json
import sys
from dataclasses import asdict
from typing import TextIO

from dispute_agent.application.ports.audit_log import AgentAuditEvent
from dispute_agent.domain.redaction import redact_reply


class JsonAuditLog:
    """Implementa `AuditLogPort`; nunca escribe en stdout. Omite las claves None."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def record(self, event: AgentAuditEvent) -> None:
        payload = {k: v for k, v in asdict(event).items() if v is not None}
        payload["at"] = event.at.isoformat()
        line = redact_reply(json.dumps(payload, ensure_ascii=False), documents=())
        self._stream.write(line + "\n")
        self._stream.flush()
