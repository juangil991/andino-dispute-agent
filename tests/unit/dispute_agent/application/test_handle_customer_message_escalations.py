"""Tests de HandleCustomerMessage: persona, fraude, cierre, límites y fallas.

Spec 007: AC-007-11, 12, 13, 14, 15, 16, 23, 24, 25, 26 y 29 (fila CARD_BLOCKED).
"""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.banking_errors import not_found
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolUnavailableError,
    CardBlocked,
    DisputeOpened,
    EscalationRegistered,
    VerificationResult,
)
from dispute_agent.application.ports.llm import LLMError, LLMResponse, ToolCall
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import (
    ChatTurnResult,
    HandleCustomerMessage,
)
from dispute_agent.domain import messages
from dispute_agent.domain.models.conversation import (
    Conversation,
    ConversationStatus,
    KnownCard,
)
from dispute_agent.domain.models.decision import EscalationReason, PriorAction
from dispute_agent.domain.models.outcome import OutcomeKind
from dispute_agent.domain.models.transaction import DisputedTransaction
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 17)
_CARD_1 = KnownCard("CARD-L1", "4321")
_CARD_2 = KnownCard("CARD-L2", "8765")


class _Repo:
    """Repositorio de conversaciones en memoria, local al test."""

    def __init__(self, *conversations: Conversation) -> None:
        self.items = {c.conversation_id: c for c in conversations}

    def get(self, conversation_id: str) -> Conversation | None:
        return self.items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self.items[conversation.conversation_id] = conversation


def _tx(tx_id: str = "TX-L1", amount: str = "85000.00") -> DisputedTransaction:
    return (
        DisputedTransactionBuilder()
        .transaction_id(tx_id)
        .card("CARD-L1", "**** 4321")
        .amount(amount, "COP")
        .days_ago(7, _TODAY)
        .national()
        .build()
    )


def _verified_conv(*transactions: DisputedTransaction) -> Conversation:
    conv = ConversationBuilder().verified("C-0001", (_CARD_1,)).build()
    conv.remember_transactions(transactions)
    return conv


def _located_conv() -> Conversation:
    return ConversationBuilder().located("C-0001", (_CARD_1,)).build()


def _registered() -> EscalationRegistered:
    return EscalationRegistered(
        escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="OTHER"
    )


def _blocked_card(already_blocked: bool = False) -> CardBlocked:
    return CardBlocked(
        card_id="CARD-L1",
        masked_card="**** 4321",
        status="BLOCKED",
        blocked_at=_NOW,
        reason="FRAUD_SUSPECTED",
        already_blocked=already_blocked,
    )


def _opened(tx: DisputedTransaction) -> DisputeOpened:
    return DisputeOpened(
        dispute_id="D-0001",
        status="OPEN",
        opened_at=_NOW,
        reason="UNRECOGNIZED_CHARGE",
        transaction=tx,
    )


def _banking() -> FakeBankingTools:
    return FakeBankingTools().respond("escalate", _registered())


def _build(
    script: list[LLMResponse | LLMError],
    banking: FakeBankingTools,
    *conversations: Conversation,
    max_iterations: int = 8,
) -> tuple[HandleCustomerMessage, FakeLLM, _Repo, FakeAgentAuditLog]:
    llm = FakeLLM(script)
    repo = _Repo(*conversations)
    audit = FakeAgentAuditLog()
    clock = FixedAgentClock(_NOW)
    escalation = EscalationService(banking, audit, clock)
    dispute_actions = DisputeActions(
        DisputePolicy(Decimal(4000)), banking, escalation, audit, clock
    )
    fraud_actions = FraudActions(banking, dispute_actions, escalation, audit, clock)
    use_case = HandleCustomerMessage(
        llm,
        banking,
        repo,
        dispute_actions,
        fraud_actions,
        escalation,
        audit,
        clock,
        SequentialIdGenerator(),
        max_iterations,
    )
    return use_case, llm, repo, audit


