"""Tests de StreamCustomerMessage: auditoría de la respuesta mostrada.

Spec 009: AC-009-12 (RN-009-11) y la nota de la derivación con la causa (§8, RN-009-10).
"""

import json
from decimal import Decimal

import pytest
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM, StreamScript, end_turn_response, tool_use_response
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator
from tests.fakes.virtual_sleeper import VirtualSleeper
from tests.unit.dispute_agent.application.test_stream_customer_message import (
    _END,
    _NOW,
    _call,
    _ended,
    _Repo,
    _tx,
    _verified_conv,
)
from tests.unit.dispute_agent.application.test_stream_customer_message_fixed import _banking

from dispute_agent.application.ports.audit_log import AgentAuditEvent
from dispute_agent.application.ports.llm import LLMError, LLMStreamEnd
from dispute_agent.application.redacting_audit_log import RedactingAuditLog
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import HandleCustomerMessage
from dispute_agent.application.use_cases.stream_customer_message import (
    StreamCustomerMessage,
    StreamEvent,
)
from dispute_agent.domain.models.conversation import Conversation
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_PAN = "4111111111114321"
_DOC = "D-1001"
_DRAFT = f"Tu tarjeta {_PAN} y tu documento {_DOC}."
_LEAK_TEXT = "texto parcial sensible"


class _Wiring:
    """Cableado de producción: el audit del turno es el `RedactingAuditLog` real."""

    def __init__(self, conv: Conversation, stream_script: list[StreamScript]) -> None:
        self.inner = FakeAgentAuditLog()
        repo = _Repo(conv)

        def documents_for(conversation_id: str) -> tuple[str, ...]:
            found = repo.get(conversation_id)
            return () if found is None else tuple(found.provided_documents)

        audit = RedactingAuditLog(self.inner, documents_for=documents_for)
        self.banking: FakeBankingTools = _banking()
        sleeper = VirtualSleeper()
        llm = FakeLLM(
            script=[  # type: ignore[arg-type]
                tool_use_response(_call("c1", "evaluar_disputa", transaction_id="TX-L1")),
                end_turn_response("Listo."),
            ],
            stream_script=stream_script,
            sleeper=sleeper,
        )
        clock = FixedAgentClock(_NOW)
        ids = SequentialIdGenerator()
        escalation = EscalationService(self.banking, audit, clock)
        disputes = DisputeActions(
            DisputePolicy(Decimal(4000)), self.banking, escalation, audit, clock
        )
        fraud = FraudActions(self.banking, disputes, escalation, audit, clock)
        handler = HandleCustomerMessage(
            llm, self.banking, repo, disputes, fraud, escalation, audit, clock, ids, 8
        )
        self.use_case = StreamCustomerMessage(handler, llm, sleeper, audit, clock, 30.0, repo, ids)

    async def run(self, conversation_id: str) -> list[StreamEvent]:
        prepared = self.use_case.prepare(conversation_id)
        return [e async for e in self.use_case.events(prepared, "No reconozco TX-L1")]

    def of_type(self, event_type: str) -> list[AgentAuditEvent]:
        return [e for e in self.inner.events if e.event_type == event_type]


def _conv_with_document() -> Conversation:
    conv = _verified_conv(_tx())
    conv.provided_documents.add(_DOC)
    return conv


