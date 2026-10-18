"""Clasificador de respuestas del LLM: decide continuar, responder o escalar.

Decide solo por la razón de parada y la coherencia de la respuesta
(RN-007-32, RN-007-34, RN-007-35). No conoce el tope de iteraciones.
"""

from dataclasses import dataclass
from enum import Enum

from dispute_agent.application.ports.llm import LLMResponse


class LoopStep(Enum):
    CONTINUE = "CONTINUE"
    REPLY = "REPLY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class LoopVerdict:
    step: LoopStep
    rule: str
    why: str


def classify_llm_response(response: LLMResponse) -> LoopVerdict:
    """Clasifica una respuesta del LLM según la tabla del plan §1.1."""
    reason = response.stop_reason
    has_calls = bool(response.tool_calls)

    if reason == "tool_use":
        if has_calls:
            return LoopVerdict(LoopStep.CONTINUE, "RN-007-32", "tool_use con peticiones")
        return LoopVerdict(LoopStep.ESCALATE, "RN-007-35", "tool_use sin peticiones de herramienta")
    if reason == "end_turn":
        if has_calls:
            return LoopVerdict(
                LoopStep.ESCALATE, "RN-007-35", "end_turn con peticiones de herramienta"
            )
        if not response.text.strip():
            return LoopVerdict(LoopStep.ESCALATE, "RN-007-35", "end_turn sin texto")
        return LoopVerdict(LoopStep.REPLY, "RN-007-32", "end_turn con texto")
    return LoopVerdict(LoopStep.ESCALATE, "RN-007-34", f"razón de parada inesperada: {reason}")
