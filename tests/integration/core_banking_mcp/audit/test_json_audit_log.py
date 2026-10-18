import io
import json
import re
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


def _verificar_event(intento: int | None) -> AuditEvent:
    return AuditEvent(
        conversation_id="conv-2",
        timestamp=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        tool="verificar_identidad",
        input=None,
        outcome="failed",
        count=None,
        customer_ids=(),
        error_code=None,
        rule=None,
        reason=None,
        customer_id="C-0001",
        intento=intento,
    )


# Regla: RN-002-15 — la auditoría de verificar_identidad no incluye fechas de identidad.
# AC-002-15 · Art. 8
def test_ac_002_15_verificar_identidad_event_is_serialized_without_dates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-002-15: línea JSON con customer_id e intento, input nulo y sin fechas AAAA-MM-DD."""
    stream = io.StringIO()

    JsonAuditLog(stream=stream).record(_verificar_event(intento=1))

    raw = stream.getvalue()
    assert raw.count("\n") == 1
    data = json.loads(raw)
    assert data["customer_id"] == "C-0001"
    assert data["intento"] == 1
    assert data["input"] is None
    assert data["timestamp"] == "2026-01-02T03:04:05+00:00"
    # Solo el instante ISO puede contener una fecha; ninguna otra cadena AAAA-MM-DD.
    assert not re.findall(r"\d{4}-\d{2}-\d{2}", raw.replace(data["timestamp"], ""))
    assert capsys.readouterr().out == ""


# Regla: RN-002-15 — sin intento (borde: customer_id presente), la línea omite `intento`.
# AC-002-15 · Art. 8
def test_ac_002_15_verificar_identidad_event_without_intento_omits_key() -> None:
    """AC-002-15: con customer_id pero sin intento, la línea no trae `intento`."""
    stream = io.StringIO()

    JsonAuditLog(stream=stream).record(_verificar_event(intento=None))

    data = json.loads(stream.getvalue())
    assert data["customer_id"] == "C-0001"
    assert "intento" not in data


def _transacciones_event(masked_card: str | None, transaction_ids: tuple[str, ...]) -> AuditEvent:
    return AuditEvent(
        conversation_id="conv-3",
        timestamp=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        tool="consultar_transacciones",
        input=None,
        outcome="found",
        count=len(transaction_ids),
        customer_ids=(),
        error_code=None,
        rule=None,
        reason=None,
        customer_id="C-0001",
        masked_card=masked_card,
        date_from="2026-01-01" if masked_card else None,
        date_to="2026-01-31" if masked_card else None,
        transaction_ids=transaction_ids,
    )


# Regla: RN-003-15 — cada invocación genera un registro de auditoría con la tarjeta enmascarada (`**** NNNN`), el rango consultado y los `transaction_id` devueltos, sin ningún número completo de tarjeta.  # noqa: E501
# AC-003-17 · Art. 8
def test_ac_003_17_consultar_transacciones_event_is_serialized_without_pan(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-003-17: línea JSON con tarjeta enmascarada, rango y transaction_ids como lista."""
    stream = io.StringIO()

    JsonAuditLog(stream=stream).record(_transacciones_event("**** 4321", ("TX-000001",)))

    raw = stream.getvalue()
    assert raw.count("\n") == 1
    data = json.loads(raw)
    assert data["tool"] == "consultar_transacciones"
    assert data["masked_card"] == "**** 4321"
    assert data["date_from"] == "2026-01-01"
    assert data["date_to"] == "2026-01-31"
    assert data["transaction_ids"] == ["TX-000001"]
    assert not re.search(r"\d{13,19}", raw)
    assert capsys.readouterr().out == ""


# Regla: RN-003-15 — la tarjeta enmascarada queda vacía si `card_last4` no es válido (borde: sin clave en la línea).  # noqa: E501
# AC-003-17 · Art. 8
def test_ac_003_17_event_without_masked_card_omits_optional_keys() -> None:
    """AC-003-17: sin tarjeta, rango ni transacciones, la línea omite esas claves."""
    stream = io.StringIO()

    JsonAuditLog(stream=stream).record(_transacciones_event(None, ()))

    data = json.loads(stream.getvalue())
    for key in ("masked_card", "date_from", "date_to", "transaction_ids"):
        assert key not in data


def _disputa_event(with_fields: bool) -> AuditEvent:
    return AuditEvent(
        conversation_id="conv-4",
        timestamp=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        tool="iniciar_disputa",
        input=None,
        outcome="created" if with_fields else "rejected",
        count=None,
        customer_ids=(),
        error_code=None,
        rule=None,
        reason=None,
        customer_id="C-0001",
        transaction_id="[REDACTED]" if with_fields else None,
        dispute_reason="fraude" if with_fields else None,
        idempotency_key="key-1" if with_fields else None,
        dispute_id="D-000001" if with_fields else None,
    )


# Regla: RN-004-16 — la auditoría de iniciar_disputa no incluye PAN ni documento; el transaction_id va redactado.  # noqa: E501
# AC-004-17 · Art. 8
def test_ac_004_17_iniciar_disputa_event_is_serialized_without_pan(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-004-17: línea JSON con los campos de disputa, sin PAN ni documento y nada en stdout."""
    stream = io.StringIO()

    JsonAuditLog(stream=stream).record(_disputa_event(with_fields=True))

    raw = stream.getvalue()
    assert raw.count("\n") == 1
    data = json.loads(raw)
    assert data["tool"] == "iniciar_disputa"
    assert data["transaction_id"] == "[REDACTED]"
    assert data["dispute_reason"] == "fraude"
    assert data["idempotency_key"] == "key-1"
    assert data["dispute_id"] == "D-000001"
    assert not re.search(r"\d{13,19}", raw)
    assert capsys.readouterr().out == ""


# Regla: RN-004-16 — sin los campos de disputa (borde: todos a None), la línea omite las claves.
# AC-004-17 · Art. 8
def test_ac_004_17_event_without_dispute_fields_omits_keys() -> None:
    """AC-004-17: con los campos de disputa a None, la línea no trae sus claves."""
    stream = io.StringIO()

    JsonAuditLog(stream=stream).record(_disputa_event(with_fields=False))

    data = json.loads(stream.getvalue())
    for key in ("transaction_id", "dispute_reason", "idempotency_key", "dispute_id"):
        assert key not in data
