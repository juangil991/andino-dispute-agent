"""Instrucciones de redacción de la respuesta (spec 009, RN-009-03)."""

import json

from dispute_agent.application.system_prompt import (
    REPLY_DRAFTING_PROMPT,
    SYSTEM_PROMPT,
    build_drafting_system,
)
from dispute_agent.domain.models.outcome import Outcome, OutcomeKind


def _outcome() -> Outcome:
    return Outcome(
        kind=OutcomeKind.DISPUTE_OPENED,
        rule="RN-001",
        reason="Abrimos tu disputa.",
        next_steps="Te avisaremos en 5 días.",
        masked_card="****4321",
        reference="DSP-1",
    )


# Regla: RN-009-05 — la redacción no afirma ni ejecuta acciones que no figuren en los `outcomes`.
# AC-009-04 · Art. 5
def test_ac_009_04_drafting_prompt_forbids_claiming_actions_outside_outcomes() -> None:
    """AC-009-04: el prompt exige español, solo outcomes y sin números completos."""
    prompt = REPLY_DRAFTING_PROMPT
    assert "español" in prompt
    assert "outcomes" in prompt
    assert "no figure" in prompt
    assert "4 dígitos" in prompt
    assert "no puedes pedir ni ejecutar acciones" in prompt

    system = build_drafting_system([_outcome()])
    assert system.startswith(REPLY_DRAFTING_PROMPT)
    payload = system[len(REPLY_DRAFTING_PROMPT) :]
    start = payload.index("[")
    assert json.loads(payload[start:]) == [
        {
            "kind": "DISPUTE_OPENED",
            "rule": "RN-001",
            "reason": "Abrimos tu disputa.",
            "next_steps": "Te avisaremos en 5 días.",
            "masked_card": "****4321",
            "reference": "DSP-1",
        }
    ]


# Regla: soporte de pruebas — el SYSTEM_PROMPT del ciclo de decisión no cambia con la redacción.
# Soporte de tests · Art. 5
def test_ac_009_03_drafting_system_does_not_change_agent_prompt() -> None:
    """SYSTEM_PROMPT del ciclo de decisión no cambia."""
    assert "Eres el agente de disputas" in SYSTEM_PROMPT
    assert build_drafting_system([]).endswith("[]")


# Regla: RN-009-03 — la redacción no escribe llamadas a herramientas ni registros internos.
# AC-009-31 · Art. 5
def test_drafting_prompt__forbids_tool_call_text() -> None:
    assert "<datos_internos>" in REPLY_DRAFTING_PROMPT
    assert "nunca escribas llamadas a herramientas" in REPLY_DRAFTING_PROMPT


# Regla: RN-007-44 — el prompt de decisión lleva la fecha actual para armar rangos de consultas.
# AC-007-58 · Art. 3
def test_build_decision_system__includes_today() -> None:
    from datetime import date

    from dispute_agent.application.system_prompt import build_decision_system

    assert "Fecha actual: 2026-03-22" in build_decision_system(date(2026, 3, 22))
