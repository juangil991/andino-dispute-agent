"""Tests del clasificador de respuestas del LLM (`classify_llm_response`)."""

import pytest

from dispute_agent.application.loop_control import (
    LoopStep,
    LoopVerdict,
    classify_draft_end,
    classify_llm_response,
)
from dispute_agent.application.ports.llm import LLMResponse, LLMStreamEnd, ToolCall

_CALL = ToolCall(id="call-1", name="consultar_transacciones", arguments={})


# Regla: RN-007-34 — Una razón de parada distinta de `tool_use` y `end_turn` es una salida inválida.
# AC-007-40 · Art. 10
@pytest.mark.parametrize("with_calls", [False, True], ids=["sin_peticiones", "con_peticiones"])
@pytest.mark.parametrize(
    "stop_reason",
    ["max_tokens", "refusal", "pause_turn", "stop_sequence", "other_reason", None],
    ids=["max_tokens", "refusal", "pause_turn", "stop_sequence", "other_reason", "ausente"],
)
def test_ac_007_40_loop_control__unexpected_stop_reason__escalate(
    stop_reason: str | None, with_calls: bool
) -> None:
    """AC-007-40: una razón de parada inesperada o ausente escala (RN-007-34)."""
    response = LLMResponse(
        text="Ya abrí tu disputa.",
        tool_calls=(_CALL,) if with_calls else (),
        stop_reason=stop_reason,
    )

    verdict = classify_llm_response(response)

    assert verdict.step is LoopStep.ESCALATE
    assert verdict.rule == "RN-007-34"
    assert verdict.why


# Regla: RN-007-35 — Una respuesta con una razón de parada válida pero incoherente o vacía también es una salida inválida.  # noqa: E501
# AC-007-42 · Art. 10
@pytest.mark.parametrize(
    ("text", "tool_calls", "stop_reason"),
    [
        ("", (), "end_turn"),
        (" \n\t \n", (), "end_turn"),
        ("Voy a consultar.", (_CALL,), "end_turn"),
        ("Voy a consultar.", (), "tool_use"),
    ],
    ids=[
        "end_turn_vacio",
        "end_turn_solo_espacios",
        "end_turn_con_peticion",
        "tool_use_sin_peticion",
    ],
)
def test_ac_007_42_loop_control__incoherent_or_empty__escalate(
    text: str, tool_calls: tuple[ToolCall, ...], stop_reason: str
) -> None:
    """AC-007-42: respuestas incoherentes o vacías escalan (RN-007-35)."""
    response = LLMResponse(text=text, tool_calls=tool_calls, stop_reason=stop_reason)

    verdict = classify_llm_response(response)

    assert verdict.step is LoopStep.ESCALATE
    assert verdict.rule == "RN-007-35"
    assert verdict.why


# Regla: RN-007-32 — Con `tool_use`, ejecuta las herramientas pedidas, siempre a través de las guardas.  # noqa: E501
# AC-007-35 · Art. 10
def test_ac_007_35_loop_control__tool_use_with_calls__continue() -> None:
    """AC-007-35: `tool_use` con peticiones continúa el loop (RN-007-32)."""
    response = LLMResponse(tool_calls=(_CALL,), stop_reason="tool_use")

    verdict = classify_llm_response(response)

    assert isinstance(verdict, LoopVerdict)
    assert verdict.step is LoopStep.CONTINUE
    assert verdict.rule == "RN-007-32"


# Regla: RN-007-32 — Con `end_turn`, envía al cliente el texto de la respuesta.
# AC-007-36 · Art. 10
def test_ac_007_36_loop_control__end_turn_with_text__reply() -> None:
    """AC-007-36: `end_turn` con texto responde al cliente (RN-007-32)."""
    response = LLMResponse(text="Hola, ¿en qué te ayudo?", stop_reason="end_turn")

    verdict = classify_llm_response(response)

    assert verdict.step is LoopStep.REPLY
    assert verdict.rule == "RN-007-32"


# Regla: RN-009-09 — una redacción con marcas del registro interno es salida inválida.
# AC-009-31 · Art. 10 (ante salida inválida del LLM, escalar)
@pytest.mark.parametrize(
    "text",
    [
        '[herramienta buscar_transacciones {"card": "**** 4321"}]',
        "<datos_internos>x</datos_internos>",
    ],
    ids=["bracket_tool_call", "internal_data_tag"],
)
def test_classify_draft_end__internal_markup_in_text__invalid(text: str) -> None:
    """Borde: end_turn con texto, pero con marcas internas ⇒ LLM_INVALID_OUTPUT."""
    verdict = classify_draft_end(LLMStreamEnd("end_turn", ()), f"Voy a consultar. {text}")

    assert not verdict.complete
    assert verdict.cause == "LLM_INVALID_OUTPUT"
