"""Tests de StreamCustomerMessage: interrupción de la redacción.

Spec 009: AC-009-09 y AC-009-11 (RN-009-09, RN-009-10).
"""

from collections.abc import AsyncIterator

import pytest
from tests.fakes.fake_llm import HANG, StreamScript, end_turn_response, tool_use_response
from tests.unit.dispute_agent.application.test_stream_customer_message import (
    _call,
    _Harness,
    _tx,
    _verified_conv,
    _words,
)
from tests.unit.dispute_agent.application.test_stream_customer_message_fixed import (
    _CLOSED_TEXT,
    _banking,
)

from dispute_agent.application.ports.llm import LLMError, LLMStreamEnd, LLMTextDelta
from dispute_agent.application.use_cases.stream_customer_message import (
    ReplyEnded,
    ReplyInterrupted,
    ReplyStarted,
    ReplyWord,
)
from dispute_agent.domain.models.conversation import ConversationStatus
from dispute_agent.domain.models.decision import EscalationReason
from dispute_agent.domain.models.outcome import OutcomeKind

_FIXED = "Tuvimos un problema al procesar tu solicitud. Una persona continuará la atención."
_TWO_WORDS: list[tuple[float, str]] = [(0.0, "Abrimos tu ")]


def _loop_script() -> list[object]:
    return [
        tool_use_response(_call("c1", "evaluar_disputa", transaction_id="TX-L1")),
        end_turn_response("Listo."),
    ]


def _interrupted(events: list[tuple[object, float]]) -> ReplyInterrupted:
    last = events[-1][0]
    assert isinstance(last, ReplyInterrupted)
    return last


def _shown(harness: _Harness) -> list[dict[str, object]]:
    return [e.output for e in harness.audit.events if e.event_type == "reply_shown"]  # type: ignore[misc]


def _scripts() -> list[tuple[StreamScript, str]]:
    return [
        ((_TWO_WORDS, LLMError("boom")), "LLM_ERROR"),
        ((_TWO_WORDS, HANG), "LLM_TIMEOUT"),
        ((_TWO_WORDS, LLMStreamEnd("max_tokens")), "LLM_INVALID_OUTPUT"),
        (
            (
                _TWO_WORDS,
                LLMStreamEnd("tool_use", (_call("t1", "bloquear_tarjeta", card_last4="4321"),)),
            ),
            "LLM_INVALID_OUTPUT",
        ),
        ((_TWO_WORDS, LLMStreamEnd("end_turn")), "INTERNAL_ERROR"),  # se sustituye por RuntimeError
    ]


