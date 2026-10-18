"""Contrato de `bloquear_tarjeta`: esquemas MCP y sobre de error (spec 005 §7)."""

from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    BLOCK_REASON_CODES,
    BloquearTarjetaOut,
    ErrorCode,
    ToolErrorOut,
)

_REASONS = {"FRAUD_SUSPECTED", "LOST_OR_STOLEN"}

_ERROR_CODES = {
    "INVALID_INPUT",
    "IDENTITY_NOT_VERIFIED",
    "NOT_FOUND",
    "TRANSACTION_NOT_DISPUTABLE",
    "DISPUTE_ALREADY_OPEN",
    "CARD_NOT_BLOCKABLE",
    "INTERNAL",
}


# Regla: RN-005-10 — la respuesta contiene solo card_id, masked_card, status, blocked_at,
#   reason y already_blocked.
# Regla: RN-005-11 — la respuesta nunca contiene el número completo, el documento ni el nombre.
# AC-005-13 · AC-005-01 · Art. 7 (datos mínimos)
def test_ac_005_13_bloquear_tarjeta__output_schema__has_exactly_spec_fields() -> None:
    """AC-005-13: salida cerrada con los 6 campos de la spec (cumple AC-005-01)."""
    schema = BloquearTarjetaOut.model_json_schema()
    assert set(schema["properties"]) == {
        "card_id",
        "masked_card",
        "status",
        "blocked_at",
        "reason",
        "already_blocked",
    }
    assert schema["additionalProperties"] is False
    props = schema["properties"]
    assert all("description" in p for p in props.values())
    status = props["status"]
    assert status.get("const", status.get("enum")) in ("BLOCKED", ["BLOCKED"])
    assert props["already_blocked"]["type"] == "boolean"
    assert {"type": "string"} in props["blocked_at"]["anyOf"]
    assert {"type": "null"} in props["blocked_at"]["anyOf"]


# Regla: RN-005-02 — el motivo es un código de un catálogo cerrado de 2 valores.
# AC-005-02 · Art. 7 (contrato cerrado)
def test_ac_005_02_bloquear_tarjeta__output_enums__are_closed() -> None:
    """AC-005-02: reason admite solo los 2 códigos en la salida."""
    reason = BloquearTarjetaOut.model_json_schema()["properties"]["reason"]
    enums = {v for opt in reason["anyOf"] for v in opt.get("enum", ())}
    assert enums == _REASONS


# Regla: RN-005-02 — motivo fuera del catálogo ⇒ INVALID_INPUT; el enum se publica al LLM.
# AC-005-03 · Art. 8 (contrato publicado)
def test_ac_005_03_bloquear_tarjeta__reason_codes__are_the_two_spec_values() -> None:
    """AC-005-03: BLOCK_REASON_CODES contiene exactamente los 2 códigos."""
    assert set(BLOCK_REASON_CODES) == _REASONS
    assert len(BLOCK_REASON_CODES) == 2


# Regla: RN-005-05 — una tarjeta CANCELLED se rechaza con CARD_NOT_BLOCKABLE.
# Regla: RN-005-06 — sin bloqueo registrado, reason es null.
# AC-005-04 · Art. 7 (catálogo cerrado)
def test_ac_005_04_bloquear_tarjeta__error_catalog__includes_card_not_blockable() -> None:
    """AC-005-04: ErrorCode contiene CARD_NOT_BLOCKABLE; reason admite null (RN-005-06)."""
    reason = BloquearTarjetaOut.model_json_schema()["properties"]["reason"]
    assert {"type": "null"} in reason["anyOf"]
    assert ErrorCode.CARD_NOT_BLOCKABLE.value == "CARD_NOT_BLOCKABLE"
    assert {c.value for c in ErrorCode} == _ERROR_CODES


# Regla: RN-005-04 — tarjeta ajena o inexistente ⇒ NOT_FOUND con mensaje fijo.
# AC-005-08 · Art. 7 (sin filtrar existencia de tarjetas ajenas)
def test_ac_005_08_bloquear_tarjeta__error_catalog__includes_not_found() -> None:
    """AC-005-08: ErrorCode contiene NOT_FOUND."""
    assert ErrorCode.NOT_FOUND.value == "NOT_FOUND"
    assert {c.value for c in ErrorCode} == _ERROR_CODES


# Regla: RN-005-08 — toda violación de la validación de entrada es INVALID_INPUT, con el sobre
#   {code, message, retryable}.
# AC-005-10 · Art. 10 (sobre de error)
def test_ac_005_10_bloquear_tarjeta__error_envelope__has_code_message_retryable() -> None:
    """AC-005-10: ToolErrorOut conserva code, message y retryable."""
    schema = ToolErrorOut.model_json_schema()
    assert set(schema["properties"]) == {"code", "message", "retryable"}
    assert ErrorCode.INVALID_INPUT.value == "INVALID_INPUT"


# Regla: RN-005-13 — una falla inesperada es INTERNAL con retryable = false, sin detalles.
# AC-005-14 · Art. 10 (sobre de error)
def test_ac_005_14_bloquear_tarjeta__error_envelope__supports_internal_not_retryable() -> None:
    """AC-005-14: ToolErrorOut admite INTERNAL con retryable = false."""
    err = ToolErrorOut(code=ErrorCode.INTERNAL, message="Error interno.", retryable=False)
    assert err.code is ErrorCode.INTERNAL
    assert err.retryable is False
    assert set(ToolErrorOut.model_json_schema()["properties"]) == {"code", "message", "retryable"}
