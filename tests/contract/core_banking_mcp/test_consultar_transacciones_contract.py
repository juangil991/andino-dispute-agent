"""Contrato de `consultar_transacciones`: esquemas MCP y sobre de error (spec 003 §7)."""

from typing import Any

from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    ConsultarTransaccionesIn,
    ConsultarTransaccionesOut,
    ErrorCode,
    ToolErrorOut,
    TransactionItemOut,
)

_ITEM_FIELDS = {
    "transaction_id",
    "occurred_at",
    "merchant",
    "amount",
    "currency",
    "status",
    "card_id",
    "masked_card",
    "merchant_country",
}


def _item_schema() -> dict[str, Any]:
    defs: dict[str, Any] = ConsultarTransaccionesOut.model_json_schema()["$defs"]
    item: dict[str, Any] = defs["TransactionItemOut"]
    return item


# Regla: RN-003-12 — cada transacción devuelta contiene solo: transaction_id, occurred_at,
#   merchant, amount, currency, status, card_id y masked_card.
# Regla: RN-003-13 — la respuesta nunca contiene el número completo de ninguna tarjeta, el
#   documento del cliente ni su nombre, ni datos de otros clientes.
# AC-003-14 · Art. 7 (datos mínimos)
def test_ac_003_14_consultar_transacciones__output_schema__has_exactly_spec_fields() -> None:
    """AC-003-14: salida con transactions y refinement_required; ítem con los 9 campos."""
    out_schema = ConsultarTransaccionesOut.model_json_schema()
    assert set(out_schema["properties"]) == {"transactions", "refinement_required"}
    assert out_schema["additionalProperties"] is False
    item = TransactionItemOut.model_json_schema()
    assert set(item["properties"]) == _ITEM_FIELDS
    assert item["additionalProperties"] is False
    assert all("description" in p for p in item["properties"].values())


# Regla: RN-003-09 — se devuelven transacciones en cualquier estado: confirmada (CONFIRMED),
#   pendiente (PENDING) o reversada (REVERSED).
# AC-003-03 · Art. 7 (contrato cerrado)
def test_ac_003_03_consultar_transacciones__status_enum__is_closed_to_three_values() -> None:
    """AC-003-03: status admite solo CONFIRMED, PENDING y REVERSED."""
    status = _item_schema()["properties"]["status"]
    assert set(status["enum"]) == {"CONFIRMED", "PENDING", "REVERSED"}


# Regla: RN-003-10 — tope de 50 transacciones; con más de 50 la respuesta no trae transacciones
#   y refinement_required = true (el esquema limita la lista a 50; borde 50).
# AC-003-08 · Art. 7 (tope de resultados)
def test_ac_003_08_consultar_transacciones__transactions__max_items_is_50() -> None:
    """AC-003-08: transactions tiene maxItems 50."""
    props = ConsultarTransaccionesOut.model_json_schema()["properties"]
    assert props["transactions"]["maxItems"] == 50


# Regla: RN-003-09 — el monto es siempre el original y positivo; la reversión se ve solo en el
#   estado.
# Regla: RN-003-12 — amount es texto decimal positivo con 2 decimales y currency código ISO 4217.
# AC-003-16 · Art. 7 (formato del contrato)
def test_ac_003_16_consultar_transacciones__amount_and_currency__are_strings() -> None:
    """AC-003-16: amount y currency se declaran como string."""
    props = _item_schema()["properties"]
    assert props["amount"]["type"] == "string"
    assert props["currency"]["type"] == "string"


# Regla: RN-003-06 — validación de entrada: conversation_id, card_last4, date_from y date_to
#   son los campos de entrada del esquema, todos obligatorios y documentados para el LLM.
# AC-003-09 · Art. 8 (conversation_id obligatorio)
def test_ac_003_09_consultar_transacciones__input_schema__declares_four_described_fields() -> None:
    """AC-003-09: la entrada tiene los 4 campos de la spec, todos con description."""
    schema = ConsultarTransaccionesIn.model_json_schema()
    assert set(schema["properties"]) == {
        "conversation_id",
        "card_last4",
        "date_from",
        "date_to",
    }
    assert all("description" in p for p in schema["properties"].values())


# Regla: RN-003-02 — una conversación sin verificación exitosa se rechaza con
#   IDENTITY_NOT_VERIFIED.
# AC-003-11 · Art. 7 (sin identificación no hay datos)
def test_ac_003_11_consultar_transacciones__error_catalog__includes_identity_not_verified() -> None:
    """AC-003-11: ErrorCode contiene IDENTITY_NOT_VERIFIED y el catálogo es cerrado."""
    assert ErrorCode.IDENTITY_NOT_VERIFIED.value == "IDENTITY_NOT_VERIFIED"
    assert {c.value for c in ErrorCode} == {
        "INVALID_INPUT",
        "IDENTITY_NOT_VERIFIED",
        "NOT_FOUND",
        "TRANSACTION_NOT_DISPUTABLE",
        "DISPUTE_ALREADY_OPEN",
        "CARD_NOT_BLOCKABLE",
        "INTERNAL",
    }


# Regla: RN-003-04 — si el cliente verificado no tiene ninguna tarjeta terminada en card_last4
#   se devuelve NOT_FOUND con un mensaje fijo, idéntico en ambos casos.
# AC-003-13 · Art. 7 (sin filtrar existencia de tarjetas ajenas)
def test_ac_003_13_consultar_transacciones__error_catalog__includes_not_found() -> None:
    """AC-003-13: ErrorCode contiene NOT_FOUND."""
    assert ErrorCode.NOT_FOUND.value == "NOT_FOUND"


# Regla: RN-003-06 — toda violación de la validación de entrada es INVALID_INPUT.
# Regla: RN-003-16 — una falla inesperada es INTERNAL con retryable = false.
# AC-003-09 · AC-003-18 · Art. 10 (sobre de error)
def test_ac_003_18_consultar_transacciones__error_envelope__has_code_message_retryable() -> None:
    """AC-003-09/AC-003-18: ToolErrorOut conserva code, message y retryable."""
    schema = ToolErrorOut.model_json_schema()
    assert set(schema["properties"]) == {"code", "message", "retryable"}


# Regla: RN-007-30 — `TransactionItem` (RN-003-12) incorpora `merchant_country`: el código ISO 3166-1 alfa-2 del país del comercio, en mayúsculas (`CO` = Colombia).  # noqa: E501
# AC-007-33 · Art. 7 (datos mínimos)
def test_ac_007_33_consultar_transacciones__item_schema__has_merchant_country() -> None:
    """AC-007-33: el ítem cerrado incluye merchant_country (string) con descripción."""
    item = TransactionItemOut.model_json_schema()
    assert item["properties"]["merchant_country"]["type"] == "string"
    assert item["properties"]["merchant_country"]["description"]
    assert item["additionalProperties"] is False
    assert _item_schema() == item