def _call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def _tools(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(tool_calls=tuple(calls))


def _final(text: str) -> LLMResponse:
    return LLMResponse(text=text)


def _names(banking: FakeBankingTools) -> list[str]:
    return [name for name, _ in banking.calls]


def _calls(banking: FakeBankingTools, tool: str) -> list[dict[str, object]]:
    return [args for name, args in banking.calls if name == tool]


def _tool_results(llm: FakeLLM, request_index: int = -1) -> list[tuple[str, bool]]:
    """(contenido, is_error) de los tool_result enviados al LLM en una petición."""
    return [
        (result.content, result.is_error)
        for message in llm.requests[request_index].messages
        for result in message.tool_results
    ]


def _closed_events(audit: FakeAgentAuditLog) -> list[str | None]:
    return [e.rule for e in audit.events if e.event_type == "conversation_closed"]


def _assert_limited(escalation: dict[str, object]) -> None:
    assert escalation["transaction_id"] is None
    assert escalation["card_id"] is None
    assert escalation["dispute_id"] is None
    assert escalation["prior_actions"] == ()


# Regla: RN-007-18 — Cuando el cliente pide expresamente que lo atienda una persona (lo interpreta
# el LLM y lo indica al agente), el agente deriva **de inmediato**, en cualquier momento de la
# conversación, y cierra la conversación. En ese turno no invoca `consultar_transacciones` ni
# `iniciar_disputa`, aunque el mismo mensaje pida otras cosas. La derivación usa el motivo `OTHER`
# y la nota `Cliente solicitó atención humana`, con resumen completo (sin transacción ni tarjeta)
# si está verificado y limitado si no. Frases de frustración o de duda que no piden una persona no
# derivan por sí solas.
# Regla: RN-007-24 — Una conversación se **cierra** tras derivar por petición de una persona
# (RN-007-18/19), fraude sin identidad (RN-007-17), identificación fallida (RN-007-04/05), falla
# del sistema (RN-007-21/22) o límite de iteraciones (RN-007-23). En una conversación cerrada, el
# agente no llama al LLM ni a ninguna herramienta y responde con el mensaje fijo `Tu caso ya fue
# derivado a un analista. Una persona continuará la atención.` Las derivaciones de una
# transacción por DP-007-02/03/04/06/07 **no** cierran la conversación.
# AC-007-12 · Art. 10
@pytest.mark.parametrize(
    ("moment", "phrase"),
    [
        ("unidentified", "quiero hablar con una persona"),
        ("located", "pásame con un asesor humano"),
        ("verified", "prefiero que me atienda un analista"),
        ("verified_with_transactions", "quiero hablar con alguien del banco"),
    ],
    ids=["unidentified", "located_verifying", "verified", "verified_with_transactions"],
)
async def test_ac_007_12_handle_message__human_request__escalates_immediately(
    moment: str, phrase: str
) -> None:
    """AC-007-12: pedir una persona deriva de inmediato con OTHER y cierra la conversación."""
    conv = {
        "unidentified": lambda: ConversationBuilder().build(),
        "located": _located_conv,
        "verified": _verified_conv,
        "verified_with_transactions": lambda: _verified_conv(_tx("TX-L1")),
    }[moment]()
    banking = _banking()
    use_case, _, repo, audit = _build(
        [
            _tools(_call("c1", "solicitar_atencion_humana")),
            _final("Una persona continuará la atención."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, phrase)

    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.OTHER
    assert escalations[0]["note"] == "Cliente solicitó atención humana"
    _assert_limited(escalations[0])
    assert "list_transactions" not in _names(banking)
    assert "open_dispute" not in _names(banking)
    assert [o.kind for o in result.outcomes] == [OutcomeKind.ESCALATED]
    assert result.outcomes[0].rule == "RN-007-18"
    assert result.outcomes[0].reason == messages.ESCALATED_NO_TX_REASON
    assert result.outcomes[0].next_steps == messages.ESCALATED_NO_TX_NEXT_STEPS
    assert result.status is ConversationStatus.ESCALATED
    saved = repo.get(result.conversation_id)
    assert saved is not None
    assert saved.status is ConversationStatus.ESCALATED
    assert _closed_events(audit) == ["RN-007-18"]
    assert isinstance(result, ChatTurnResult)


# Regla: RN-007-17 — Con la identidad **no** verificada, una declaración de fraude no bloquea
# ninguna tarjeta ni opera sobre productos: el agente deriva con `FRAUD_SUSPECTED` y resumen
# limitado, informa que una persona continuará la atención y cierra la conversación.
# Regla: RN-007-24 — Una conversación se **cierra** tras derivar por petición de una persona
# (RN-007-18/19), fraude sin identidad (RN-007-17), identificación fallida (RN-007-04/05), falla
# del sistema (RN-007-21/22) o límite de iteraciones (RN-007-23). En una conversación cerrada, el
# agente no llama al LLM ni a ninguna herramienta y responde con el mensaje fijo `Tu caso ya fue
# derivado a un analista. Una persona continuará la atención.` Las derivaciones de una
# transacción por DP-007-02/03/04/06/07 **no** cierran la conversación.
# AC-007-11 · Art. 7
async def test_ac_007_11_handle_message__unverified_fraud__escalates_limited_and_closes() -> None:
    """AC-007-11: fraude sin verificar no bloquea; deriva limitado y la conversación se cierra."""
    conv = _located_conv()
    banking = _banking()
    use_case, _, repo, audit = _build(
        [
            _tools(_call("c1", "reportar_fraude", card_last4="4321")),
            _final("Una persona continuará la atención."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Sospecho de fraude con mi tarjeta")

    assert "block_card" not in _names(banking)
    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.FRAUD_SUSPECTED
    _assert_limited(escalations[0])
    assert [o.kind for o in result.outcomes] == [OutcomeKind.ESCALATED]
    assert result.outcomes[0].reason == messages.ESCALATED_NO_TX_REASON
    assert result.outcomes[0].next_steps == messages.ESCALATED_NO_TX_NEXT_STEPS
    assert result.status is ConversationStatus.ESCALATED
    saved = repo.get(result.conversation_id)
    assert saved is not None
    assert saved.status is ConversationStatus.ESCALATED
    assert _closed_events(audit) == ["RN-007-17"]


# Regla: RN-007-17 — Con la identidad **no** verificada, una declaración de fraude no bloquea
# ninguna tarjeta ni opera sobre productos: el agente deriva con `FRAUD_SUSPECTED` y resumen
# limitado, informa que una persona continuará la atención y cierra la conversación.
# Regla: RN-007-19 — Si en el mismo turno el cliente pide una persona y declara fraude: con
# identidad verificada, el agente primero bloquea la tarjeta (RN-007-14/15) y luego registra
# **una sola** derivación con `FRAUD_SUSPECTED`, `card_id`, `prior_actions = ["CARD_BLOCKED"]` y la
# nota `Cliente solicitó atención humana`, sin consultar transacciones ni abrir disputas. Sin
# identidad verificada se aplica RN-007-17. En ambos casos se cierra la conversación.
# AC-007-15 · Art. 7
async def test_ac_007_15_handle_message__unverified_human_and_fraud__escalates_limited() -> None:
    """AC-007-15: persona y fraude sin verificar: sin bloqueo y una sola derivación limitada."""
    conv = _located_conv()
    banking = _banking()
    use_case, _, _, audit = _build(
        [
            _tools(
                _call("c1", "solicitar_atencion_humana"),
                _call("c2", "reportar_fraude", card_last4="4321"),
            ),
            _final("Una persona continuará la atención."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(
        conv.conversation_id, "Quiero hablar con una persona, sospecho de fraude con mi tarjeta"
    )

    assert "block_card" not in _names(banking)
    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.FRAUD_SUSPECTED
    _assert_limited(escalations[0])
    assert [o.kind for o in result.outcomes] == [OutcomeKind.ESCALATED]
    assert result.status is ConversationStatus.ESCALATED
    assert _closed_events(audit) == ["RN-007-17"]


# Regla: RN-007-18 — Cuando el cliente pide expresamente que lo atienda una persona (lo interpreta
# el LLM y lo indica al agente), el agente deriva **de inmediato**, en cualquier momento de la
# conversación, y cierra la conversación. En ese turno no invoca `consultar_transacciones` ni
# `iniciar_disputa`, aunque el mismo mensaje pida otras cosas. La derivación usa el motivo `OTHER`
# y la nota `Cliente solicitó atención humana`, con resumen completo (sin transacción ni tarjeta)
# si está verificado y limitado si no. Frases de frustración o de duda que no piden una persona no
# derivan por sí solas.
# AC-007-13 · Art. 10
@pytest.mark.parametrize(
    "phrase",
    ["no entiendo lo que me pide", "esto es muy lento", "no sé cuál es el cobro"],
    ids=["no_entiendo", "muy_lento", "no_se_el_cobro"],
)
async def test_ac_007_13_handle_message__non_human_phrases__stay_active(phrase: str) -> None:
    """AC-007-13: sin la intención de atención humana no se deriva y sigue ACTIVE."""
    conv = _verified_conv()
    banking = _banking()
    use_case, _, _, audit = _build(
        [_final("Te explico con más calma qué necesito: indícame el cobro.")], banking, conv
    )

    result = await use_case.handle(conv.conversation_id, phrase)

    assert _calls(banking, "escalate") == []
    assert result.status is ConversationStatus.ACTIVE
    assert result.outcomes == ()
    assert _closed_events(audit) == []


# Regla: RN-007-19 — Si en el mismo turno el cliente pide una persona y declara fraude: con
# identidad verificada, el agente primero bloquea la tarjeta (RN-007-14/15) y luego registra
# **una sola** derivación con `FRAUD_SUSPECTED`, `card_id`, `prior_actions = ["CARD_BLOCKED"]` y la
# nota `Cliente solicitó atención humana`, sin consultar transacciones ni abrir disputas. Sin
# identidad verificada se aplica RN-007-17. En ambos casos se cierra la conversación.
# AC-007-14 · Art. 5
async def test_ac_007_14_handle_message__verified_human_and_fraud__blocks_and_escalates_once() -> (
    None
):
    """AC-007-14: persona y fraude verificada: bloquea CARD-L1 y deriva una sola vez."""
    conv = _verified_conv()
    banking = _banking().respond("block_card", _blocked_card())
    use_case, _, _, audit = _build(
        [
            _tools(
                _call("c1", "solicitar_atencion_humana"),
                _call("c2", "reportar_fraude", card_last4="4321"),
            ),
            _final("Bloqueamos tu tarjeta y una persona continuará la atención."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(
        conv.conversation_id, "Quiero hablar con una persona, sospecho de fraude en la 4321"
    )

    blocks = _calls(banking, "block_card")
    assert len(blocks) == 1
    assert blocks[0]["card_id"] == "CARD-L1"
    assert blocks[0]["reason"] == "FRAUD_SUSPECTED"
    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.FRAUD_SUSPECTED
    assert escalations[0]["card_id"] == "CARD-L1"
    assert escalations[0]["prior_actions"] == (PriorAction.CARD_BLOCKED,)
    assert escalations[0]["note"] == "Cliente solicitó atención humana"
    assert escalations[0]["transaction_id"] is None
    assert _names(banking) == ["block_card", "escalate"]
    assert result.status is ConversationStatus.ESCALATED
    assert [o.kind for o in result.outcomes] == [OutcomeKind.CARD_BLOCKED, OutcomeKind.ESCALATED]
    assert _closed_events(audit) == ["RN-007-19"]


# Regla: RN-007-18 — Cuando el cliente pide expresamente que lo atienda una persona (lo interpreta
# el LLM y lo indica al agente), el agente deriva **de inmediato**, en cualquier momento de la
# conversación, y cierra la conversación. En ese turno no invoca `consultar_transacciones` ni
# `iniciar_disputa`, aunque el mismo mensaje pida otras cosas. La derivación usa el motivo `OTHER`
# y la nota `Cliente solicitó atención humana`, con resumen completo (sin transacción ni tarjeta)
# si está verificado y limitado si no. Frases de frustración o de duda que no piden una persona no
# derivan por sí solas.
# AC-007-16 · Art. 5
@pytest.mark.parametrize(
    "other_call",
    [
        _call("c1", "iniciar_disputa", transaction_id="TX-L1"),
        _call("c1", "evaluar_disputa", transaction_id="TX-L1"),
    ],
    ids=["iniciar_disputa", "evaluar_disputa"],
)
async def test_ac_007_16_handle_message__multiple_topics_with_human_request__no_dispute(
    other_call: ToolCall,
) -> None:
    """AC-007-16: disputar y pedir una persona en un mensaje: no se abre la disputa, se deriva."""
    tx = _tx("TX-L1", "85000.00")
    conv = _verified_conv(tx)
    banking = _banking().respond("open_dispute", _opened(tx))
    use_case, llm, _, _ = _build(
        [
            _tools(other_call, _call("c2", "solicitar_atencion_humana")),
            _final("Una persona continuará la atención."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(
        conv.conversation_id, "Disputa TX-L1 y quiero hablar con una persona"
    )

    assert "open_dispute" not in _names(banking)
    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.OTHER
    assert result.status is ConversationStatus.ESCALATED
    results = _tool_results(llm)
    assert results[0][1] is True
    assert conv.decisions == {}


_LIST_ARGS = {"card_last4": "4321", "date_from": "2026-10-01", "date_to": "2026-10-17"}
_INTERNAL_TEXT = "detalle interno: traza de la base de datos"


# Regla: RN-007-21 — Si `consultar_transacciones`, `iniciar_disputa` o `bloquear_tarjeta`
# devuelven `INTERNAL`, no responden dentro del tiempo límite o devuelven una respuesta que no
# cumple su esquema, el agente no da la acción por realizada. Deriva con
# `UNRECOVERABLE_SYSTEM_FAILURE`, con la transacción o la tarjeta afectada si la identidad está
# verificada, informa al cliente sin detalles técnicos y cierra la conversación. Solo se reintenta
# un error con `retryable = true`.
# Regla: RN-007-24 — Una conversación se **cierra** tras derivar por petición de una persona
# (RN-007-18/19), fraude sin identidad (RN-007-17), identificación fallida (RN-007-04/05), falla
# del sistema (RN-007-21/22) o límite de iteraciones (RN-007-23). En una conversación cerrada, el
# agente no llama al LLM ni a ninguna herramienta y responde con el mensaje fijo `Tu caso ya fue
# derivado a un analista. Una persona continuará la atención.` Las derivaciones de una
# transacción por DP-007-02/03/04/06/07 **no** cierran la conversación.
# AC-007-23 · Art. 10
@pytest.mark.parametrize(
    "failure",
    [
        BankingToolError("INTERNAL", _INTERNAL_TEXT, False),
        BankingToolUnavailableError(_INTERNAL_TEXT),
    ],
    ids=["internal", "unavailable"],
)
async def test_ac_007_23_handle_message__consultar_internal__escalates(
    failure: Exception,
) -> None:
    """AC-007-23: falla de consultar_transacciones: deriva sin datos afectados y cierra."""
    conv = _verified_conv()
    banking = _banking().respond("list_transactions", failure)
    use_case, llm, repo, audit = _build(
        [
            _tools(_call("c1", "consultar_transacciones", **_LIST_ARGS)),
            _final("Tuvimos un problema; una persona continuará la atención."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    kinds = [o.kind for o in result.outcomes]
    assert OutcomeKind.DISPUTE_OPENED not in kinds
    assert OutcomeKind.CARD_BLOCKED not in kinds
    assert kinds == [OutcomeKind.ESCALATED]
    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    assert escalations[0]["transaction_id"] is None
    assert escalations[0]["card_id"] is None
    shown = [content for content, _ in _tool_results(llm)] + [result.reply]
    shown.append(json.dumps([o.__dict__ for o in result.outcomes], default=str))
    for text in shown:
        assert "INTERNAL" not in text
        assert _INTERNAL_TEXT not in text
    assert "open_dispute" not in _names(banking)
    assert "block_card" not in _names(banking)
    assert result.status is ConversationStatus.ESCALATED
    saved = repo.get(result.conversation_id)
    assert saved is not None
    assert saved.status is ConversationStatus.ESCALATED
    assert _closed_events(audit) == ["RN-007-21"]


# Regla: RN-007-21 — Si `consultar_transacciones`, `iniciar_disputa` o `bloquear_tarjeta`
# devuelven `INTERNAL`, no responden dentro del tiempo límite o devuelven una respuesta que no
# cumple su esquema, el agente no da la acción por realizada. Deriva con
# `UNRECOVERABLE_SYSTEM_FAILURE`, con la transacción o la tarjeta afectada si la identidad está
# verificada, informa al cliente sin detalles técnicos y cierra la conversación. Solo se reintenta
# un error con `retryable = true`.
# AC-007-23 · Art. 10
@pytest.mark.parametrize(
    ("script_call", "core_tool", "failure", "affected_key", "affected_value"),
    [
        (
            _call("c1", "evaluar_disputa", transaction_id="TX-L1"),
            "open_dispute",
            BankingToolError("INTERNAL", _INTERNAL_TEXT, False),
            "transaction_id",
            "TX-L1",
        ),
        (
            _call("c1", "evaluar_disputa", transaction_id="TX-L1"),
            "open_dispute",
            BankingToolUnavailableError(f"tiempo límite: {_INTERNAL_TEXT}"),
            "transaction_id",
            "TX-L1",
        ),
        (
            _call("c1", "evaluar_disputa", transaction_id="TX-L1"),
            "open_dispute",
            BankingToolUnavailableError(f"salida inválida: {_INTERNAL_TEXT}"),
            "transaction_id",
            "TX-L1",
        ),
        (
            _call("c1", "reportar_fraude", card_last4="4321"),
            "block_card",
            BankingToolError("INTERNAL", _INTERNAL_TEXT, False),
            "card_id",
            "CARD-L1",
        ),
    ],
    ids=[
        "iniciar_disputa_internal",
        "iniciar_disputa_timeout",
        "iniciar_disputa_invalid_output",
        "bloquear_tarjeta_internal",
    ],
)
async def test_ac_007_23_handle_message__write_failure__escalates_without_leaking_error(
    script_call: ToolCall,
    core_tool: str,
    failure: Exception,
    affected_key: str,
    affected_value: str,
) -> None:
    """AC-007-23: falla de una escritura: no se da por hecha, deriva y no filtra el error."""
    conv = _verified_conv(_tx("TX-L1", "85000.00"))
    banking = _banking().respond(core_tool, failure)
    use_case, llm, repo, audit = _build(
        [_tools(script_call), _final("Tuvimos un problema; una persona continuará.")],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "No reconozco TX-L1")

    kinds = [o.kind for o in result.outcomes]
    assert OutcomeKind.DISPUTE_OPENED not in kinds
    assert OutcomeKind.CARD_BLOCKED not in kinds
    assert core_tool in _names(banking)
    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    assert escalations[0][affected_key] == affected_value
    shown = [content for content, _ in _tool_results(llm)] + [result.reply]
    shown.append(json.dumps([o.__dict__ for o in result.outcomes], default=str))
    for text in shown:
        assert "INTERNAL" not in text
        assert _INTERNAL_TEXT not in text
        assert "Traceback" not in text
    assert result.status is ConversationStatus.ESCALATED
    saved = repo.get(result.conversation_id)
    assert saved is not None
    assert saved.status is ConversationStatus.ESCALATED
    assert _closed_events(audit) == ["RN-007-21"]


# Regla: RN-011-10 — NOT_FOUND de una escritura sigue derivando por RN-007-21.
# AC-011-11
async def test_ac_011_11_handle__not_found_in_write_tool_still_escalates() -> None:
    """AC-011-11: NOT_FOUND de iniciar_disputa deriva con UNRECOVERABLE_SYSTEM_FAILURE."""
    conv = _verified_conv(_tx("TX-L1", "85000.00"))
    banking = _banking().respond("open_dispute", not_found())
    use_case, _llm, _repo, audit = _build(
        [
            _tools(_call("c1", "evaluar_disputa", transaction_id="TX-L1")),
            _final("Tuvimos un problema; una persona continuará."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "No reconozco TX-L1")

    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    assert result.status is ConversationStatus.ESCALATED
    assert _closed_events(audit) == ["RN-007-21"]


# Regla: RN-007-22 — Si `escalar_a_analista` devuelve `INTERNAL` o falla, el agente no reintenta
# automáticamente. Informa al cliente que su caso no pudo derivarse y que vuelva a contactar al
# banco, lo audita y cierra la conversación. Si devuelve `IDENTITY_NOT_VERIFIED`, repite la
# solicitud sin datos del cliente.
# AC-007-24 · Art. 10
async def test_ac_007_24_handle_message__escalation_internal() -> None:
    """AC-007-24: si escalar_a_analista falla, una sola llamada y outcome ESCALATION_FAILED."""
    conv = _verified_conv()
    banking = FakeBankingTools().respond(
        "escalate", BankingToolError("INTERNAL", _INTERNAL_TEXT, False)
    )
    use_case, _, repo, audit = _build(
        [
            _tools(_call("c1", "solicitar_atencion_humana")),
            _final("No pudimos derivar tu caso; vuelve a contactar al banco."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Quiero hablar con una persona")

    assert len(_calls(banking, "escalate")) == 1
    assert [o.kind for o in result.outcomes] == [OutcomeKind.ESCALATION_FAILED]
    assert result.outcomes[0].reason == messages.OUTCOME_REASONS[OutcomeKind.ESCALATION_FAILED]
    assert (
        result.outcomes[0].next_steps == messages.OUTCOME_NEXT_STEPS[OutcomeKind.ESCALATION_FAILED]
    )
    assert result.status is ConversationStatus.ESCALATED
    saved = repo.get(result.conversation_id)
    assert saved is not None
    assert saved.status is ConversationStatus.ESCALATED
    assert _closed_events(audit) == ["RN-007-18"]


def _harmless(index: int) -> LLMResponse:
    """Petición inocua: la transacción no está entre las consultadas."""
    return _tools(_call(f"h{index}", "evaluar_disputa", transaction_id="TX-NOEXISTE"))


def _dangerous() -> LLMResponse:
    """Peticiones que abrirían una disputa y bloquearían una tarjeta si se ejecutaran."""
    return _tools(
        _call("d1", "evaluar_disputa", transaction_id="TX-L1"),
        _call("d2", "reportar_fraude", card_last4="4321"),
    )


_LIMIT_TEXT = (
    f"{messages.OUTCOME_REASONS[OutcomeKind.ITERATION_LIMIT]} "
    f"{messages.OUTCOME_NEXT_STEPS[OutcomeKind.ITERATION_LIMIT]}"
)
_LLM_FAILURE_TEXT = (
    f"{messages.OUTCOME_REASONS[OutcomeKind.LLM_FAILURE]} "
    f"{messages.OUTCOME_NEXT_STEPS[OutcomeKind.LLM_FAILURE]}"
)
_UNKNOWN_TOOL_TURN = _tools(
    _call("d1", "evaluar_disputa", transaction_id="TX-L1"), _call("d3", "no_existe")
)
_INVALID_ARGS_TURN = _tools(
    _call("d1", "evaluar_disputa", transaction_id="TX-L1"), _call("d3", "evaluar_disputa")
)


# Regla: RN-007-23 — El loop admite como máximo **8** llamadas al LLM por cada mensaje del cliente
# (configurable). Al superarlo, o si el LLM falla o devuelve una salida inválida, el agente no
# ejecuta ninguna acción pendiente de ese turno. Deriva con `INCONCLUSIVE_RULES` si se superó el
# límite, o con `UNRECOVERABLE_SYSTEM_FAILURE` si falló el LLM, informa al cliente con un mensaje
# fijo y cierra la conversación.
# Regla: RN-007-24 — Una conversación se **cierra** tras derivar por petición de una persona
# (RN-007-18/19), fraude sin identidad (RN-007-17), identificación fallida (RN-007-04/05), falla
# del sistema (RN-007-21/22) o límite de iteraciones (RN-007-23). En una conversación cerrada, el
# agente no llama al LLM ni a ninguna herramienta y responde con el mensaje fijo `Tu caso ya fue
# derivado a un analista. Una persona continuará la atención.` Las derivaciones de una
# transacción por DP-007-02/03/04/06/07 **no** cierran la conversación.
# AC-007-25 · Art. 10
@pytest.mark.parametrize(
    ("script", "requests", "reason", "kind", "reply"),
    [
        (
            [*(_harmless(i) for i in range(7)), _dangerous(), _dangerous()],
            8,
            EscalationReason.INCONCLUSIVE_RULES,
            OutcomeKind.ITERATION_LIMIT,
            _LIMIT_TEXT,
        ),
        (
            [LLMError("proveedor caído")],
            1,
            EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE,
            OutcomeKind.LLM_FAILURE,
            _LLM_FAILURE_TEXT,
        ),
        (
            [_UNKNOWN_TOOL_TURN],
            1,
            EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE,
            OutcomeKind.LLM_FAILURE,
            _LLM_FAILURE_TEXT,
        ),
        (
            [_INVALID_ARGS_TURN],
            1,
            EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE,
            OutcomeKind.LLM_FAILURE,
            _LLM_FAILURE_TEXT,
        ),
    ],
    ids=["nine_calls_iteration_limit", "llm_error", "unknown_tool", "invalid_arguments"],
)
async def test_ac_007_25_handle_message__iteration_limit_and_llm_failure(
    script: list[LLMResponse | LLMError],
    requests: int,
    reason: EscalationReason,
    kind: OutcomeKind,
    reply: str,
) -> None:
    """AC-007-25: tope o falla del LLM: deriva, no ejecuta lo pendiente y responde fijo."""
    tx = _tx("TX-L1", "85000.00")
    conv = _verified_conv(tx)
    banking = _banking().respond("open_dispute", _opened(tx)).respond("block_card", _blocked_card())
    use_case, llm, repo, audit = _build(script, banking, conv, max_iterations=8)

    result = await use_case.handle(conv.conversation_id, "No reconozco TX-L1")

    assert len(llm.requests) == requests
    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is reason
    _assert_limited(escalations[0])
    assert "open_dispute" not in _names(banking)
    assert "block_card" not in _names(banking)
    assert result.reply == reply
    assert [o.kind for o in result.outcomes] == [kind]
    assert result.outcomes[0].rule == "RN-007-23"
    assert result.outcomes[0].reference == "E-0001"
    assert result.status is ConversationStatus.ESCALATED
    saved = repo.get(result.conversation_id)
    assert saved is not None
    assert saved.status is ConversationStatus.ESCALATED
    assert _closed_events(audit) == ["RN-007-23"]


# Regla: RN-007-23 — El loop admite como máximo **8** llamadas al LLM por cada mensaje del cliente
# (configurable). Al superarlo, o si el LLM falla o devuelve una salida inválida, el agente no
# ejecuta ninguna acción pendiente de ese turno. Deriva con `INCONCLUSIVE_RULES` si se superó el
# límite, o con `UNRECOVERABLE_SYSTEM_FAILURE` si falló el LLM, informa al cliente con un mensaje
# fijo y cierra la conversación.
# AC-007-25 · Art. 10
async def test_ac_007_25_handle_message__eight_calls_with_final_reply__stays_active() -> None:
    """AC-007-25: 8 llamadas y respuesta final en la 8.ª: no se deriva y sigue ACTIVE."""
    conv = _verified_conv(_tx("TX-L1", "85000.00"))
    banking = _banking()
    use_case, llm, _, audit = _build(
        [*(_harmless(i) for i in range(7)), _final("Listo, ¿algo más?")],
        banking,
        conv,
        max_iterations=8,
    )

    result = await use_case.handle(conv.conversation_id, "No reconozco TX-L1")

    assert len(llm.requests) == 8
    assert _calls(banking, "escalate") == []
    assert result.reply == "Listo, ¿algo más?"
    assert result.outcomes == ()
    assert result.status is ConversationStatus.ACTIVE
    assert _closed_events(audit) == []


_VERIFY_ARGS = {"birth_date": "1990-05-17", "document_issue_date": "2010-06-01"}


def _closing_first_turn(cause: str) -> tuple[Conversation, FakeBankingTools, list[LLMResponse]]:
    """Conversación y guion del primer turno que la deja derivada por `cause`."""
    if cause == "human_request":
        return (
            _verified_conv(),
            _banking(),
            [_tools(_call("c1", "solicitar_atencion_humana")), _final("Una persona te atenderá.")],
        )
    if cause == "verification_exhausted":
        return (
            _located_conv(),
            _banking().respond("verify_identity", VerificationResult(False, 0, True)),
            [_tools(_call("c1", "verificar_identidad", **_VERIFY_ARGS)), _final("Derivamos.")],
        )
    return (
        _verified_conv(),
        _banking().respond("list_transactions", BankingToolError("INTERNAL", "x", False)),
        [_tools(_call("c1", "consultar_transacciones", **_LIST_ARGS)), _final("Derivamos.")],
    )


# Regla: RN-007-24 — Una conversación se **cierra** tras derivar por petición de una persona
# (RN-007-18/19), fraude sin identidad (RN-007-17), identificación fallida (RN-007-04/05), falla
# del sistema (RN-007-21/22) o límite de iteraciones (RN-007-23). En una conversación cerrada, el
# agente no llama al LLM ni a ninguna herramienta y responde con el mensaje fijo `Tu caso ya fue
# derivado a un analista. Una persona continuará la atención.` Las derivaciones de una
# transacción por DP-007-02/03/04/06/07 **no** cierran la conversación.
# AC-007-26 · Art. 10
@pytest.mark.parametrize(
    "cause",
    ["human_request", "verification_exhausted", "system_failure"],
    ids=["human_request", "verification_exhausted", "system_failure"],
)
async def test_ac_007_26_handle_message__closed_conversation__no_calls(cause: str) -> None:
    """AC-007-26: tras derivar, otro mensaje no llama al LLM ni a herramientas."""
    conv, banking, script = _closing_first_turn(cause)
    use_case, llm, repo, audit = _build([*script, _final("No debería llamarse.")], banking, conv)
    first = await use_case.handle(conv.conversation_id, "primer mensaje")
    assert first.status is ConversationStatus.ESCALATED
    llm_calls = len(llm.requests)
    banking_calls = list(banking.calls)
    events = len(audit.events)

    result = await use_case.handle(conv.conversation_id, "¿hay novedades?")

    assert len(llm.requests) == llm_calls
    assert banking.calls == banking_calls
    assert result.reply == messages.CONVERSATION_CLOSED_MESSAGE
    assert result.outcomes == ()
    assert result.status is ConversationStatus.ESCALATED
    assert len(audit.events) == events
    saved = repo.get(result.conversation_id)
    assert saved is not None
    assert saved.status is ConversationStatus.ESCALATED


# Regla: RN-007-24 — Una conversación se **cierra** tras derivar por petición de una persona
# (RN-007-18/19), fraude sin identidad (RN-007-17), identificación fallida (RN-007-04/05), falla
# del sistema (RN-007-21/22) o límite de iteraciones (RN-007-23). En una conversación cerrada, el
# agente no llama al LLM ni a ninguna herramienta y responde con el mensaje fijo `Tu caso ya fue
# derivado a un analista. Una persona continuará la atención.` Las derivaciones de una
# transacción por DP-007-02/03/04/06/07 **no** cierran la conversación.
# AC-007-26 · Art. 10
async def test_ac_007_26_handle_message__dp_007_03_escalation__stays_active() -> None:
    """AC-007-26: tras una derivación por DP-007-03 la conversación sigue ACTIVE y atiende."""
    conv = _verified_conv(_tx("TX-L1", "800000.00"))
    banking = _banking()
    use_case, llm, _, _ = _build(
        [
            _tools(_call("c1", "evaluar_disputa", transaction_id="TX-L1")),
            _final("Derivamos tu caso por el monto."),
            _final("Claro, dime qué más necesitas."),
        ],
        banking,
        conv,
    )

    first = await use_case.handle(conv.conversation_id, "No reconozco TX-L1")
    second = await use_case.handle(conv.conversation_id, "Una consulta más")

    assert first.status is ConversationStatus.ACTIVE
    assert [o.rule for o in first.outcomes] == ["DP-007-03"]
    assert second.status is ConversationStatus.ACTIVE
    assert second.reply == "Claro, dime qué más necesitas."
    assert len(llm.requests) == 3


# Regla: RN-007-25 — Cada respuesta de `POST /api/chat` incluye el texto redactado por el LLM
# (`reply`) y la lista estructurada `outcomes` con lo ocurrido en el turno (§7.3): por cada acción
# o decisión, su tipo, la transacción o tarjeta enmascarada, la regla aplicada, el motivo y los
# próximos pasos, ambos en español y con el texto fijo de §5 o de §7.3. El LLM recibe esos
# `outcomes` para redactar la respuesta, pero no puede alterarlos.
# AC-007-29 · Art. 5
async def test_ac_007_29_handle_message__card_blocked_outcome() -> None:
    """AC-007-29: reportar fraude produce CARD_BLOCKED con textos de messages, que el LLM recibe."""
    conv = _verified_conv()
    banking = _banking().respond("block_card", _blocked_card())
    use_case, llm, _, _ = _build(
        [
            _tools(_call("c1", "reportar_fraude", card_last4="4321")),
            _final("Bloqueamos tu tarjeta."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Sospecho de fraude con mi tarjeta 4321")

    blocked = result.outcomes[0]
    assert blocked.kind is OutcomeKind.CARD_BLOCKED
    assert blocked.rule == "RN-007-14"
    assert blocked.reason == messages.OUTCOME_REASONS[OutcomeKind.CARD_BLOCKED]
    assert blocked.next_steps == messages.OUTCOME_NEXT_STEPS[OutcomeKind.CARD_BLOCKED]
    assert blocked.reason.strip()
    assert blocked.next_steps.strip()
    [(content, is_error)] = _tool_results(llm)
    assert not is_error
    seen = json.loads(content)["outcomes"]
    assert [(o["kind"], o["rule"], o["reason"], o["next_steps"]) for o in seen][0] == (
        "CARD_BLOCKED",
        "RN-007-14",
        messages.OUTCOME_REASONS[OutcomeKind.CARD_BLOCKED],
        messages.OUTCOME_NEXT_STEPS[OutcomeKind.CARD_BLOCKED],
    )
    assert result.status is ConversationStatus.ACTIVE


# Soporte de tests: reportar_fraude sin persona y sin forma de determinar la tarjeta pide los
# últimos 4 dígitos, sin escrituras ni outcomes (RN-007-15) · Art. 3
async def test_handle_message__fraud_without_card_digits__asks_digits_without_writes() -> None:
    """Con 2 tarjetas y sin dígitos, el tool_result pide los dígitos y no hay escrituras."""
    conv = ConversationBuilder().verified("C-0001", (_CARD_1, _CARD_2)).build()
    banking = _banking()
    use_case, llm, _, _ = _build(
        [_tools(_call("c1", "reportar_fraude")), _final("¿Cuáles son los últimos 4 dígitos?")],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Sospecho de fraude con mi tarjeta")

    assert banking.calls == []
    [(content, is_error)] = _tool_results(llm)
    assert not is_error
    payload = json.loads(content)
    assert payload["result"] == "needs_card_digits"
    assert "4 dígitos" in payload["message"]
    assert "outcomes" not in payload
    assert result.outcomes == ()
    assert result.status is ConversationStatus.ACTIVE


# Soporte de tests: reportar_fraude con transaction_ids no conocidas o mal formados · Art. 3
async def test_handle_message__fraud_with_malformed_transaction_ids__llm_failure() -> None:
    """transaction_ids que no es una lista de textos es una salida inválida del LLM."""
    conv = _verified_conv()
    banking = _banking()
    use_case, _, _, _ = _build(
        [_tools(_call("c1", "reportar_fraude", transaction_ids="TX-L1"))], banking, conv
    )

    result = await use_case.handle(conv.conversation_id, "Fraude")

    assert [o.kind for o in result.outcomes] == [OutcomeKind.LLM_FAILURE]
    assert "block_card" not in _names(banking)


# Soporte de tests: la falla de una lectura (buscar_cliente, verificar_identidad o
# consultar_transacciones) deriva con RN-007-21, cierra la conversación y audita
# `conversation_closed` · Art. 3
@pytest.mark.parametrize(
    ("tool", "arguments", "core_tool", "make_conv"),
    [
        ("buscar_cliente", {"document": "D-1001"}, "search_customer", ConversationBuilder().build),
        ("verificar_identidad", _VERIFY_ARGS, "verify_identity", _located_conv),
        ("consultar_transacciones", _LIST_ARGS, "list_transactions", _verified_conv),
    ],
    ids=["buscar_cliente", "verificar_identidad", "consultar_transacciones"],
)
async def test_handle_message__read_failure__escalates_closes_and_audits(
    tool: str,
    arguments: dict[str, object],
    core_tool: str,
    make_conv: Callable[[], Conversation],
) -> None:
    """RN-007-21: una lectura que falla cierra la conversación y el LLM no ve el error."""
    conv = make_conv()
    banking = _banking().respond(core_tool, BankingToolError("INTERNAL", _INTERNAL_TEXT, False))
    use_case, llm, _, audit = _build(
        [_tools(_call("c1", tool, **arguments)), _final("Derivamos tu caso.")], banking, conv
    )

    result = await use_case.handle(conv.conversation_id, "Mis datos")

    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    assert escalations[0]["note"] == f"RN-007-21: falla irrecuperable en {tool} (INTERNAL)"
    [(content, is_error)] = _tool_results(llm)
    assert is_error
    assert "INTERNAL" not in content
    assert _INTERNAL_TEXT not in content
    assert result.status is ConversationStatus.ESCALATED
    assert _closed_events(audit) == ["RN-007-21"]


# Soporte de tests: si la derivación por límite o falla del LLM no se puede registrar, el reply
# es el texto fijo de ESCALATION_FAILED y la conversación se cierra igualmente (RN-007-22) · Art. 3
async def test_handle_message__llm_failure_and_escalation_failure__fixed_failed_reply() -> None:
    """Con ESCALATION_FAILED el reply fijo es el de §7.3 y los outcomes traen ambos fallos."""
    conv = _verified_conv()
    banking = FakeBankingTools().respond("escalate", BankingToolError("INTERNAL", "x", False))
    use_case, _, _, audit = _build([LLMError("caído")], banking, conv)

    result = await use_case.handle(conv.conversation_id, "Hola")

    assert result.reply == (
        f"{messages.OUTCOME_REASONS[OutcomeKind.ESCALATION_FAILED]} "
        f"{messages.OUTCOME_NEXT_STEPS[OutcomeKind.ESCALATION_FAILED]}"
    )
    assert [o.kind for o in result.outcomes] == [
        OutcomeKind.LLM_FAILURE,
        OutcomeKind.ESCALATION_FAILED,
    ]
    assert len(_calls(banking, "escalate")) == 1
    assert result.status is ConversationStatus.ESCALATED
    assert _closed_events(audit) == ["RN-007-23"]


# Soporte de tests: persona y fraude con tarjeta indeterminable: no se pregunta ni se bloquea,
# se deriva FRAUD_SUSPECTED con la nota y se cierra (RN-007-19, RN-007-15) · Art. 3
async def test_handle_message__human_and_fraud_undetermined_card__escalates_without_block() -> None:
    """Con 2 tarjetas y sin dígitos, persona y fraude derivan sin bloquear y cierran."""
    conv = ConversationBuilder().verified("C-0001", (_CARD_1, _CARD_2)).build()
    banking = _banking()
    use_case, _, _, audit = _build(
        [
            _tools(_call("c1", "solicitar_atencion_humana"), _call("c2", "reportar_fraude")),
            _final("Una persona continuará la atención."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Quiero una persona; hay fraude")

    assert "block_card" not in _names(banking)
    escalations = _calls(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.FRAUD_SUSPECTED
    assert escalations[0]["card_id"] is None
    assert escalations[0]["prior_actions"] == ()
    assert escalations[0]["note"] == "Cliente solicitó atención humana"
    assert result.status is ConversationStatus.ESCALATED
    assert _closed_events(audit) == ["RN-007-19"]
