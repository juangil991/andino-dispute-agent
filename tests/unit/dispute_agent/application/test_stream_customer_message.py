"""Tests de StreamCustomerMessage: decisión primero y redacción palabra por palabra.

Spec 009: AC-009-01 a AC-009-05 (camino feliz `COMPLETE`).
"""

import re
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM, StreamScript, end_turn_response, tool_use_response
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator
from tests.fakes.virtual_sleeper import VirtualSleeper

from dispute_agent.application.ports.audit_log import AgentAuditEvent
from dispute_agent.application.ports.banking_tools import (
    DisputeOpened,
    EscalationRegistered,
    TransactionPage,
)
from dispute_agent.application.ports.llm import (
    ChatMessage,
    LLMStreamEnd,
    LLMTextDelta,
    ToolCall,
)
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import (
    ConversationNotFoundError,
    HandleCustomerMessage,
)
from dispute_agent.application.use_cases.stream_customer_message import (
    ReplyEnded,
    ReplyStarted,
    ReplyWord,
    StreamCustomerMessage,
    StreamEvent,
)
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus, KnownCard
from dispute_agent.domain.models.outcome import OutcomeKind
from dispute_agent.domain.models.transaction import DisputedTransaction
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 17)
_CARD = KnownCard("CARD-L1", "4321")
_END = LLMStreamEnd("end_turn")


class _Repo:
    def __init__(self, *conversations: Conversation) -> None:
        self.items = {c.conversation_id: c for c in conversations}

    def get(self, conversation_id: str) -> Conversation | None:
        return self.items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self.items[conversation.conversation_id] = conversation


class _TimelineAudit(FakeAgentAuditLog):
    """Auditoría que anota cada evento en una línea de tiempo compartida."""

    def __init__(self, timeline: list[str]) -> None:
        super().__init__()
        self._timeline = timeline

    def record(self, event: AgentAuditEvent) -> None:
        self._timeline.append(f"audit:{event.event_type}")
        super().record(event)


