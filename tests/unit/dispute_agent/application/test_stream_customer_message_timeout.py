"""Tests de StreamCustomerMessage: espera máxima configurable de la redacción.

Spec 009: AC-009-10 (RN-009-09 b).
"""

import pytest
from tests.fakes.fake_llm import StreamScript
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator
from tests.unit.dispute_agent.application.test_stream_customer_message import (
    _END,
    _NOW,
    _ended,
    _Harness,
    _tx,
    _verified_conv,
    _words,
)
from tests.unit.dispute_agent.application.test_stream_customer_message_fixed import _banking
from tests.unit.dispute_agent.application.test_stream_customer_message_interruptions import (
    _interrupted,
    _loop_script,
    _shown,
)

from dispute_agent.application.use_cases.stream_customer_message import (
    ReplyEnded,
    ReplyInterrupted,
    ReplyStarted,
    ReplyWord,
    StreamCustomerMessage,
)
from dispute_agent.domain.models.conversation import ConversationStatus
from dispute_agent.domain.models.decision import EscalationReason


def _harness(silence: float, idle_timeout: float | None = None) -> tuple[_Harness, str]:
    """Guion `Hola ` + silencio de `silence` s + `Ana.`; opcionalmente otra espera máxima."""
    conv = _verified_conv(_tx())
    script: StreamScript = ([(0.0, "Hola "), (silence, "Ana.")], _END)
    harness = _Harness(conv, _loop_script(), [script], _banking())
    if idle_timeout is not None:
        harness.use_case = StreamCustomerMessage(
            harness.use_case._handler,  # noqa: SLF001
            harness.llm,
            harness.sleeper,
            harness.audit,
            FixedAgentClock(_NOW),
            idle_timeout,
            harness.repo,
            SequentialIdGenerator(),
        )
    return harness, conv.conversation_id


@pytest.mark.parametrize(
    ("silence", "completes"),
    [(29.0, True), (30.0, False)],
    ids=["29_s_completa", "30_s_interrumpe"],
)
# Regla: RN-009-09 (b) — 30 s sin texto nuevo interrumpen la redacción; 29 s no.
# AC-009-10 · Art. 10 — borde exacto de 30 s
async def test_ac_009_10_idle_timeout_borders(silence: float, completes: bool) -> None:
    """AC-009-10: 29 s ⇒ termina completa sin derivar; 30 s ⇒ `LLM_TIMEOUT` a los 30 s."""
    harness, conversation_id = _harness(silence)

    events = await harness.run(conversation_id, "No reconozco TX-L1")

    names = [name for name, _ in harness.banking.calls]
    if completes:
        assert [type(e) for e, _ in events] == [ReplyStarted, ReplyWord, ReplyWord, ReplyEnded]
        assert _words(events) == ["Hola", " Ana."]
        assert _ended(events).reply == "Hola Ana."
        assert "escalate" not in names
        assert harness.sleeper.now == 29.0
        return
    assert [type(e) for e, _ in events] == [ReplyStarted, ReplyWord, ReplyInterrupted]
    assert _words(events) == ["Hola"]
    assert events[-1][1] == 30.0
    interrupted = _interrupted(events)
    assert interrupted.status is ConversationStatus.ESCALATED
    assert names.count("escalate") == 1
    escalate_args = next(args for name, args in harness.banking.calls if name == "escalate")
    assert escalate_args["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    shown = _shown(harness)
    assert len(shown) == 1
    assert shown[0]["result"] == "INTERRUPTED"
    assert shown[0]["cause"] == "LLM_TIMEOUT"


# Regla: RN-009-09 (b) — la espera se cuenta desde el último texto recibido, no desde el inicio.
# AC-009-10 · Art. 10
async def test_ac_009_10_idle_timeout_restarts_with_each_delta() -> None:
    """AC-009-10: 4 trozos separados por 20 s (80 s en total) no interrumpen."""
    conv = _verified_conv(_tx())
    chunks = [(20.0, "Uno "), (20.0, "dos "), (20.0, "tres "), (20.0, "cuatro.")]
    harness = _Harness(conv, _loop_script(), [(chunks, _END)], _banking())

    events = await harness.run(conv.conversation_id, "No reconozco TX-L1")

    assert isinstance(events[-1][0], ReplyEnded)
    assert _ended(events).reply == "Uno dos tres cuatro."
    assert harness.sleeper.now == 80.0
    assert "escalate" not in [name for name, _ in harness.banking.calls]


@pytest.mark.parametrize(("silence", "interrupts"), [(10.0, True), (9.0, False)])
# Regla: RN-009-09 (b) — la espera máxima es configurable (constructor).
# AC-009-10 · Art. 10 — borde exacto de la espera configurada (10 s)
async def test_ac_009_10_idle_timeout_is_configurable(silence: float, interrupts: bool) -> None:
    """AC-009-10: con la espera en 10 s, 10 s de silencio interrumpen y 9 s no."""
    harness, conversation_id = _harness(silence, idle_timeout=10.0)

    events = await harness.run(conversation_id, "No reconozco TX-L1")

    if interrupts:
        assert isinstance(events[-1][0], ReplyInterrupted)
        assert events[-1][1] == 10.0
        assert _shown(harness)[0]["cause"] == "LLM_TIMEOUT"
    else:
        assert isinstance(events[-1][0], ReplyEnded)
        assert harness.sleeper.now == 9.0
