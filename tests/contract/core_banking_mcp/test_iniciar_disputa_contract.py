"""Contrato de `iniciar_disputa`: esquemas MCP y sobre de error (spec 004 §7)."""

from typing import Any

from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    ErrorCode,
    IniciarDisputaIn,
    IniciarDisputaOut,
    ToolErrorOut,
    TransactionItemOut,
)

_REASONS = {
    "UNRECOGNIZED_CHARGE",
    "DUPLICATE_CHARGE",
    "INCORRECT_AMOUNT",
    "NOT_RECEIVED",
    "OTHER",
}

_ERROR_CODES = {
    "INVALID_INPUT",
    "IDENTITY_NOT_VERIFIED",
    "NOT_FOUND",
    "TRANSACTION_NOT_DISPUTABLE",
    "DISPUTE_ALREADY_OPEN",
    "CARD_NOT_BLOCKABLE",
    "INTERNAL",
}


# Regla: RN-004-12 — la respuesta contiene solo dispute_id, status, opened_at, reason y
#   transaction (con los campos de TransactionItem).
# Regla: RN-004-13 — la respuesta nunca contiene el número completo de la tarjeta, el documento
#   ni el nombre del cliente.
# AC-004-15 · Art. 7 (datos mínimos)
def test_ac_004_15_iniciar_disputa__output_schema__has_exactly_spec_fields() -> None:
    """AC-004-15: salida cerrada con los 5 campos de la spec; transaction es TransactionItem."""
    schema = IniciarDisputaOut.model_json_schema()
    assert set(schema["properties"]) == {
        "dispute_id",
        "status",
        "opened_at",
        "reason",
        "transaction",
    }
    assert schema["additionalProperties"] is False
    status = schema["properties"]["status"]
    assert status.get("const", status.get("enum")) in ("OPEN", ["OPEN"])
    assert all("description" in p for p in schema["properties"].values())
    assert schema["properties"]["transaction"]["$ref"].endswith("/TransactionItemOut")
    item: dict[str, Any] = schema["$defs"]["TransactionItemOut"]
    assert item == TransactionItemOut.model_json_schema()


# Regla: RN-004-02 — el motivo es un código de un catálogo cerrado de 5 valores.
# AC-004-02 · Art. 7 (contrato cerrado)
def test_ac_004_02_iniciar_disputa__output_enums__are_closed() -> None:
    """AC-004-02: reason admite solo los 5 códigos en la salida."""
    props = IniciarDisputaOut.model_json_schema()["properties"]
    assert set(props["reason"]["enum"]) == _REASONS


# Regla: RN-004-02 — motivo fuera del catálogo ⇒ INVALID_INPUT; el enum se publica al LLM.
# Regla: RN-004-09 — la entrada declara conversation_id, transaction_id, reason e
#   idempotency_key, todos documentados.
# AC-004-03 · Art. 8 (conversation_id obligatorio)
def test_ac_004_03_iniciar_disputa__input_schema__publishes_reason_enum() -> None:
    """AC-004-03: la entrada tiene 4 campos con description y reason publica el enum."""
    schema = IniciarDisputaIn.model_json_schema()
    assert set(schema["properties"]) == {
        "conversation_id",
        "transaction_id",
        "reason",
        "idempotency_key",
    }
    assert all("description" in p for p in schema["properties"].values())
    assert set(schema["properties"]["reason"]["enum"]) == _REASONS


# Regla: RN-004-05 — una transacción PENDING o REVERSED se rechaza con
#   TRANSACTION_NOT_DISPUTABLE.
# AC-004-04 · Art. 7 (catálogo cerrado)
def test_ac_004_04_iniciar_disputa__error_catalog__includes_transaction_not_disputable() -> None:
    """AC-004-04: ErrorCode contiene TRANSACTION_NOT_DISPUTABLE y el catálogo es cerrado."""
    assert ErrorCode.TRANSACTION_NOT_DISPUTABLE.value == "TRANSACTION_NOT_DISPUTABLE"
    assert {c.value for c in ErrorCode} == _ERROR_CODES


# Regla: RN-004-07 — con una disputa OPEN sobre la transacción se rechaza con
#   DISPUTE_ALREADY_OPEN.
# AC-004-07 · Art. 7 (catálogo cerrado)
def test_ac_004_07_iniciar_disputa__error_catalog__includes_dispute_already_open() -> None:
    """AC-004-07: ErrorCode contiene DISPUTE_ALREADY_OPEN y el catálogo es cerrado."""
    assert ErrorCode.DISPUTE_ALREADY_OPEN.value == "DISPUTE_ALREADY_OPEN"
    assert {c.value for c in ErrorCode} == _ERROR_CODES


# Regla: RN-004-04 — transacción ajena o inexistente ⇒ NOT_FOUND con mensaje fijo.
# Regla: RN-004-13 — la respuesta no filtra datos de otros clientes.
# AC-004-11 · Art. 7 (sin filtrar existencia de transacciones ajenas)
def test_ac_004_11_iniciar_disputa__error_catalog__includes_not_found() -> None:
    """AC-004-11: ErrorCode contiene NOT_FOUND."""
    assert ErrorCode.NOT_FOUND.value == "NOT_FOUND"
    assert {c.value for c in ErrorCode} == _ERROR_CODES


# Regla: RN-004-09 — toda violación de la validación de entrada es INVALID_INPUT, con el sobre
#   {code, message, retryable}.
# AC-004-13 · Art. 10 (sobre de error)
def test_ac_004_13_iniciar_disputa__error_envelope__has_code_message_retryable() -> None:
    """AC-004-13: ToolErrorOut conserva code, message y retryable."""
    schema = ToolErrorOut.model_json_schema()
    assert set(schema["properties"]) == {"code", "message", "retryable"}
    assert ErrorCode.INVALID_INPUT.value == "INVALID_INPUT"


# Regla: RN-004-15 — una falla inesperada es INTERNAL con retryable = false, sin detalles.
# AC-004-16 · Art. 10 (sobre de error)
def test_ac_004_16_iniciar_disputa__error_envelope__supports_internal_not_retryable() -> None:
    """AC-004-16: ToolErrorOut admite INTERNAL con retryable = false."""
    err = ToolErrorOut(code=ErrorCode.INTERNAL, message="Error interno.", retryable=False)
    assert err.code is ErrorCode.INTERNAL
    assert err.retryable is False
    assert set(ToolErrorOut.model_json_schema()["properties"]) == {"code", "message", "retryable"}


# Regla: RN-007-30 — `TransactionItem` (RN-003-12) incorpora `merchant_country`: el código ISO 3166-1 alfa-2 del país del comercio, en mayúsculas (`CO` = Colombia).  # noqa: E501
# AC-007-33 · Art. 7 (datos mínimos)
def test_ac_007_33_iniciar_disputa__transaction_schema__has_merchant_country() -> None:
    """AC-007-33: la transacción de la disputa incluye merchant_country y es un esquema cerrado."""
    item: dict[str, Any] = IniciarDisputaOut.model_json_schema()["$defs"]["TransactionItemOut"]
    assert "merchant_country" in item["properties"]
    assert item["additionalProperties"] is False
