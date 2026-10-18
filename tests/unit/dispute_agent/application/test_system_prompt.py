"""Pruebas del prompt del sistema del agente de disputas."""

from dispute_agent.application.system_prompt import SYSTEM_PROMPT


# Regla: RN-007-33 — El texto del LLM nunca se interpreta para ejecutar acciones ni para darlas
# por hechas.
# AC-007-39 · Art. 5
def test_ac_007_39_system_prompt__forbids_claiming_actions_outside_outcomes() -> None:
    """AC-007-39 / RN-007-33: el prompt prohíbe afirmar acciones fuera de `outcomes`."""
    assert "No afirmes al cliente ninguna acción que no figure en los outcomes" in SYSTEM_PROMPT
