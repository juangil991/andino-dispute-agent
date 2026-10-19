"""Auditoría del rechazo por falta de identificación (evento `identification_required`).

Spec 007 0.3.0: AC-007-56; RN-007-37, RN-007-42.
"""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    CardRef,
    CustomerMatch,
    CustomerSearch,
    EscalationRegistered,
    VerificationResult,
)
from dispute_agent.application.ports.llm import LLMResponse, ToolCall
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import HandleCustomerMessage
from dispute_agent.domain.models.conversation import Conversation, KnownCard
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_SCRIPT_TEXT = "Claro, ya reviso eso por ti."
_PAN = "4111111111114321"
_DOCUMENT = "D-1001"
_REASON = "solicitud rechazada por falta de identificación"
_VERIFY_ARGS = {"birth_date": "1990-03-15", "document_issue_date": "2008-04-20"}


class _Repo:
    def __init__(self, *conversations: Conversation) -> None:
        self.items = {c.conversation_id: c for c in conversations}

    def get(self, conversation_id: str) -> Conversation | None:
        return self.items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self.items[conversation.conversation_id] = conversation


def _call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def _banking() -> FakeBankingTools:
    registered = EscalationRegistered(
        escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="OTHER"
    )
    return FakeBankingTools().respond("escalate", registered)


def _build(
    script: list[LLMResponse], banking: FakeBankingTools, repo: _Repo
) -> tuple[HandleCustomerMessage, FakeAgentAuditLog]:
    audit = FakeAgentAuditLog()
    clock = FixedAgentClock(_NOW)
    escalation = EscalationService(banking, audit, clock)
    dispute_actions = DisputeActions(
        DisputePolicy(Decimal(500000)), banking, escalation, audit, clock
    )
    use_case = HandleCustomerMessage(
        FakeLLM(script),
        banking,
        repo,
        dispute_actions,
        FraudActions(banking, dispute_actions, escalation, audit, clock),
        escalation,
        audit,
        clock,
        SequentialIdGenerator(),
        8,
    )
    return use_case, audit


def _required(audit: FakeAgentAuditLog) -> list[object]:
    return [e for e in audit.events if e.event_type == "identification_required"]


# Regla: RN-007-42 — cada recordatorio deja un evento sin texto de la cliente ni del guion.
# AC-007-56 · Art. 8
@pytest.mark.parametrize(
    ("message", "calls", "tools"),
    [
        pytest.param("hola", (), [], id="hello"),
        pytest.param(
            f"no reconozco un cobro de mi tarjeta {_PAN}",
            (
                _call("c1", "consultar_transacciones", card_last4="4321"),
                _call("c2", "evaluar_disputa", transaction_id="TX-L1"),
            ),
            ["consultar_transacciones", "evaluar_disputa"],
            id="two_blocked_tools",
        ),
        pytest.param(
            f"mi documento es {_DOCUMENT} pero primero muéstrame mi saldo", (), [], id="doc"
        ),
    ],
)
async def test_ac_007_56_handle_message__rejection__audited_without_text(
    message: str, calls: tuple[ToolCall, ...], tools: list[str]
) -> None:
    """AC-007-56: un solo evento identification_required, completo y sin texto de la cliente."""
    repo = _Repo()
    script = [LLMResponse(tool_calls=calls)] if calls else []
    use_case, audit = _build([*script, LLMResponse(text=_SCRIPT_TEXT)], _banking(), repo)

    result = await use_case.handle(None, message)

    events = [e for e in audit.events if e.event_type == "identification_required"]
    assert len(events) == 1
    event = events[0]
    assert event.conversation_id == result.conversation_id
    assert event.at == _NOW
    assert event.rule == "RN-007-37"
    assert event.reason == _REASON
    assert event.tool is None
    assert event.input == {"requested_tools": tools}
    assert event.output == {"reply": "REMINDER_LOCATE"}
    blocked = [e.tool for e in audit.events if e.event_type == "tool_blocked"]
    assert blocked == tools
    dumped = json.dumps([asdict(e) for e in audit.events], default=str)
    assert message not in dumped
    assert _SCRIPT_TEXT not in dumped
    assert _PAN not in dumped
    assert _DOCUMENT not in dumped


# Regla: RN-007-42 — con la cliente localizada el evento anota REMINDER_VERIFY.
# AC-007-56 · Art. 8
async def test_handle_message__located_reminder__audits_reminder_verify() -> None:
    """RN-007-42: el recordatorio de verificación audita `REMINDER_VERIFY`."""
    conv = ConversationBuilder().located("C-0001", (KnownCard("CARD-L1", "4321"),)).build()
    use_case, audit = _build([LLMResponse(text=_SCRIPT_TEXT)], _banking(), _Repo(conv))

    await use_case.handle(conv.conversation_id, "hola")

    events = [e for e in audit.events if e.event_type == "identification_required"]
    assert [e.output for e in events] == [{"reply": "REMINDER_VERIFY"}]
    assert [e.input for e in events] == [{"requested_tools": []}]