class _TimelineLLM(FakeLLM):
    """LLM falso que anota en la línea de tiempo cuándo empieza la redacción."""

    def __init__(self, timeline: list[str], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._timeline = timeline

    def stream(  # type: ignore[override]
        self, system: str, messages: tuple[ChatMessage, ...]
    ) -> AsyncIterator[LLMTextDelta | LLMStreamEnd]:
        self._timeline.append("stream")
        return super().stream(system, messages)


class _Harness:
    def __init__(
        self,
        conv: Conversation | None,
        script: list[object],
        stream_script: list[StreamScript],
        banking: FakeBankingTools | None = None,
    ) -> None:
        self.timeline: list[str] = []
        self.sleeper = VirtualSleeper()
        self.banking = banking or FakeBankingTools().respond(
            "escalate",
            EscalationRegistered(
                escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="OTHER"
            ),
        )
        self.llm = _TimelineLLM(
            self.timeline,
            script=script,  # type: ignore[arg-type]
            stream_script=stream_script,
            sleeper=self.sleeper,
        )
        self.audit = _TimelineAudit(self.timeline)
        self.repo = _Repo(*([conv] if conv else []))
        clock = FixedAgentClock(_NOW)
        ids = SequentialIdGenerator()
        escalation = EscalationService(self.banking, self.audit, clock)
        dispute_actions = DisputeActions(
            DisputePolicy(Decimal(4000)), self.banking, escalation, self.audit, clock
        )
        fraud_actions = FraudActions(self.banking, dispute_actions, escalation, self.audit, clock)
        handler = HandleCustomerMessage(
            self.llm,
            self.banking,
            self.repo,
            dispute_actions,
            fraud_actions,
            escalation,
            self.audit,
            clock,
            ids,
            8,
        )
        self.use_case = StreamCustomerMessage(
            handler, self.llm, self.sleeper, self.audit, clock, 30.0, self.repo, ids
        )

    async def run(
        self, conversation_id: str | None, message: str = "Hola"
    ) -> list[tuple[StreamEvent, float]]:
        """Eventos con la hora virtual (segundos) a la que se emitió cada uno."""
        prepared = self.use_case.prepare(conversation_id)
        return [
            (event, self.sleeper.now) async for event in self.use_case.events(prepared, message)
        ]


def _verified_conv(*transactions: DisputedTransaction) -> Conversation:
    conv = ConversationBuilder().verified("C-0001", (_CARD,)).build()
    conv.remember_transactions(transactions)
    return conv


def _tx() -> DisputedTransaction:
    return (
        DisputedTransactionBuilder()
        .transaction_id("TX-L1")
        .card("CARD-L1", "**** 4321")
        .merchant("Comercio Ficticio")
        .amount("85000.00", "COP")
        .days_ago(7, _TODAY)
        .national()
        .build()
    )


def _words(events: list[tuple[StreamEvent, float]]) -> list[str]:
    return [e.text for e, _ in events if isinstance(e, ReplyWord)]


def _ended(events: list[tuple[StreamEvent, float]]) -> ReplyEnded:
    last = events[-1][0]
    assert isinstance(last, ReplyEnded)
    return last


def _chunks(text: str, size: int) -> list[tuple[float, str]]:
    return [(0.0, text[i : i + size]) for i in range(0, len(text), size)]


def _call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


# Regla: RN-009-01 — `POST /api/chat/stream` responde `200` con un flujo de eventos.
# Regla: RN-009-03 — exactamente una llamada de redacción, sin herramientas.
# Regla: RN-009-06 — cada fragmento lleva una palabra completa con su espacio previo.
# Regla: RN-009-08 — la concatenación de los fragmentos es exactamente `reply`.
# AC-009-01 · Art. 5
async def test_ac_009_01_reply_streams_word_by_word() -> None:
    """AC-009-01: la redacción llega palabra por palabra y cada palabra sale al completarse."""
    conv = _verified_conv()
    harness = _Harness(
        conv,
        [end_turn_response("texto del ciclo")],
        [
            (
                [(1.0, "Abrimos tu dis"), (1.0, "puta por "), (1.0, "85.000 COP.")],
                _END,
            )
        ],
    )

    events = await harness.run(conv.conversation_id)

    assert isinstance(events[0][0], ReplyStarted)
    assert events[0][0].conversation_id == conv.conversation_id
    assert _words(events) == ["Abrimos", " tu", " disputa", " por", " 85.000", " COP."]
    times = {e.text: t for e, t in events if isinstance(e, ReplyWord)}
    assert times[" disputa"] == 2.0  # sale con el 2.º trozo, antes del 3.º (t = 3)
    assert times[" 85.000"] == 3.0
    ended = _ended(events)
    assert ended.reply == "Abrimos tu disputa por 85.000 COP."
    assert "".join(_words(events)) == ended.reply
    assert ended.status is ConversationStatus.ACTIVE
    assert len(harness.llm.stream_requests) == 1
    assert [m.role for m in conv.history] == ["user", "assistant"]
    assert conv.history[-1].text == ended.reply  # type: ignore[union-attr]


# Regla: RN-009-02 — el turno se ejecuta sin enviar texto a la cliente.
# Regla: RN-009-03 — el texto del ciclo no se envía; lo sustituye la redacción.
# AC-009-02 · Art. 5
async def test_ac_009_02_no_text_is_sent_while_the_loop_runs() -> None:
    """AC-009-02: entre `start` y el primer `word` no hay eventos ni texto del ciclo."""
    tx = _tx()
    conv = _verified_conv(tx)
    banking = (
        FakeBankingTools()
        .respond("list_transactions", TransactionPage((tx,), False))
        .respond(
            "open_dispute",
            DisputeOpened(
                dispute_id="D-0001",
                status="OPEN",
                opened_at=_NOW,
                reason="UNRECOGNIZED_CHARGE",
                transaction=tx,
            ),
        )
    )
    script = [
        tool_use_response(
            _call(
                "c1",
                "consultar_transacciones",
                card_last4="4321",
                date_from="2026-09-01",
                date_to="2026-10-17",
            ),
            text="Voy a revisar…",
        ),
        tool_use_response(
            _call("c2", "evaluar_disputa", transaction_id="TX-L1"), text="Voy a revisar…"
        ),
        end_turn_response("Listo."),
    ]
    harness = _Harness(conv, script, [(_chunks("Todo en orden con tu caso", 5), _END)], banking)

    events = await harness.run(conv.conversation_id)

    kinds = [type(e) for e, _ in events]
    assert kinds[0] is ReplyStarted
    assert set(kinds[1:-1]) == {ReplyWord}
    assert kinds[-1] is ReplyEnded
    sent = "".join(_words(events))
    assert "Voy a revisar" not in sent
    assert "Listo." not in sent
    assert sent == "Todo en orden con tu caso"
    assert len(harness.llm.requests) == 3


# Regla: RN-009-02 — guardas, `DisputePolicy`, herramientas y auditoría del turno van primero.
# Regla: RN-009-03 — la redacción solo empieza cuando todo lo anterior ya terminó.
# Regla: RN-009-05 — el texto de la redacción nunca ejecuta acciones.
# AC-009-03 · Art. 5
async def test_ac_009_03_decisions_and_actions_happen_before_first_word() -> None:
    """AC-009-03: `iniciar_disputa`, decisión y auditoría ocurren antes de la redacción."""
    tx = _tx()
    conv = _verified_conv(tx)
    banking = FakeBankingTools().respond(
        "open_dispute",
        DisputeOpened(
            dispute_id="D-0001",
            status="OPEN",
            opened_at=_NOW,
            reason="UNRECOGNIZED_CHARGE",
            transaction=tx,
        ),
    )
    script = [
        tool_use_response(_call("c1", "evaluar_disputa", transaction_id="TX-L1")),
        end_turn_response("Listo."),
    ]
    harness = _Harness(conv, script, [([(0.0, "Abrimos tu disputa.")], _END)], banking)
    opens_at_first_word: list[int] = []
    prepared = harness.use_case.prepare(conv.conversation_id)

    events: list[StreamEvent] = []
    async for event in harness.use_case.events(prepared, "No reconozco TX-L1"):
        if isinstance(event, ReplyWord) and not opens_at_first_word:
            opens_at_first_word.append(len([c for c in banking.calls if c[0] == "open_dispute"]))
            harness.timeline.append("first_word")
        events.append(event)

    assert opens_at_first_word == [1]
    timeline = harness.timeline
    stream_at = timeline.index("stream")
    assert "audit:decision" in timeline[:stream_at]
    assert timeline.index("first_word") > stream_at
    after_stream = [i for i in timeline[stream_at:] if i.startswith("audit:")]
    assert after_stream == ["audit:llm_response", "audit:reply_shown"]
    assert not {"audit:decision", "audit:tool_call", "audit:escalation"} & set(timeline[stream_at:])
    ended = events[-1]
    assert isinstance(ended, ReplyEnded)
    assert [(o.kind, o.rule) for o in ended.outcomes] == [(OutcomeKind.DISPUTE_OPENED, "DP-007-05")]
    assert harness.timeline[-1] == "audit:reply_shown"


# Regla: RN-009-05 — el texto de la redacción nunca se interpreta para ejecutar acciones.
# Regla: RN-009-11 — `reply_shown` registra el texto enviado y los `outcomes` del turno.
# AC-009-04 · Art. 5
async def test_ac_009_04_draft_text_never_triggers_actions() -> None:
    """AC-009-04: una redacción que afirma acciones no ejecuta nada y se audita `COMPLETE`."""
    conv = _verified_conv()
    text = "Ya bloqueé tu tarjeta y abrí la disputa."
    harness = _Harness(conv, [end_turn_response("Hola")], [(_chunks(text, 4), _END)])

    events = await harness.run(conv.conversation_id)

    assert [name for name, _ in harness.banking.calls] == []
    ended = _ended(events)
    assert ended.outcomes == ()
    shown = [e for e in harness.audit.events if e.event_type == "reply_shown"]
    assert len(shown) == 1
    assert shown[0].conversation_id == conv.conversation_id
    assert shown[0].at == _NOW
    assert shown[0].rule == "RN-009-03"
    assert shown[0].output == {"result": "COMPLETE", "cause": None, "text": text, "outcomes": []}


@pytest.mark.parametrize(
    "content",
    [
        "Tildes, ñandú y emojis 😀",
        "Línea 1\nLínea 2",
        "Mira " + "x" * 80,
        "<b>texto</b> con marcas de código",
    ],
    ids=["unicode", "salto_de_linea", "palabra_larga", "marcas_de_codigo"],
)
# Regla: RN-009-06 — cada fragmento es una palabra completa con su espacio previo.
# Regla: RN-009-08 — la concatenación de los fragmentos es exactamente `reply`.
# AC-009-05 · Art. 5
async def test_ac_009_05_stream_concatenation_equals_reply(content: str) -> None:
    """AC-009-05: las palabras no se parten ni se alteran; la concatenación es `reply`."""
    conv = _verified_conv()
    harness = _Harness(conv, [end_turn_response("Hola")], [(_chunks(content, 3), _END)])

    events = await harness.run(conv.conversation_id)

    words = _words(events)
    assert all(re.fullmatch(r"\s*\S+", word) for word in words)
    assert "".join(words) == content
    assert _ended(events).reply == content


# Regla: RN-009-01 — el flujo de eventos abre con `start`, que trae el id de la conversación.
# AC-009-01 · Art. 5
async def test_ac_009_01_new_conversation_started_event_carries_new_id() -> None:
    """AC-009-01: sin `conversation_id`, `ReplyStarted` trae el id de la conversación nueva."""
    harness = _Harness(None, [end_turn_response("Hola")], [([(0.0, "Hola")], _END)])

    events = await harness.run(None)

    first = events[0][0]
    assert isinstance(first, ReplyStarted)
    assert first.conversation_id == "conv-0001"
    assert _ended(events).conversation_id == "conv-0001"
    assert harness.repo.get("conv-0001") is not None


# Regla: RN-009-01 — `404` antes de transmitir cuando la conversación no existe.
# AC-009-08 · Art. 5
def test_ac_009_01_prepare_unknown_conversation_raises_not_found() -> None:
    """AC-009-01: `prepare` propaga `ConversationNotFoundError` (404 previo al flujo)."""
    harness = _Harness(None, [], [])

    with pytest.raises(ConversationNotFoundError):
        harness.use_case.prepare("NO-EXISTE")