@pytest.mark.parametrize(
    ("script", "cause"),
    _scripts(),
    ids=["error_del_llm", "30_s_sin_texto", "max_tokens", "herramienta_pedida", "falla_interna"],
)
# Regla: RN-009-09 / RN-009-10 — la redacción interrumpida deriva una vez y cierra la conversación.
# Regla: RN-009-05 — la herramienta pedida en la redacción nunca se ejecuta.
# AC-009-09 · Art. 10
async def test_ac_009_09_interrupted_draft_escalates_and_closes(
    script: StreamScript, cause: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-009-09: tras la falla no hay más `word`; `interrupted`, derivación única y cierre."""
    conv = _verified_conv(_tx())
    harness = _Harness(conv, _loop_script(), [script], _banking())
    if cause == "INTERNAL_ERROR":

        async def exploding(*_: object) -> AsyncIterator[LLMTextDelta | LLMStreamEnd]:
            yield LLMTextDelta("Abrimos tu ")
            raise RuntimeError("falla inesperada")

        monkeypatch.setattr(harness.llm, "stream", exploding)

    events = await harness.run(conv.conversation_id, "No reconozco TX-L1")

    assert [type(e) for e, _ in events] == [ReplyStarted, ReplyWord, ReplyWord, ReplyInterrupted]
    assert _words(events) == ["Abrimos", " tu"]
    interrupted = _interrupted(events)
    assert interrupted.reply == _FIXED
    assert interrupted.status is ConversationStatus.ESCALATED
    kinds = [(o.kind, o.rule) for o in interrupted.outcomes]
    assert kinds[0] == (OutcomeKind.DISPUTE_OPENED, "DP-007-05")
    assert kinds[-1] == (OutcomeKind.LLM_FAILURE, "RN-009-10")
    calls = harness.banking.calls
    assert [name for name, _ in calls] == ["open_dispute", "escalate"]
    assert calls[1][1]["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    assert conv.status is ConversationStatus.ESCALATED
    assert [m.text for m in conv.history[-2:]] == ["Abrimos tu", _FIXED]  # type: ignore[union-attr]
    shown = _shown(harness)
    assert len(shown) == 1
    assert shown[0]["result"] == "INTERRUPTED"
    assert shown[0]["cause"] == cause
    assert shown[0]["text"] == "Abrimos tu"
    after = await harness.run(conv.conversation_id, "¿Y ahora?")
    last = after[-1][0]
    assert isinstance(last, ReplyEnded)
    assert last.reply == _CLOSED_TEXT
    assert [name for name, _ in harness.banking.calls] == ["open_dispute", "escalate"]


@pytest.mark.parametrize(
    "script",
    [
        ([(0.0, "   ")], LLMStreamEnd("end_turn")),
        ([], LLMStreamEnd("refusal")),
        ([], LLMError("boom")),
    ],
    ids=["texto_en_blanco", "refusal_sin_texto", "error_antes_del_texto"],
)
# Regla: RN-009-09 / RN-009-10 — una redacción vacía o inválida sin palabras deriva y cierra.
# AC-009-11 · Art. 10
async def test_ac_009_11_invalid_draft_without_words_escalates(script: StreamScript) -> None:
    """AC-009-11: sin `word`, `interrupted` con el mensaje fijo y derivación del sistema."""
    conv = _verified_conv(_tx())
    harness = _Harness(conv, _loop_script(), [script], _banking())

    events = await harness.run(conv.conversation_id, "No reconozco TX-L1")

    assert [type(e) for e, _ in events] == [ReplyStarted, ReplyInterrupted]
    interrupted = _interrupted(events)
    assert interrupted.reply == _FIXED
    assert interrupted.status is ConversationStatus.ESCALATED
    calls = harness.banking.calls
    assert [name for name, _ in calls] == ["open_dispute", "escalate"]
    assert calls[1][1]["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    assert [m.text for m in conv.history[-1:]] == [_FIXED]  # type: ignore[union-attr]


# Regla: RN-009-09 — una redacción con marcas del registro interno de herramientas es salida
# inválida: lo ya enviado no se retracta y el turno se deriva (RN-009-10).
# AC-009-31 · Art. 10
async def test_ac_009_31_draft_with_internal_markup_escalates() -> None:
    """AC-009-31: `end_turn` con `[herramienta ...]` en el texto ⇒ `interrupted` y derivación."""
    leak: StreamScript = (
        [(0.0, 'Consulto. [herramienta buscar_transacciones {"card": "4321"}] ')],
        LLMStreamEnd("end_turn"),
    )
    conv = _verified_conv(_tx())
    harness = _Harness(conv, _loop_script(), [leak], _banking())

    events = await harness.run(conv.conversation_id, "No reconozco TX-L1")

    interrupted = _interrupted(events)
    assert interrupted.reply == _FIXED
    assert interrupted.status is ConversationStatus.ESCALATED
    calls = harness.banking.calls
    assert [name for name, _ in calls] == ["open_dispute", "escalate"]
    assert calls[1][1]["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    [shown] = _shown(harness)
    assert shown["result"] == "INTERRUPTED"
    assert shown["cause"] == "LLM_INVALID_OUTPUT"
