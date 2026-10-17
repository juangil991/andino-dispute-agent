import io
import json
from datetime import UTC, datetime

import pytest

from core_banking_mcp.application.ports.audit_log import AuditEvent, AuditInput
from core_banking_mcp.infrastructure.outbound.audit.json_audit_log import JsonAuditLog


# Regla: RN-001-12 — la auditoría se emite como una línea JSON a stderr, nunca a stdout.
# AC-001-13 · Art. 8
def test_ac_001_13_audit_event_is_written_as_json_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-001-13: el evento se escribe como una línea JSON válida y nada va a stdout."""
    stream = io.StringIO()
    event = AuditEvent(
        conversation_id="conv-1",
        timestamp=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        tool="search_customer",
        input=AuditInput(document="****4567", full_name="Ana Pérez", card_last4="1234"),
        outcome="ok",
        count=2,
        customer_ids=("c-1", "c-2"),
        error_code=None,
        rule=None,
        reason=None,
    )

    JsonAuditLog(stream=stream).record(event)

    raw = stream.getvalue()
    assert raw.endswith("\n")
    assert raw.count("\n") == 1
    data = json.loads(raw)
    assert data == {
        "conversation_id": "conv-1",
        "timestamp": "2026-01-02T03:04:05+00:00",
        "tool": "search_customer",
        "input": {"document": "****4567", "full_name": "Ana Pérez", "card_last4": "1234"},
        "outcome": "ok",
        "count": 2,
        "customer_ids": ["c-1", "c-2"],
        "error_code": None,
        "rule": None,
        "reason": None,
    }
    assert "Ana Pérez" in raw
    assert capsys.readouterr().out == ""
