"""Tests de StreamCustomerMessage: desconexión de la página durante el turno.

Spec 009: AC-009-13 (RN-009-12).
"""

import asyncio
from typing import Any

import pytest
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import HANG, end_turn_response, tool_use_response
from tests.unit.dispute_agent.application.test_stream_customer_message import (
    _END,
    _call,
    _ended,
    _Harness,
    _tx,
    _verified_conv,
)
from tests.unit.dispute_agent.application.test_stream_customer_message_fixed import (
    _CLOSED_TEXT,
    _banking,
)

from dispute_agent.application.ports.banking_tools import DisputeOpened, EscalationRegistered
from dispute_agent.application.ports.llm import LLMError
from dispute_agent.application.use_cases.stream_customer_message import (
    ReplyInterrupted,
    ReplyStarted,
    ReplyWord,
    StreamEvent,
)
from dispute_agent.domain.models.conversation import ConversationStatus

_FIXED = "Tuvimos un problema al procesar tu solicitud. Una persona continuará la atención."


def _shown(harness: _Harness) -> list[dict[str, object]]:
    return [e.output for e in harness.audit.events if e.event_type == "reply_shown"]  # type: ignore[misc]


class _GatedBanking(FakeBankingTools):
    """`open_dispute` avisa de que empezó y espera a que el test lo libere."""

    def __init__(self, inner: FakeBankingTools) -> None:
        super().__init__()
        self._programmed = inner._programmed
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = False

    async def open_dispute(
        self, conversation_id: str, transaction_id: str, reason: str, idempotency_key: str
    ) -> DisputeOpened:
        self.started.set()
        await self.release.wait()
        result = await super().open_dispute(
            conversation_id, transaction_id, reason, idempotency_key
        )
        self.finished = True
        return result


class _GatedEscalation(FakeBankingTools):
    """`escalate` avisa de que empezó y espera a que el test lo libere."""

    def __init__(self, inner: FakeBankingTools) -> None:
        super().__init__()
        self._programmed = inner._programmed
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def escalate(self, *args: Any, **kwargs: Any) -> EscalationRegistered:
        self.started.set()
        await self.release.wait()
        return await super().escalate(*args, **kwargs)


# Regla: RN-009-12 — la derivación por interrupción (RN-009-10) ya empezó: la desconexión no la
# corta a medias; termina, cierra la conversación y la guarda con un único `reply_shown`
# (con la causa original de la interrupción, no `CLIENT_DISCONNECTED`).
# AC-009-13 · Art. 10
@pytest.mark.parametrize("how", ["cancel", "cancel_twice"])
async def test_ac_009_13_disconnect_during_interruption_escalation_does_not_cut_it(
    how: str,
) -> None:
    """AC-009-13: desconectar en pleno `escalar_a_analista` deja la derivación hecha y guardada."""
    conv = _verified_conv(_tx())
    banking = _GatedEscalation(_banking())
    harness = _Harness(
        conv,
        [
            tool_use_response(_call("c1", "evaluar_disputa", transaction_id="TX-L1")),
            end_turn_response("Listo."),
        ],
        [([(0.0, "Abrimos tu ")], LLMError("boom"))],
        banking,
    )
    prepared = harness.use_case.prepare(conv.conversation_id)
    received: list[StreamEvent] = []
    gen = harness.use_case.events(prepared, "No reconozco TX-L1")

    async def consume() -> None:
        async for event in gen:
            received.append(event)

    task = asyncio.ensure_future(consume())
    await banking.started.wait()
    task.cancel()
    if how == "cancel_twice":
        await asyncio.sleep(0)
        task.cancel()
    banking.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [name for name, _ in banking.calls] == ["open_dispute", "escalate"]
    assert conv.status is ConversationStatus.ESCALATED
    assert harness.repo.get(conv.conversation_id) is conv
    texts = [getattr(m, "text", None) for m in conv.history]
    assert texts.count("Abrimos tu") == 1
    assert texts.count(_FIXED) == 1
    assert texts[-2:] == ["Abrimos tu", _FIXED]
    shown = _shown(harness)
    assert len(shown) == 1
    assert shown[0]["result"] == "INTERRUPTED"
    assert shown[0]["cause"] == "LLM_ERROR"
    assert shown[0]["text"] == "Abrimos tu"
    assert not any(isinstance(e, ReplyInterrupted) for e in received)

    after = await harness.run(conv.conversation_id, "¿Y ahora?")

    assert _ended(after).reply == _CLOSED_TEXT
    assert [name for name, _ in banking.calls] == ["open_dispute", "escalate"]


