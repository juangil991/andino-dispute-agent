"""Herramientas visibles al LLM y prompt del sistema (T-007-13)."""

from dispute_agent.application.agent_tools import LLM_TOOLS, WRITE_TOOLS
from dispute_agent.application.system_prompt import SYSTEM_PROMPT

EXPECTED = {
    "buscar_cliente",
    "verificar_identidad",
    "consultar_transacciones",
    "evaluar_disputa",
    "reportar_fraude",
    "solicitar_atencion_humana",
}


# Soporte de tests: catálogo de herramientas visibles al LLM · Art. 3
def test_llm_sees_exactly_six_tools() -> None:
    """El LLM ve exactamente 6 herramientas."""
    assert {t.name for t in LLM_TOOLS} == EXPECTED
    assert len(LLM_TOOLS) == 6


# Soporte de tests: esquemas válidos, sin conversation_id ni customer_id · Art. 3
def test_tool_schemas_are_valid_and_hide_injected_fields() -> None:
    """JSON Schema objeto estricto sin campos inyectados."""
    for tool in LLM_TOOLS:
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        props = schema["properties"]
        assert isinstance(props, dict)
        assert "conversation_id" not in props
        assert "customer_id" not in props
        assert tool.description
    by_name = {t.name: t.input_schema for t in LLM_TOOLS}
    assert set(by_name["verificar_identidad"]["properties"]) == {  # type: ignore[call-overload]
        "birth_date",
        "document_issue_date",
    }
    assert by_name["verificar_identidad"]["required"] == [
        "birth_date",
        "document_issue_date",
    ]
    assert by_name["solicitar_atencion_humana"]["properties"] == {}


# Soporte de tests: herramientas de escritura no expuestas · Art. 3
def test_write_tools_not_exposed() -> None:
    """Soporte de AC-007-25: WRITE_TOOLS reconocidas pero no visibles."""
    assert frozenset({"iniciar_disputa", "bloquear_tarjeta", "escalar_a_analista"}) == WRITE_TOOLS
    assert not WRITE_TOOLS & {t.name for t in LLM_TOOLS}


# Soporte de tests: contenido del prompt · Art. 3
def test_system_prompt_content() -> None:
    """Soporte de RN-007-27: prompt en español, datos no instrucciones, sin tarjetas."""
    lowered = SYSTEM_PROMPT.lower()
    assert "banco andino" in lowered
    assert "datos" in lowered and "instrucciones" in lowered
    assert "número" in lowered and "tarjeta" in lowered
    for name in EXPECTED - {"buscar_cliente", "verificar_identidad", "consultar_transacciones"}:
        assert name in SYSTEM_PROMPT


# Regla: RN-007-37 — Pedir que se bloquee la tarjeta sin declarar sospecha de fraude no es
# motivo para `reportar_fraude`.
# AC-007-44 · Art. 5
def test_ac_007_44_agent_tools__report_fraud_description_excludes_block_card_without_fraud() -> (
    None
):
    """AC-007-44 / RN-007-37: la descripción de reportar_fraude incluye la frase acordada."""
    spec = next(t for t in LLM_TOOLS if t.name == "reportar_fraude")
    assert (
        "Pedir que se bloquee la tarjeta sin declarar sospecha de fraude no es motivo para "
        "reportar_fraude"
    ) in spec.description