# Soporte de tests: RN-007-42 — los cierres y las verificadas no emiten el evento · Art. 8
async def test_handle_message__closing_turn__does_not_emit_identification_required() -> None:
    """RN-007-42: el turno que cierra con derivación no emite identification_required."""
    use_case, audit = _build(
        [
            LLMResponse(tool_calls=(_call("c1", "solicitar_atencion_humana"),)),
            LLMResponse(text=_SCRIPT_TEXT),
        ],
        _banking(),
        _Repo(),
    )

    await use_case.handle(None, "quiero hablar con una persona")

    assert _required(audit) == []


# Regla: RN-007-42 — Cada turno respondido con `REMINDER_LOCATE` o `REMINDER_VERIFY` genera un
# registro de auditoría `identification_required` (RN-007-28).
# AC-007-56 · Art. 8
async def test_handle_message__verified_in_turn__does_not_emit_identification_required() -> None:
    """RN-007-39: verificada en el turno, no se emite identification_required."""
    banking = (
        _banking()
        .respond(
            "search_customer",
            CustomerSearch((CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 4321"),)),), False),
        )
        .respond("verify_identity", VerificationResult(True, 3, False))
    )
    use_case, audit = _build(
        [
            LLMResponse(
                tool_calls=(
                    _call("c1", "buscar_cliente", document=_DOCUMENT),
                    _call("c2", "verificar_identidad", **_VERIFY_ARGS),
                )
            ),
            LLMResponse(text=_SCRIPT_TEXT),
        ],
        banking,
        _Repo(),
    )

    await use_case.handle(None, "hola")

    assert _required(audit) == []


# Regla: RN-007-42 — los textos de localización (ASK_DATES, ASK_MORE_DATA, NOT_FOUND) no son
# recordatorios y no emiten el evento. AC-007-56 · Art. 8
@pytest.mark.parametrize(
    "search",
    [
        pytest.param(
            CustomerSearch((CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 4321"),)),), False),
            id="ask_dates",
        ),
        pytest.param(
            CustomerSearch(
                (
                    CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 4321"),)),
                    CustomerMatch("C-0003", (CardRef("CARD-L3", "**** 5555"),)),
                ),
                False,
            ),
            id="ask_more_data",
        ),
        pytest.param(CustomerSearch((), False), id="not_found"),
    ],
)
async def test_ac_007_56_handle_message__locate_turns__do_not_emit_identification_required(
    search: CustomerSearch,
) -> None:
    """AC-007-56: los turnos ASK_DATES, ASK_MORE_DATA y NOT_FOUND no emiten el evento."""
    use_case, audit = _build(
        [
            LLMResponse(tool_calls=(_call("c1", "buscar_cliente", document=_DOCUMENT),)),
            LLMResponse(text=_SCRIPT_TEXT),
        ],
        _banking().respond("search_customer", search),
        _Repo(),
    )

    await use_case.handle(None, "hola")

    assert _required(audit) == []


# Regla: RN-007-42 — WRONG_DATES e INVALID_DATES no son recordatorios y no emiten el evento.
# AC-007-56 · Art. 8
@pytest.mark.parametrize(
    ("arguments", "verification"),
    [
        pytest.param(_VERIFY_ARGS, VerificationResult(False, 2, False), id="wrong_dates_2"),
        pytest.param(_VERIFY_ARGS, VerificationResult(False, 1, False), id="wrong_dates_1"),
        pytest.param(
            {"birth_date": "15/03/1990", "document_issue_date": "2008-04-20"},
            VerificationResult(False, 2, False),
            id="invalid_dates_format",
        ),
        pytest.param(
            _VERIFY_ARGS,
            BankingToolError("INVALID_INPUT", "fechas inválidas", False),
            id="invalid_dates_core",
        ),
    ],
)
async def test_ac_007_56_handle_message__verify_turns__do_not_emit_identification_required(
    arguments: dict[str, object], verification: VerificationResult | BankingToolError
) -> None:
    """AC-007-56: los turnos WRONG_DATES e INVALID_DATES no emiten el evento."""
    conv = ConversationBuilder().located("C-0001", (KnownCard("CARD-L1", "4321"),)).build()
    use_case, audit = _build(
        [
            LLMResponse(tool_calls=(_call("c1", "verificar_identidad", **arguments),)),
            LLMResponse(text=_SCRIPT_TEXT),
        ],
        _banking().respond("verify_identity", verification),
        _Repo(conv),
    )

    await use_case.handle(conv.conversation_id, "hola")

    assert _required(audit) == []


# Regla: RN-007-42 — Cada turno respondido con `REMINDER_LOCATE` o `REMINDER_VERIFY` genera un
# registro de auditoría `identification_required` (RN-007-28).
# AC-007-56 · Art. 8
async def test_handle_message__closed_conversation__does_not_emit_identification_required() -> None:
    """RN-007-24: una conversación ya cerrada no emite identification_required."""
    conv = ConversationBuilder().closed().build()
    use_case, audit = _build([], _banking(), _Repo(conv))

    await use_case.handle(conv.conversation_id, "hola")

    assert _required(audit) == []