# Regla: RN-009-12 — al cerrarse la conexión el agente deja de redactar, no llama más al LLM,
# no deriva y registra `INTERRUPTED` con causa `CLIENT_DISCONNECTED`; la conversación sigue activa.
# AC-009-13 · Art. 8
async def test_ac_009_13_disconnect_during_draft_stops_without_escalating() -> None:
    """AC-009-13: tras dos palabras y el cierre, no hay deriva ni otra llamada y sigue `ACTIVE`."""
    conv = _verified_conv(_tx())
    harness = _Harness(
        conv,
        [
            tool_use_response(_call("c1", "evaluar_disputa", transaction_id="TX-L1")),
            end_turn_response("Listo."),
            end_turn_response("Listo."),
        ],
        [
            ([(0.0, "Abrimos tu ")], HANG),
            ([(0.0, "Seguimos con tu caso")], _END),
        ],
        _banking(),
    )
    prepared = harness.use_case.prepare(conv.conversation_id)
    gen = harness.use_case.events(prepared, "No reconozco TX-L1")

    first = [await anext(gen) for _ in range(3)]
    await gen.aclose()

    assert isinstance(first[0], ReplyStarted)
    assert [e.text for e in first if isinstance(e, ReplyWord)] == ["Abrimos", " tu"]
    assert len(harness.llm.stream_requests) == 1
    assert [name for name, _ in harness.banking.calls] == ["open_dispute"]
    shown = _shown(harness)
    assert len(shown) == 1
    assert shown[0]["result"] == "INTERRUPTED"
    assert shown[0]["cause"] == "CLIENT_DISCONNECTED"
    assert shown[0]["text"] == "Abrimos tu"
    assert conv.status is ConversationStatus.ACTIVE
    texts = [getattr(m, "text", None) for m in conv.history]
    assert texts.count("No reconozco TX-L1") == 1
    assert (conv.history[-1].role, texts[-1]) == ("assistant", "Abrimos tu")  # type: ignore[union-attr]
    assert harness.repo.get(conv.conversation_id) is conv

    after = await harness.run(conv.conversation_id, "¿Cómo va?")

    assert _ended(after).reply == "Seguimos con tu caso"
    assert [name for name, _ in harness.banking.calls] == ["open_dispute"]


# Regla: RN-009-12 — las decisiones del turno ya se tomaron: la desconexión no corta acciones.
# AC-009-13 · Art. 8
async def test_ac_009_13_disconnect_during_decision_does_not_cut_actions() -> None:
    """AC-009-13: cancelar en pleno `iniciar_disputa` deja la disputa terminada y guardada."""
    conv = _verified_conv(_tx())
    banking = _GatedBanking(_banking())
    harness = _Harness(
        conv,
        [
            tool_use_response(_call("c1", "evaluar_disputa", transaction_id="TX-L1")),
            end_turn_response("Listo."),
        ],
        [([(0.0, "No debería salir")], _END)],
        banking,
    )
    prepared = harness.use_case.prepare(conv.conversation_id)
    received: list[StreamEvent] = []

    async def consume() -> None:
        async for event in harness.use_case.events(prepared, "No reconozco TX-L1"):
            received.append(event)

    task = asyncio.ensure_future(consume())
    await banking.started.wait()
    task.cancel()
    banking.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert banking.finished
    assert [name for name, _ in banking.calls] == ["open_dispute"]
    assert harness.llm.stream_requests == []
    assert [type(e) for e in received] == [ReplyStarted]
    assert conv.status is ConversationStatus.ACTIVE
    assert [getattr(m, "text", None) for m in conv.history].count("No reconozco TX-L1") == 1
    assert harness.repo.get(conv.conversation_id) is conv
    shown = _shown(harness)
    assert len(shown) == 1
    assert shown[0]["result"] == "INTERRUPTED"
    assert shown[0]["cause"] == "CLIENT_DISCONNECTED"
    assert shown[0]["text"] == ""
    assert [o["kind"] for o in shown[0]["outcomes"]] == ["DISPUTE_OPENED"]  # type: ignore[attr-defined]
