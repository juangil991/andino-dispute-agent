"""Pruebas del prompt del sistema del agente de disputas."""

from dispute_agent.application.system_prompt import SYSTEM_PROMPT


# Regla: RN-007-33 — El texto del LLM nunca se interpreta para ejecutar acciones ni para darlas
# por hechas.
# AC-007-39 · Art. 5
def test_ac_007_39_system_prompt__forbids_claiming_actions_outside_outcomes() -> None:
    """AC-007-39 / RN-007-33: el prompt prohíbe afirmar acciones fuera de `outcomes`."""
    assert "No afirmes al cliente ninguna acción que no figure en los outcomes" in SYSTEM_PROMPT


# Regla: RN-007-37 — Pedir que se bloquee la tarjeta sin declarar sospecha de fraude no es
# motivo para `reportar_fraude`.
# AC-007-44 · Art. 5
def test_ac_007_44_system_prompt__block_card_without_fraud_is_not_fraud_report() -> None:
    """AC-007-44 / RN-007-37: el prompt aclara que bloquear sin fraude no es reportar fraude."""
    assert (
        "Pedir que se bloquee la tarjeta sin declarar sospecha de fraude no es motivo para "
        "reportar_fraude"
    ) in SYSTEM_PROMPT
