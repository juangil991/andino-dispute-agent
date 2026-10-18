"""Adaptador de auditoría: una línea JSON por evento a un stream (stderr por defecto)."""

import json
import sys
from dataclasses import asdict
from typing import TextIO

from core_banking_mcp.application.ports.audit_log import AuditEvent

_OPTIONAL_KEYS = (
    "customer_id",
    "intento",
    "masked_card",
    "date_from",
    "date_to",
    "transaction_ids",
    "transaction_id",
    "dispute_reason",
    "idempotency_key",
    "dispute_id",
    "card_id",
    "block_reason",
)


class JsonAuditLog:
    """Implementa `AuditLogPort`; nunca escribe en stdout (canal MCP, Art. 8)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def record(self, event: AuditEvent) -> None:
        payload = asdict(event)
        payload["timestamp"] = event.timestamp.isoformat()
        payload["customer_ids"] = list(event.customer_ids)
        payload["transaction_ids"] = list(event.transaction_ids)
        for key in _OPTIONAL_KEYS:
            if payload[key] in (None, []):
                del payload[key]
        self._stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._stream.flush()
