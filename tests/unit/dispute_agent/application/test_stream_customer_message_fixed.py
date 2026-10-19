"""Tests de StreamCustomerMessage: respuestas fijas sin redacción.

Spec 009: AC-009-07 (RN-009-04).
"""

import pytest
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import tool_use_response
from tests.unit.dispute_agent.application.test_stream_customer_message import (
    _NOW,
    _call,
    _ended,
    _Harness,
    _tx,
    _verified_conv,
)

from dispute_agent.application.ports.banking_tools import DisputeOpened, EscalationRegistered
from dispute_agent.application.ports.llm import LLMResponse
from dispute_agent.application.use_cases.stream_customer_message import (
    ReplyEnded,
    ReplyStarted,
)
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus

_LIMIT_TEXT = (
    "No pudimos completar tu solicitud automáticamente. Una persona continuará la atención."
)
_MAX_TOKENS_TEXT = (
    "Tuvimos un problema al procesar tu solicitud. Una persona continuará la atención."
)
_CLOSED_TEXT = "Tu caso ya fue derivado a un analista. Una persona continuará la atención."


def _verified() -> Conversation:
    return _verified_conv(_tx())


def _closed() -> Conversation:
    conv = _verified()
    conv.status = ConversationStatus.ESCALATED
    return conv


def _limit_script() -> list[object]:
    return [
        tool_use_response(_call(f"c{i}", "evaluar_disputa", transaction_id="TX-L1"))
        for i in range(8)
    ]


def _banking() -> FakeBankingTools:
    return (
        FakeBankingTools()
        .respond(
            "open_dispute",
            DisputeOpened(
                dispute_id="D-0001",
                status="OPEN",
                opened_at=_NOW,
                reason="UNRECOGNIZED_CHARGE",
                transaction=_tx(),
            ),
        )
        .respond(
            "escalate",
            EscalationRegistered(
                escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="OTHER"
            ),
        )
    )


@pytest.mark.parametrize(
    ("conv_factory", "script", "text"),
    [
        (_verified, _limit_script(), _LIMIT_TEXT),
        (_verified, [LLMResponse(text="", stop_reason="max_tokens")], _MAX_TOKENS_TEXT),
        (_closed, [], _CLOSED_TEXT),
    ],
    ids=["limite_de_8_llamadas", "max_tokens_en_el_ciclo", "conversacion_cerrada"],
)
# Regla: RN-009-04 — las respuestas fijas se envían enteras, sin redacción por palabras.
# AC-009-07 · Art. 10
async def test_ac_009_07_fixed_replies_are_sent_whole_without_drafting(
    conv_factory: object, script: list[object], text: str
) -> None:
    """AC-009-07: límite, `max_tokens` o cierre: solo `start` y `end` con el texto fijo."""
    conv = conv_factory()  # type: ignore[operator]
    history_before = list(conv.history)
    harness = _Harness(conv, script, [], _banking())

    events = await harness.run(conv.conversation_id)

    assert [type(e) for e, _ in events] == [ReplyStarted, ReplyEnded]
    ended = _ended(events)
    assert ended.reply == text
    assert ended.status is ConversationStatus.ESCALATED
    assert harness.llm.stream_requests == []
    if text == _CLOSED_TEXT:
        assert conv.history == history_before
        assert harness.banking.calls == []  # ninguna herramienta
        assert harness.llm.requests == []
