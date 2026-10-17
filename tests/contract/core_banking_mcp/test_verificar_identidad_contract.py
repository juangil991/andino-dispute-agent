"""Contrato de `verificar_identidad`: esquemas MCP y sobre de error (spec 002 §7)."""

import pytest
from pydantic import ValidationError

from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    ErrorCode,
    ToolErrorOut,
    VerificarIdentidadIn,
    VerificarIdentidadOut,
)


# Regla: RN-002-14 — la salida expone solo verified, attempts_remaining y escalation_required.
# AC-002-14 · Art. 7 (datos mínimos)
def test_ac_002_14_output_schema_has_exactly_three_fields() -> None:
    """AC-002-14: la salida tiene exactamente 3 campos y no admite extras."""
    schema = VerificarIdentidadOut.model_json_schema()
    assert set(schema["properties"]) == {"verified", "attempts_remaining", "escalation_required"}
    assert schema["additionalProperties"] is False
    assert all("description" in p for p in schema["properties"].values())


# Regla: RN-002-04 — attempts_remaining en rango 0–3 (parte de la regla que valida el esquema);
#   bordes 0 y 3.
# AC-002-05 · Art. 10 (límite de intentos)
@pytest.mark.parametrize("value", [0, 3], ids=["lower_bound_0", "upper_bound_3"])
def test_ac_002_05_attempts_remaining_accepts_bounds(value: int) -> None:
    """AC-002-05: attempts_remaining acepta 0 y 3."""
    out = VerificarIdentidadOut(verified=False, attempts_remaining=value, escalation_required=False)
    assert out.attempts_remaining == value


# Regla: RN-002-04 — attempts_remaining en rango 0–3 (parte de la regla que valida el esquema);
#   fuera de rango es inválido (bordes -1 y 4).
# AC-002-05 · Art. 10 (límite de intentos)
@pytest.mark.parametrize("value", [-1, 4], ids=["below_min_-1", "above_max_4"])
def test_ac_002_05_attempts_remaining_rejects_out_of_range(value: int) -> None:
    """AC-002-05: attempts_remaining rechaza -1 y 4."""
    with pytest.raises(ValidationError):
        VerificarIdentidadOut(verified=False, attempts_remaining=value, escalation_required=False)


# Regla: RN-002-01 — la solicitud de verificación lleva conversation_id, customer_id, birth_date y
#   document_issue_date: los 4 campos de entrada, todos documentados para el LLM.
# AC-002-01 · Art. 8 (conversation_id obligatorio)
def test_ac_002_01_input_schema_declares_four_described_fields() -> None:
    """AC-002-01: la entrada tiene los 4 campos de la spec, todos con description."""
    schema = VerificarIdentidadIn.model_json_schema()
    assert set(schema["properties"]) == {
        "conversation_id",
        "customer_id",
        "birth_date",
        "document_issue_date",
    }
    assert all("description" in p for p in schema["properties"].values())


# Regla: RN-002-07 — toda violación de la entrada es INVALID_INPUT (catálogo cerrado de códigos).
# Regla: RN-002-16 — una falla inesperada es INTERNAL con sobre {code, message, retryable}.
# AC-002-03 · AC-002-08 · AC-002-16 · Art. 10 (sobre de error)
def test_ac_002_16_error_envelope_matches_spec() -> None:
    """AC-002-03/AC-002-16: ToolErrorOut cumple el sobre y ErrorCode sigue cerrado."""
    schema = ToolErrorOut.model_json_schema()
    assert set(schema["properties"]) == {"code", "message", "retryable"}
    assert {c.value for c in ErrorCode} == {"INVALID_INPUT", "INTERNAL"}
