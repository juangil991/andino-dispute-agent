"""Tests del clasificador de la redacción en streaming (`classify_draft_end`)."""

import pytest

from dispute_agent.application.loop_control import DraftVerdict, classify_draft_end
from dispute_agent.application.ports.llm import LLMStreamEnd, ToolCall

_CALL = ToolCall(id="call-1", name="consultar_transacciones", arguments={})
_TEXT = "Ya registré tu solicitud."


# Regla: RN-009-09 — La redacción es completa solo con `end_turn`, sin herramientas y con texto no vacío; si no, es salida inválida.  # noqa: E501
# AC-009-09 · Art. 10
# AC-009-11 · Art. 10 (redacción vacía o inválida sin palabras enviadas)
@pytest.mark.parametrize(
    ("stop_reason", "text", "tool_calls", "complete"),
    [
        ("end_turn", _TEXT, (), True),
        ("end_turn", "   ", (), False),
        ("end_turn", "", (), False),
        ("max_tokens", _TEXT, (), False),
        ("refusal", _TEXT, (), False),
        ("pause_turn", _TEXT, (), False),
        ("stop_sequence", _TEXT, (), False),
        (None, _TEXT, (), False),
        ("other_reason", _TEXT, (), False),
        ("end_turn", _TEXT, (_CALL,), False),
    ],
    ids=[
        "end_turn_con_texto",
        "end_turn_solo_espacios",
        "end_turn_texto_vacio",
        "max_tokens",
        "refusal",
        "pause_turn",
        "stop_sequence",
        "ausente",
        "otra_razon",
        "end_turn_con_herramienta",
    ],
)
def test_ac_009_09_draft_end_is_complete_only_with_end_turn_text_and_no_tools(
    stop_reason: str | None,
    text: str,
    tool_calls: tuple[ToolCall, ...],
    complete: bool,
) -> None:
    """AC-009-09 y AC-009-11: solo `end_turn` con texto y sin herramientas es COMPLETE."""
    end = LLMStreamEnd(stop_reason=stop_reason, tool_calls=tool_calls)

    verdict = classify_draft_end(end, text)

    expected_cause = None if complete else "LLM_INVALID_OUTPUT"
    assert verdict == DraftVerdict(complete=complete, cause=expected_cause)
