"""Contrato de `buscar_cliente`: esquemas MCP y sobre de error (spec 001 §7)."""

import json

from mcp.types import TextContent

from core_banking_mcp.infrastructure.inbound.mcp.errors import tool_error
from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    BuscarClienteOut,
    CustomerMatchOut,
    ErrorCode,
    ToolErrorOut,
)


# Regla: RN-001-08 — cada cliente expone solo id, nombre, documento y tarjetas enmascarados.
# AC-001-01 · Art. 1 (datos mínimos)
def test_ac_001_01_customer_match_schema_has_exactly_spec_fields() -> None:
    """AC-001-01: CustomerMatch tiene exactamente los campos de la spec y no admite extras."""
    schema = CustomerMatchOut.model_json_schema()
    assert set(schema["properties"]) == {
        "customer_id",
        "full_name",
        "masked_document",
        "masked_cards",
    }
    assert schema["additionalProperties"] is False
    assert all("description" in p for p in schema["properties"].values())


# Regla: RN-001-10 — la respuesta no incluye token ni indicador de verificación.
# AC-001-10 · Art. 7 (buscar no confirma identidad)
def test_ac_001_10_output_schema_has_no_identity_fields() -> None:
    """AC-001-10: la salida solo tiene `customers` y `refinement_required`."""
    schema = BuscarClienteOut.model_json_schema()
    assert set(schema["properties"]) == {"customers", "refinement_required"}


# Regla: RN-001-05 — entradas inválidas responden con error estructurado.
# AC-001-09 · Art. 10 (sobre de error {code, message, retryable})
def test_ac_001_09_error_envelope_matches_spec() -> None:
    """AC-001-09: ToolErrorOut tiene code/message/retryable y ErrorCode es cerrado."""
    schema = ToolErrorOut.model_json_schema()
    assert set(schema["properties"]) == {"code", "message", "retryable"}
    assert {c.value for c in ErrorCode} == {
        "INVALID_INPUT",
        "IDENTITY_NOT_VERIFIED",
        "NOT_FOUND",
        "INTERNAL",
    }


# Regla: RN-001-05 — el error viaja con isError y el mismo JSON en structuredContent y texto.
# AC-001-09 · Art. 10 (riesgo plan §7)
def test_ac_001_09_tool_error_result_is_error_with_structured_and_text() -> None:
    """AC-001-09: tool_error devuelve isError=True con sobre estructurado y texto idéntico."""
    result = tool_error(ErrorCode.INVALID_INPUT, "Entrada inválida.", retryable=False)
    expected = {"code": "INVALID_INPUT", "message": "Entrada inválida.", "retryable": False}
    assert result.isError is True
    assert result.structuredContent == expected
    assert len(result.content) == 1
    block = result.content[0]
    assert isinstance(block, TextContent)
    assert json.loads(block.text) == expected
