"""Tests de StreamCustomerMessage: turno sin verificar con texto fijo.

Spec 007: AC-007-57 (RN-007-38, RN-009-04).
"""

from tests.fakes.fake_llm import end_turn_response
from tests.unit.dispute_agent.application.test_stream_customer_message import (
    _ended,
    _Harness,
)

from dispute_agent.application.use_cases.stream_customer_message import (
    ReplyEnded,
    ReplyStarted,
)
from dispute_agent.domain.messages import IDENTIFICATION_REPLIES, IdentificationReply
from dispute_agent.domain.models.conversation import ConversationStatus


# Regla: RN-007-38 — Si al terminar el turno la cliente no está verificada, el `reply` no es el
# texto del LLM sino un texto fijo de §7.4 (no se llama al LLM para redactarlo y se envía
# completo en el evento `end`, sin eventos `word`).
# AC-007-57 · Art. 7
async def test_ac_007_57_stream__unverified_turn__start_and_end_without_words() -> None:
    """AC-007-57: conversación nueva y `hola`: solo `start` y `end` con REMINDER_LOCATE."""
    harness = _Harness(None, [end_turn_response("Claro, ya reviso eso por ti.")], [])

    events = await harness.run(None, "hola")

    assert [type(e) for e, _ in events] == [ReplyStarted, ReplyEnded]
    ended = _ended(events)
    assert ended.reply == IDENTIFICATION_REPLIES[IdentificationReply.REMINDER_LOCATE]
    assert "Claro, ya reviso" not in ended.reply
    assert ended.status is ConversationStatus.ACTIVE
    assert harness.llm.stream_requests == []
    assert harness.banking.calls == []
