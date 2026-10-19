"""Verificación de HandleCustomerMessage: WRONG_DATES, INVALID_DATES y verificar + pedir.

Spec 007 0.3.1: AC-007-47, AC-007-49, AC-007-50 (fila 1), AC-007-52; RN-007-03, RN-007-04,
RN-007-21, RN-007-37, RN-007-38, RN-007-39, RN-007-40, RN-007-41. Los textos fijos se comparan
con el literal de spec §7.4, nunca con la constante.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    CardBlocked,
    DisputeOpened,
    EscalationRegistered,
    VerificationResult,
)
from dispute_agent.application.ports.llm import LLMResponse, ToolCall
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import HandleCustomerMessage
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus, KnownCard
from dispute_agent.domain.models.decision import EscalationReason, PriorAction
from dispute_agent.domain.models.outcome import OutcomeKind
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 17)
_CARD = KnownCard("CARD-L1", "4321")
_SCRIPT_TEXT = "Claro, ya reviso eso por ti."
_VERIFY_ARGS = {"birth_date": "1990-03-15", "document_issue_date": "2008-04-20"}

# Literales de spec §7.4
_WRONG_DATES_2 = (
    "Los datos no coinciden con los registrados. Te quedan 2 intentos. Indícame de nuevo tu "
    "fecha de nacimiento y la fecha de expedición de tu documento."
)
_WRONG_DATES_1 = (
    "Los datos no coinciden con los registrados. Te queda 1 intento. Indícame de nuevo tu "
    "fecha de nacimiento y la fecha de expedición de tu documento."
)
_INVALID_DATES = (
    "Las fechas no son válidas. Indícame tu fecha de nacimiento y la fecha de expedición de tu "
    "documento con el formato AAAA-MM-DD."
)
_CLOSED_ESCALATED = (
    "Tu caso requiere la revisión de una persona. Una persona continuará la atención."
)
_THANKS = "Gracias, ya verifiqué tu identidad."


class _Repo:
    def __init__(self, *conversations: Conversation) -> None:
        self.items = {c.conversation_id: c for c in conversations}

    def get(self, conversation_id: str) -> Conversation | None:
        return self.items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self.items[conversation.conversation_id] = conversation


def _call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def _tx() -> object:
    return (
        DisputedTransactionBuilder()
        .transaction_id("TX-L1")
        .card("CARD-L1", "**** 4321")
        .amount("85000.00", "COP")
        .days_ago(7, _TODAY)
        .national()
        .build()
    )


def _located_conv(with_transaction: bool = False) -> Conversation:
    conv = ConversationBuilder().located("C-0001", (_CARD,)).build()
    if with_transaction:
        conv.remember_transactions([_tx()])  # type: ignore[list-item]
    return conv


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


def _verify_script(**arguments: object) -> list[LLMResponse]:
    return [
        LLMResponse(tool_calls=(_call("c1", "verificar_identidad", **arguments),)),
        LLMResponse(text=_SCRIPT_TEXT),
    ]


def _names(banking: FakeBankingTools) -> list[str]:
    return [name for name, _ in banking.calls]


def _calls(banking: FakeBankingTools, tool: str) -> list[dict[str, object]]:
    return [args for name, args in banking.calls if name == tool]


# Regla: RN-007-38 (2) y RN-007-04 — fechas incorrectas: texto con los intentos que quedan; al
# agotarlos, derivación y cierre. AC-007-47 · Art. 7
@pytest.mark.parametrize(
    ("result", "expected_reply", "closes"),
    [
        pytest.param(
            VerificationResult(False, 2, False), _WRONG_DATES_2, False, id="first_failure"
        ),
        pytest.param(
            VerificationResult(False, 1, False), _WRONG_DATES_1, False, id="second_failure"
        ),
        pytest.param(VerificationResult(False, 0, True), _CLOSED_ESCALATED, True, id="third"),
    ],
)
async def test_ac_007_47_handle_message__wrong_dates__fixed_attempts_reply(
    result: VerificationResult, expected_reply: str, closes: bool
) -> None:
    """AC-007-47: WRONG_DATES con 2 y 1 intentos; al agotarlos deriva y cierra."""
    conv = _located_conv()
    banking = _banking().respond("verify_identity", result)
    use_case, _ = _build(_verify_script(**_VERIFY_ARGS), banking, _Repo(conv))

    turn = await use_case.handle(conv.conversation_id, "mis fechas")

    assert turn.reply == expected_reply
    assert _SCRIPT_TEXT not in turn.reply
    for datum in ("1990-03-15", "2008-04-20", "nacimiento falló", "expedición falló"):
        assert datum not in turn.reply
    assert conv.verified_customer_id is None
    escalations = _calls(banking, "escalate")
    if closes:
        assert [turn_outcome.kind for turn_outcome in turn.outcomes] == [OutcomeKind.ESCALATED]
        assert len(escalations) == 1
        assert escalations[0]["card_id"] is None
        assert escalations[0]["transaction_id"] is None
        assert escalations[0]["dispute_id"] is None
        assert escalations[0]["reason"] is EscalationReason.IDENTITY_VERIFICATION_FAILED
        assert turn.status is ConversationStatus.ESCALATED
    else:
        assert escalations == []
        assert turn.status is ConversationStatus.ACTIVE


# Regla: RN-007-40 — fechas sin formato ISO o INVALID_INPUT del core: se pide de nuevo, sin
# intento ni derivación. AC-007-49 · Art. 7
@pytest.mark.parametrize(
    ("first_args", "core_error", "verify_calls"),
    [
        pytest.param(
            {"birth_date": "15/03/1990", "document_issue_date": "2008-04-20"},
            None,
            1,
            id="not_iso_format",
        ),
        pytest.param(
            {"birth_date": "1990-03-14", "document_issue_date": "2008-04-20"},
            BankingToolError("INVALID_INPUT", "fechas inválidas", False),
            2,
            id="core_invalid_input",
        ),
    ],
)
async def test_ac_007_49_handle_message__invalid_dates__ask_again_without_attempt(
    first_args: dict[str, object], core_error: BankingToolError | None, verify_calls: int
) -> None:
    """AC-007-49: INVALID_DATES sin derivar ni gastar intento; con fechas correctas verifica."""
    conv = _located_conv()
    banking = _banking().respond(
        "verify_identity",
        *([core_error] if core_error else []),
        VerificationResult(True, 3, False),
    )
    script = [
        *_verify_script(**first_args),
        *_verify_script(**_VERIFY_ARGS),
    ]
    use_case, _ = _build(script, banking, _Repo(conv))

    first = await use_case.handle(conv.conversation_id, "mis fechas")

    assert first.reply == _INVALID_DATES
    assert "escalate" not in _names(banking)
    assert first.status is ConversationStatus.ACTIVE
    assert conv.verified_customer_id is None
    assert _names(banking).count("verify_identity") == (1 if core_error else 0)

    second = await use_case.handle(conv.conversation_id, "1990-03-15 y 2008-04-20")

    assert second.reply == _SCRIPT_TEXT
    assert conv.verified_customer_id == "C-0001"
    assert _names(banking).count("verify_identity") == verify_calls


# Regla: RN-007-37 — La guarda se evalúa **en cada petición**, con el estado de verificación de
# ese momento: si la cliente queda verificada a mitad del turno, las peticiones posteriores de
# ese turno se atienden con normalidad.
# AC-007-50 · Art. 7
async def test_ac_007_50_handle_message__verify_then_evaluate_in_one_message__dispute_opened() -> (
    None
):
    """AC-007-50: verificar_identidad y luego evaluar_disputa abren la disputa; reply del guion."""
    conv = _located_conv(with_transaction=True)
    tx = conv.seen_transactions["TX-L1"]
    opened = DisputeOpened("D-0001", "OPEN", _NOW, "UNRECOGNIZED_CHARGE", tx)
    banking = (
        _banking()
        .respond("verify_identity", VerificationResult(True, 3, False))
        .respond("open_dispute", opened)
    )
    use_case, _ = _build(
        [
            LLMResponse(tool_calls=(_call("c1", "verificar_identidad", **_VERIFY_ARGS),)),
            LLMResponse(tool_calls=(_call("c2", "evaluar_disputa", transaction_id="TX-L1"),)),
            LLMResponse(text=_THANKS),
        ],
        banking,
        _Repo(conv),
    )

    turn = await use_case.handle(conv.conversation_id, "mis fechas y no reconozco TX-L1")

    open_calls = _calls(banking, "open_dispute")
    assert [c["transaction_id"] for c in open_calls] == ["TX-L1"]
    assert [o.kind for o in turn.outcomes] == [OutcomeKind.DISPUTE_OPENED]
    assert turn.reply == "Gracias, ya verifiqué tu identidad."
    assert conv.verified_customer_id == "C-0001"


# Regla: RN-007-14 — Con identidad verificada, el agente invoca `bloquear_tarjeta` con
# `reason = FRAUD_SUSPECTED` sobre la tarjeta afectada, de inmediato y sin pedir confirmación.
# Regla: RN-007-17 — Con la identidad no verificada, una declaración de fraude no bloquea ninguna
# tarjeta: el agente deriva con `FRAUD_SUSPECTED` y resumen limitado y cierra la conversación.
# AC-007-52 · Art. 7
@pytest.mark.parametrize(
    "correct",
    [pytest.param(True, id="correct_dates"), pytest.param(False, id="wrong_dates")],
)
async def test_ac_007_52_handle_message__fraud_and_verify_in_one_message__blocks_or_escalates(
    correct: bool,
) -> None:
    """AC-007-52: fechas correctas bloquean y derivan; incorrectas derivan sin bloquear."""
    conv = _located_conv()
    verification = (
        VerificationResult(True, 3, False) if correct else VerificationResult(False, 2, False)
    )
    blocked = CardBlocked("CARD-L1", "**** 4321", "BLOCKED", _NOW, "FRAUD_SUSPECTED", False)
    banking = _banking().respond("verify_identity", verification).respond("block_card", blocked)
    use_case, _ = _build(
        [
            LLMResponse(
                tool_calls=(
                    _call("c1", "verificar_identidad", **_VERIFY_ARGS),
                    _call("c2", "reportar_fraude", card_last4="4321"),
                )
            ),
            LLMResponse(text="Bloqueamos tu tarjeta."),
        ],
        banking,
        _Repo(conv),
    )

    turn = await use_case.handle(conv.conversation_id, "mis fechas y sospecho fraude en la 4321")

    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.FRAUD_SUSPECTED
    if correct:
        assert turn.status is ConversationStatus.ACTIVE  # fraude verificada no cierra (§8)
        assert [c["card_id"] for c in _calls(banking, "block_card")] == ["CARD-L1"]
        assert escalations[0]["card_id"] == "CARD-L1"
        assert escalations[0]["prior_actions"] == (PriorAction.CARD_BLOCKED,)
        assert turn.reply == "Bloqueamos tu tarjeta."
        assert conv.verified_customer_id == "C-0001"
    else:
        assert turn.status is ConversationStatus.ESCALATED
        assert "block_card" not in _names(banking)
        assert escalations[0]["card_id"] is None
        assert escalations[0]["transaction_id"] is None
        assert escalations[0]["dispute_id"] is None
        assert escalations[0]["prior_actions"] == ()
        assert turn.reply == _CLOSED_ESCALATED
        assert conv.verified_customer_id is None
