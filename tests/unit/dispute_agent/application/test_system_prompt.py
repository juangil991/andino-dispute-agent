"""Pruebas del prompt del sistema del agente de disputas."""

from datetime import date

from dispute_agent.application.system_prompt import SYSTEM_PROMPT, build_decision_system


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


# Regla: RN-011-01 — el prompt de decisión declara el límite exacto y el rango por defecto.
# AC-011-01 · agent-behavior §17
def test_ac_011_01_decision_prompt__states_89_day_limit_and_default_date_from() -> None:
    """AC-011-01: el prompt dice 89 días, 90 con ambos extremos y date_from = hoy - 89."""
    prompt = build_decision_system(date(2026, 10, 19))
    assert "89 días después de `date_from` (90 días contando ambos extremos)" in prompt
    assert "`date_from` es `hoy - 89`" in prompt
    assert "`date_to` es hoy" in prompt
    assert "últimos 90 días" not in prompt.replace("últimos 90 días contando ambos extremos", "")