@pytest.mark.parametrize(
    ("script", "result", "cause", "rule", "stop_reason", "decision"),
    [
        (([(0.0, _DRAFT)], _END), "COMPLETE", None, "RN-009-03", "end_turn", "REPLY"),
        (
            ([(0.0, _DRAFT)], LLMStreamEnd("max_tokens")),
            "INTERRUPTED",
            "LLM_INVALID_OUTPUT",
            "RN-009-09",
            "max_tokens",
            "ESCALATE",
        ),
    ],
    ids=["completa", "max_tokens"],
)
# Regla: RN-009-11 — cada respuesta mostrada queda auditada con su texto filtrado y los outcomes.
# Regla: RN-009-11 — la llamada de redacción genera su `llm_response` (RN-007-36).
# AC-009-12 · Art. 8
async def test_ac_009_12_reply_shown_is_audited_masked(
    script: StreamScript,
    result: str,
    cause: str | None,
    rule: str,
    stop_reason: str,
    decision: str,
) -> None:
    """AC-009-12: `reply_shown` y `llm_response` de la redacción, sin datos sin enmascarar."""
    conv = _conv_with_document()
    wiring = _Wiring(conv, [script])

    events = await wiring.run(conv.conversation_id)

    shown = wiring.of_type("reply_shown")
    assert len(shown) == 1
    assert shown[0].conversation_id == conv.conversation_id
    assert shown[0].at == _NOW
    assert shown[0].output is not None
    assert shown[0].output["result"] == result
    assert shown[0].output["cause"] == cause
    assert shown[0].output["outcomes"][0] == {  # type: ignore[index]
        "kind": "DISPUTE_OPENED",
        "rule": "DP-007-05",
    }
    text = shown[0].output["text"]
    assert isinstance(text, str)
    assert _PAN not in text
    assert _DOC not in text
    assert text.startswith("Tu tarjeta")
    drafts = [e for e in wiring.of_type("llm_response") if e.input == {"call": "draft"}]
    assert len(drafts) == 1
    assert drafts[0].rule == rule
    assert drafts[0].output == {
        "stop_reason": stop_reason,
        "decision": decision,
        "tool_call_count": 0,
        "tool_calls": [],
    }
    order = [e.event_type for e in wiring.inner.events]
    assert order.index("llm_response") < order.index("reply_shown")
    assert [e for e in wiring.inner.events if e.event_type == "llm_response"][-1] is drafts[0]
    if result == "COMPLETE":
        assert (
            text
            == _ended(
                [(e, 0.0) for e in events]  # type: ignore[misc]
            ).reply
        )
    dumped = json.dumps([vars(e) for e in wiring.inner.events], default=str, ensure_ascii=False)
    assert _PAN not in dumped
    assert _DOC not in dumped


@pytest.mark.parametrize(
    ("script", "cause"),
    [
        (([(0.0, _LEAK_TEXT)], LLMError("boom")), "LLM_ERROR"),
        (([(0.0, _LEAK_TEXT)], LLMStreamEnd("max_tokens")), "LLM_INVALID_OUTPUT"),
    ],
    ids=["error_del_llm", "max_tokens"],
)
# Regla: RN-009-10 — la nota de la derivación por interrupción lleva solo la causa.
# AC-009-09 · Art. 10
async def test_ac_009_09_interruption_note_carries_cause_only(
    script: StreamScript, cause: str
) -> None:
    """Spec §8: la nota recibida por `escalar_a_analista` trae la causa, sin texto del LLM."""
    conv = _conv_with_document()
    wiring = _Wiring(conv, [script])

    await wiring.run(conv.conversation_id)

    escalations = [args for name, args in wiring.banking.calls if name == "escalate"]
    assert len(escalations) == 1
    note = escalations[0]["note"]
    assert isinstance(note, str)
    assert cause in note
    assert "RN-009-10" in note
    assert _LEAK_TEXT not in note
    assert "boom" not in note


# Regla: RN-009-11 — sin fin del flujo, el `llm_response` de la redacción cita `RN-009-09`.
# AC-009-12 · Art. 8
async def test_ac_009_12_draft_llm_response_without_stream_end() -> None:
    """AC-009-12: sin `LLMStreamEnd` el `llm_response` trae `stop_reason` nulo y `RN-009-09`."""
    conv = _conv_with_document()
    wiring = _Wiring(conv, [([(0.0, "Hola ")], LLMError("boom"))])

    await wiring.run(conv.conversation_id)

    drafts = [e for e in wiring.of_type("llm_response") if e.input == {"call": "draft"}]
    assert len(drafts) == 1
    assert drafts[0].rule == "RN-009-09"
    assert drafts[0].output == {
        "stop_reason": None,
        "decision": "ESCALATE",
        "tool_call_count": 0,
        "tool_calls": [],
    }
