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


def _bloqueo_event(with_fields: bool) -> AuditEvent:
    return AuditEvent(
        conversation_id="conv-5",
        timestamp=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        tool="bloquear_tarjeta",
        input=None,
        outcome="blocked" if with_fields else "rejected",
        count=None,
        customer_ids=(),
        error_code=None,
        rule=None,
        reason=None,
        customer_id="C-0001",
        masked_card="**** 4321" if with_fields else None,
        idempotency_key="key-1" if with_fields else None,
        card_id="[REDACTED]" if with_fields else None,
        block_reason="FRAUD_SUSPECTED" if with_fields else None,
    )


# Regla: RN-005-14 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "bloquear_tarjeta"`; el `card_id`, el `reason` y la `idempotency_key` recibidos (cada uno vacío si no es válido según RN-005-08, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); y el resultado. El resultado es `blocked`, `replayed`, `already_blocked` o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `CARD_NOT_BLOCKABLE`, `INTERNAL`). Como `card_id` e `idempotency_key` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente.  # noqa: E501
# AC-005-15 · Art. 8
def test_ac_005_15_bloquear_tarjeta__event_with_block_fields__serialized_without_pan(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-005-15: línea JSON con los campos de bloqueo, sin PAN ni documento y nada en stdout."""
    stream = io.StringIO()

    JsonAuditLog(stream=stream).record(_bloqueo_event(with_fields=True))

    raw = stream.getvalue()
    assert raw.count("\n") == 1
    data = json.loads(raw)
    assert data["tool"] == "bloquear_tarjeta"
    assert data["card_id"] == "[REDACTED]"
    assert data["block_reason"] == "FRAUD_SUSPECTED"
    assert data["idempotency_key"] == "key-1"
    assert data["masked_card"] == "**** 4321"
    assert not re.search(r"\d{13,19}", raw)
    assert capsys.readouterr().out == ""


# Regla: RN-005-14 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "bloquear_tarjeta"`; el `card_id`, el `reason` y la `idempotency_key` recibidos (cada uno vacío si no es válido según RN-005-08, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); y el resultado. El resultado es `blocked`, `replayed`, `already_blocked` o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `CARD_NOT_BLOCKABLE`, `INTERNAL`). Como `card_id` e `idempotency_key` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente.  # noqa: E501
# Borde: `card_id` y `reason` vacíos (None) — la línea JSON omite esas claves.
# AC-005-15 · Art. 8
def test_ac_005_15_bloquear_tarjeta__event_without_block_fields__omits_keys() -> None:
    """AC-005-15: con card_id y block_reason a None, la línea no trae esas claves."""
    stream = io.StringIO()

    JsonAuditLog(stream=stream).record(_bloqueo_event(with_fields=False))

    data = json.loads(stream.getvalue())
    assert "card_id" not in data
    assert "block_reason" not in data


# Regla: RN-001-12 — los eventos de 001–004 no ganan claves nuevas (regresión).
# AC-004-17 · Art. 8
def test_ac_004_17_existing_events_keep_their_keys() -> None:
    """AC-004-17: la línea de iniciar_disputa no incluye card_id ni block_reason."""
    stream = io.StringIO()

    JsonAuditLog(stream=stream).record(_disputa_event(with_fields=True))

    data = json.loads(stream.getvalue())
    assert "card_id" not in data
    assert "block_reason" not in data


def _escalacion_event(with_fields: bool) -> AuditEvent:
    return AuditEvent(
        conversation_id="conv-6",
        timestamp=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        tool="escalar_a_analista",
        input=None,
        outcome="escalated" if with_fields else "INVALID_INPUT",
        count=None,
        customer_ids=(),
        error_code=None,
        rule=None,
        reason=None,
        masked_card="**** 4321" if with_fields else None,
        idempotency_key="key-1" if with_fields else None,
        card_id="[REDACTED]" if with_fields else None,
        escalation_reason="FRAUD_SUSPECTED" if with_fields else None,
        escalation_id="ESC-000001" if with_fields else None,
        note="tarjeta [REDACTED]" if with_fields else None,
        prior_actions=("DISPUTE_OPENED", "CARD_BLOCKED") if with_fields else (),
        identity_verified=False if with_fields else None,
    )


# Regla: RN-006-16 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "escalar_a_analista"`; el `reason`, la `idempotency_key`, el `transaction_id`, el `card_id`, el `dispute_id`, las `prior_actions` y la `note` recibidos (cada uno vacío si no llegó o no es válido según RN-006-10, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); `identity_verified` (si la conversación estaba verificada); y el resultado. El resultado es `escalated` con el `escalation_id` creado, `replayed` con el `escalation_id` existente, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INTERNAL`). Como `idempotency_key`, `transaction_id`, `card_id`, `dispute_id` y `note` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente.  # noqa: E501
# AC-006-20 · Art. 8
def test_ac_006_20_json_audit_log__escalation_event__serialized_without_pan(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-006-20: línea JSON con los campos de derivación, sin PAN ni documento y sin stdout."""
    stream = io.StringIO()

    JsonAuditLog(stream=stream).record(_escalacion_event(with_fields=True))

    raw = stream.getvalue()
    assert raw.count("\n") == 1
    data = json.loads(raw)
    assert data["tool"] == "escalar_a_analista"
    assert data["escalation_reason"] == "FRAUD_SUSPECTED"
    assert data["escalation_id"] == "ESC-000001"
    assert data["prior_actions"] == ["DISPUTE_OPENED", "CARD_BLOCKED"]
    assert data["note"] == "tarjeta [REDACTED]"
    assert data["card_id"] == "[REDACTED]"
    assert data["idempotency_key"] == "key-1"
    assert data["masked_card"] == "**** 4321"
    assert data["identity_verified"] is False
    assert not re.search(r"\d{13,19}", raw)
    assert capsys.readouterr().out == ""


# Regla: RN-006-16 — Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "escalar_a_analista"`; el `reason`, la `idempotency_key`, el `transaction_id`, el `card_id`, el `dispute_id`, las `prior_actions` y la `note` recibidos (cada uno vacío si no llegó o no es válido según RN-006-10, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); `identity_verified` (si la conversación estaba verificada); y el resultado. El resultado es `escalated` con el `escalation_id` creado, `replayed` con el `escalation_id` existente, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INTERNAL`). Como `idempotency_key`, `transaction_id`, `card_id`, `dispute_id` y `note` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente.  # noqa: E501
# Borde: campos nuevos a None y prior_actions vacío — la línea omite esas claves.
# AC-006-20 · Art. 8
def test_ac_006_20_json_audit_log__escalation_event_without_optional_fields__omits_keys() -> None:
    """AC-006-20: sin campos de derivación, la línea no trae sus claves; 001–005 no cambian."""
    stream = io.StringIO()

    JsonAuditLog(stream=stream).record(_escalacion_event(with_fields=False))
    JsonAuditLog(stream=stream).record(_disputa_event(with_fields=True))

    lines = stream.getvalue().splitlines()
    escalation_line = json.loads(lines[0])
    dispute_line = json.loads(lines[1])
    new_keys = (
        "escalation_reason",
        "escalation_id",
        "note",
        "prior_actions",
        "identity_verified",
    )
    for key in new_keys:
        assert key not in escalation_line
        assert key not in dispute_line


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
