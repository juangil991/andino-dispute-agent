import json
from datetime import UTC, datetime

import pytest

from dispute_agent.application.ports.audit_log import AgentAuditEvent
from dispute_agent.infrastructure.outbound.audit.json_audit_log import JsonAuditLog


# Regla: RN-007-28 — Cada evento genera un registro de auditoría en `AuditLogPort`, en JSON. Hay
# tres tipos de evento: llamada a herramienta (incluidas las bloqueadas), decisión de
# `DisputePolicy` y derivación o cierre. Cada registro lleva `conversation_id`, marca de tiempo
# del reloj inyectado, tipo de evento, entrada, salida, regla aplicada (`DP-007-XX` o
# `RN-007-XX`) y motivo. Ningún registro contiene un número completo de tarjeta ni un documento
# completo: se aplica el filtro de RN-007-26.
# AC-007-30 · Art. 8
# Convención: las claves con valor None se OMITEN del JSON.
def test_ac_007_30_agent_json_audit_log__event__json_line_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-007-30: línea JSON en stderr con PAN sustituido y documento enmascarado intacto."""
    event = AgentAuditEvent(
        conversation_id="c" * 32,
        at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        event_type="tool_call",
        tool="search_customer",
        input={"card": "4111111111111111", "document": "****01"},
        output={"echo": "pan 4111111111111111"},
        rule="RN-007-28",
        reason="prueba",
    )

    JsonAuditLog().record(event)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    data = json.loads(captured.err)
    assert data == {
        "conversation_id": "c" * 32,
        "at": "2026-01-02T03:04:05+00:00",
        "event_type": "tool_call",
        "tool": "search_customer",
        "input": {"card": "[REDACTED]", "document": "****01"},
        "output": {"echo": "pan [REDACTED]"},
        "rule": "RN-007-28",
        "reason": "prueba",
    }
    assert "4111111111111111" not in captured.err


# Soporte de tests: claves None omitidas · Art. 3
def test_agent_json_audit_log__none_fields__omitted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Soporte: los campos opcionales ausentes no aparecen en la línea."""
    JsonAuditLog().record(
        AgentAuditEvent(
            conversation_id="x",
            at=datetime(2026, 1, 2, tzinfo=UTC),
            event_type="decision",
        )
    )

    data = json.loads(capsys.readouterr().err)
    assert set(data) == {"conversation_id", "at", "event_type"}
