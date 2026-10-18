"""Tests del loop de HandleCustomerMessage guiado por la razón de parada.

Spec 007 (v0.2.0): AC-007-35 a AC-007-43.
"""

import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM, end_turn_response, tool_use_response
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.audit_log import AgentAuditEvent
from dispute_agent.application.ports.banking_tools import (
    DisputeOpened,
    EscalationRegistered,
    TransactionPage,
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
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus, KnownCard
from dispute_agent.domain.models.decision import EscalationReason
from dispute_agent.domain.models.outcome import OutcomeKind
from dispute_agent.domain.models.transaction import DisputedTransaction
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 17)
_CARD = KnownCard("CARD-L1", "4321")
_LIST_ARGS = {"card_last4": "4321", "date_from": "2026-10-01", "date_to": "2026-10-17"}
_FAILURE_REPLY = "Tuvimos un problema al procesar tu solicitud. Una persona continuará la atención."
_LIMIT_REPLY = (
    "No pudimos completar tu solicitud automáticamente. Una persona continuará la atención."
)


class _Repo:
    def __init__(self, *conversations: Conversation) -> None:
        self.items = {c.conversation_id: c for c in conversations}

    def get(self, conversation_id: str) -> Conversation | None:
        return self.items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self.items[conversation.conversation_id] = conversation


def _tx(tx_id: str = "TX-L1") -> DisputedTransaction:
    return (
        DisputedTransactionBuilder()
        .transaction_id(tx_id)
        .card("CARD-L1", "**** 4321")
        .amount("85000.00", "COP")
        .days_ago(7, _TODAY)
        .national()
        .build()
    )


def _verified_conv(*transactions: DisputedTransaction) -> Conversation:
    conv = ConversationBuilder().verified("C-0001", (_CARD,)).build()
    conv.remember_transactions(transactions)
    return conv


def _banking() -> FakeBankingTools:
    registered = EscalationRegistered(
        escalation_id="E-0001", status="PENDING", escalated_at=_NOW, reason="OTHER"
    )
    return (
        FakeBankingTools()
        .respond("escalate", registered)
        .respond("list_transactions", TransactionPage((_tx(),), False))
    )


def _build(
    script: list[LLMResponse | LLMError],
    banking: FakeBankingTools,
    conv: Conversation,
    max_iterations: int = 8,
    infer_stop_reason: bool = True,
) -> tuple[HandleCustomerMessage, FakeLLM, FakeAgentAuditLog]:
    llm = FakeLLM(script, infer_stop_reason=infer_stop_reason)
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
        _Repo(conv),
        dispute_actions,
        fraud_actions,
        escalation,
        audit,
        clock,
        SequentialIdGenerator(),
        max_iterations,
    )
    return use_case, llm, audit


def _call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def _names(banking: FakeBankingTools) -> list[str]:
    return [name for name, _ in banking.calls]


def _closed_rules(audit: FakeAgentAuditLog) -> list[str | None]:
    return [e.rule for e in audit.events if e.event_type == "conversation_closed"]


# Regla: RN-007-32 — Cada respuesta del LLM trae su **razón de parada**, y el agente decide solo
# por ella si continúa o responde. Con `tool_use`, ejecuta las herramientas pedidas, siempre a
# través de las guardas de las reglas anteriores. Devuelve al LLM un resultado por cada petición
# en la misma llamada siguiente, también para las bloqueadas o fallidas. Con `end_turn`, envía al
# cliente el texto de la respuesta, tras el filtro de RN-007-26, y no invoca más herramientas ni
# llama otra vez al LLM en ese turno. El número de llamadas, salvo el tope de RN-007-23, y el
# contenido del texto no influyen en esta decisión.
# AC-007-35 · Art. 5
async def test_ac_007_35_handle_message__tool_use__continues_with_tool_result() -> None:
    """AC-007-35: tool_use ejecuta la herramienta y la 2.ª llamada recibe su tool_result."""
    conv = _verified_conv()
    banking = _banking()
    use_case, llm, _ = _build(
        [
            tool_use_response(_call("c1", "consultar_transacciones", **_LIST_ARGS)),
            end_turn_response("Encontré tus movimientos."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Quiero ver mis movimientos")

    assert _names(banking) == ["list_transactions"]
    assert len(llm.requests) == 2
    results = [r for m in llm.requests[1].messages for r in m.tool_results]
    assert [r.tool_call_id for r in results] == ["c1"]
    assert json.loads(results[0].content)["transactions"][0]["transaction_id"] == "TX-L1"
    assert result.reply == "Encontré tus movimientos."
    assert result.status is ConversationStatus.ACTIVE


# Regla: RN-007-32 — Cada respuesta del LLM trae su **razón de parada**, y el agente decide solo
# por ella si continúa o responde. Con `tool_use`, ejecuta las herramientas pedidas, siempre a
# través de las guardas de las reglas anteriores. Devuelve al LLM un resultado por cada petición
# en la misma llamada siguiente, también para las bloqueadas o fallidas. Con `end_turn`, envía al
# cliente el texto de la respuesta, tras el filtro de RN-007-26, y no invoca más herramientas ni
# llama otra vez al LLM en ese turno. El número de llamadas, salvo el tope de RN-007-23, y el
# contenido del texto no influyen en esta decisión.
# AC-007-36 · Art. 5
async def test_ac_007_36_handle_message__end_turn__replies_once() -> None:
    """AC-007-36: end_turn responde el texto, con una sola llamada y sin herramientas."""
    conv = _verified_conv()
    banking = _banking()
    use_case, llm, _ = _build([end_turn_response("¿Qué cobro quieres revisar?")], banking, conv)

    result = await use_case.handle(conv.conversation_id, "Hola")

    assert result.reply == "¿Qué cobro quieres revisar?"
    assert len(llm.requests) == 1
    assert banking.calls == []
    assert result.status is ConversationStatus.ACTIVE


# Regla: RN-007-23 — El loop admite como máximo **8** llamadas al LLM por cada mensaje del cliente
# (configurable). Ese máximo es solo una red de seguridad: el loop no termina por contar llamadas,
# sino por la razón de parada (RN-007-32).
# Regla: RN-007-32 — Cada respuesta del LLM trae su **razón de parada**, y el agente decide solo
# por ella si continúa o responde. El número de llamadas, salvo el tope de RN-007-23, y el
# contenido del texto no influyen en esta decisión.
# AC-007-37 · Art. 5
async def test_ac_007_37_handle_message__several_steps__not_cut_by_count() -> None:
    """AC-007-37: tres pasos tool_use seguidos se ejecutan en orden y luego se responde."""
    conv = ConversationBuilder().located("C-0001", (_CARD,)).build()
    tx = _tx()
    opened = DisputeOpened(
        dispute_id="D-0001",
        status="OPEN",
        opened_at=_NOW,
        reason="UNRECOGNIZED_CHARGE",
        transaction=tx,
    )
    banking = (
        _banking()
        .respond("verify_identity", VerificationResult(True, 3, False))
        .respond("open_dispute", opened)
    )
    use_case, llm, _ = _build(
        [
            tool_use_response(
                _call(
                    "c1",
                    "verificar_identidad",
                    birth_date="1990-01-01",
                    document_issue_date="2010-01-01",
                )
            ),
            tool_use_response(_call("c2", "consultar_transacciones", **_LIST_ARGS)),
            tool_use_response(_call("c3", "evaluar_disputa", transaction_id="TX-L1")),
            end_turn_response("Abrí tu disputa."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Mis datos; no reconozco TX-L1")

    assert _names(banking) == ["verify_identity", "list_transactions", "open_dispute"]
    assert banking.calls[2][1]["transaction_id"] == "TX-L1"
    assert len(llm.requests) == 4
    assert result.reply == "Abrí tu disputa."
    assert "escalate" not in _names(banking)
    assert result.status is ConversationStatus.ACTIVE


# Regla: RN-007-23 — El loop admite como máximo **8** llamadas al LLM por cada mensaje del cliente
# (configurable). Ese máximo es solo una red de seguridad: el loop no termina por contar llamadas,
# sino por la razón de parada (RN-007-32). Si la llamada número 8 termina pidiendo herramientas,
# se considera superado el límite. Deriva con `INCONCLUSIVE_RULES` si se superó el límite.
# Informa al cliente con un mensaje fijo y cierra la conversación.
# Regla: RN-007-32 — Cada respuesta del LLM trae su **razón de parada**, y el agente decide solo
# por ella si continúa o responde. El número de llamadas, salvo el tope de RN-007-23, y el
# contenido del texto no influyen en esta decisión.
# AC-007-38 · Art. 10
@pytest.mark.parametrize(
    ("max_iterations", "steps", "executed", "llm_calls", "escalated"),
    [
        (8, 7, 7, 8, False),
        (8, 8, 7, 8, True),
        (8, 9, 7, 8, True),
        (3, 2, 2, 3, False),
    ],
    ids=["8_max_7_steps", "8_max_8_steps", "8_max_9_steps", "3_max_2_steps"],
)
async def test_ac_007_38_handle_message__iteration_cap__safety_net_only(
    max_iterations: int, steps: int, executed: int, llm_calls: int, escalated: bool
) -> None:
    """AC-007-38: el tope solo actúa si la última llamada permitida aún pide herramientas."""
    conv = _verified_conv()
    banking = _banking()
    script: list[LLMResponse | LLMError] = [
        tool_use_response(_call(f"c{n}", "consultar_transacciones", **_LIST_ARGS))
        for n in range(1, steps + 1)
    ]
    script.append(end_turn_response("Listo, ya vi tus movimientos."))
    use_case, llm, _ = _build(script, banking, conv, max_iterations=max_iterations)

    result = await use_case.handle(conv.conversation_id, "Mis movimientos")

    assert _names(banking).count("list_transactions") == executed
    assert len(llm.requests) == llm_calls
    if escalated:
        [escalation] = [args for name, args in banking.calls if name == "escalate"]
        assert escalation["reason"] is EscalationReason.INCONCLUSIVE_RULES
        assert [o.kind for o in result.outcomes] == [OutcomeKind.ITERATION_LIMIT]
        assert result.reply == _LIMIT_REPLY
        assert result.status is ConversationStatus.ESCALATED
    else:
        assert "escalate" not in _names(banking)
        assert result.reply == "Listo, ya vi tus movimientos."
        assert result.status is ConversationStatus.ACTIVE


# Regla: RN-007-32 — Cada respuesta del LLM trae su **razón de parada**, y el agente decide solo
# por ella si continúa o responde. Con `end_turn`, envía al cliente el texto de la respuesta, tras
# el filtro de RN-007-26, y no invoca más herramientas ni llama otra vez al LLM en ese turno. El
# número de llamadas, salvo el tope de RN-007-23, y el contenido del texto no influyen en esta
# decisión.
# Regla: RN-007-33 — El texto del LLM nunca se interpreta para ejecutar acciones ni para darlas
# por hechas. Solo se ejecutan las peticiones estructuradas de herramientas de una respuesta
# `tool_use`. Lo que el sistema realizó en el turno consta en `outcomes`, que solo contiene lo
# ejecutado. El `reply` no se filtra por palabras.
# AC-007-39 · Art. 5
@pytest.mark.parametrize(
    "text",
    ["Voy a consultar sus movimientos.", "Ya bloqueé su tarjeta."],
    ids=["promises_query", "claims_block"],
)
async def test_ac_007_39_handle_message__words_do_not_drive_actions(text: str) -> None:
    """AC-007-39: el texto de un end_turn no ejecuta nada ni cambia los outcomes."""
    conv = _verified_conv()
    banking = _banking()
    use_case, llm, _ = _build([end_turn_response(text)], banking, conv)

    result = await use_case.handle(conv.conversation_id, "Hola")

    assert result.reply == text
    assert len(llm.requests) == 1
    assert banking.calls == []
    assert result.outcomes == ()
    assert result.status is ConversationStatus.ACTIVE


def _assert_llm_failure(
    result: object,
    banking: FakeBankingTools,
    audit: FakeAgentAuditLog,
    rule: str,
) -> None:
    assert isinstance(result, ChatTurnResult)
    escalations = [args for name, args in banking.calls if name == "escalate"]
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
    assert [o.kind for o in result.outcomes] == [OutcomeKind.LLM_FAILURE]
    assert result.outcomes[0].rule == rule
    assert result.reply == _FAILURE_REPLY
    assert result.status is ConversationStatus.ESCALATED
    assert _closed_rules(audit) == [rule]


# Regla: RN-007-23 — El agente tampoco sigue si el LLM falla o devuelve una salida inválida, lo
# que incluye una razón de parada inesperada o una respuesta incoherente o vacía (RN-007-34,
# RN-007-35). En esos casos no ejecuta ninguna acción pendiente de ese turno. Deriva con
# `UNRECOVERABLE_SYSTEM_FAILURE` si falló el LLM o su salida es inválida. Informa al cliente con
# un mensaje fijo y cierra la conversación.
# Regla: RN-007-24 — Una conversación se **cierra** tras derivar por petición de una persona
# (RN-007-18/19), fraude sin identidad (RN-007-17), identificación fallida (RN-007-04/05), falla
# del sistema (RN-007-21/22) o límite de iteraciones (RN-007-23).
# Regla: RN-007-34 — Una razón de parada distinta de `tool_use` y `end_turn` es una salida
# inválida. Esto incluye `max_tokens` (respuesta cortada por límite de longitud), `refusal`
# (rechazo), `pause_turn` (pausa sin terminar), `stop_sequence`, cualquier otro valor y la
# ausencia de razón. El agente no ejecuta **ninguna** de las herramientas pedidas en esa
# respuesta, y aplica RN-007-23 como falla del LLM: deriva con `UNRECOVERABLE_SYSTEM_FAILURE`,
# responde con el mensaje fijo de `LLM_FAILURE` y cierra la conversación.
# AC-007-40 · Art. 10
@pytest.mark.parametrize(
    "stop_reason",
    ["max_tokens", "refusal", "pause_turn", "stop_sequence", "other_reason", None],
    ids=["max_tokens", "refusal", "pause_turn", "stop_sequence", "other_reason", "absent"],
)
async def test_ac_007_40_handle_message__unexpected_stop_reason__escalates_without_actions(
    stop_reason: str | None,
) -> None:
    """AC-007-40: una razón de parada inesperada o ausente deriva sin ejecutar acciones."""
    conv = _verified_conv()
    banking = _banking()
    use_case, llm, audit = _build(
        [LLMResponse(text="Ya abrí tu disputa.", stop_reason=stop_reason)],
        banking,
        conv,
        infer_stop_reason=False,
    )

    result = await use_case.handle(conv.conversation_id, "Hola")

    assert _names(banking) == ["escalate"]
    _assert_llm_failure(result, banking, audit, "RN-007-34")
    assert "Ya abrí tu disputa." not in result.reply
    assert len(llm.requests) == 1


# Regla: RN-007-34 — Una razón de parada distinta de `tool_use` y `end_turn` es una salida
# inválida. Esto incluye `max_tokens` (respuesta cortada por límite de longitud). El agente no
# ejecuta **ninguna** de las herramientas pedidas en esa respuesta, ni siquiera las que llegaron
# completas, y aplica RN-007-23 como falla del LLM: deriva con `UNRECOVERABLE_SYSTEM_FAILURE`,
# responde con el mensaje fijo de `LLM_FAILURE` y cierra la conversación.
# AC-007-41 · Art. 10
async def test_ac_007_41_handle_message__truncated_with_complete_calls__executes_none() -> None:
    """AC-007-41: max_tokens con peticiones completas no ejecuta ninguna y deriva."""
    conv = _verified_conv(_tx("TX-L1"))
    banking = _banking()
    use_case, _, audit = _build(
        [
            LLMResponse(
                tool_calls=(
                    _call("c1", "evaluar_disputa", transaction_id="TX-L1"),
                    _call("c2", "reportar_fraude", card_last4="4321"),
                ),
                stop_reason="max_tokens",
            )
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "No reconozco TX-L1 y sospecho fraude")

    assert _names(banking) == ["escalate"]
    kinds = [o.kind for o in result.outcomes]
    assert OutcomeKind.DISPUTE_OPENED not in kinds
    assert OutcomeKind.CARD_BLOCKED not in kinds
    assert not [e for e in audit.events if e.event_type == "decision"]
    assert "TX-L1" not in conv.decisions
    _assert_llm_failure(result, banking, audit, "RN-007-34")


# Regla: RN-007-24 — Una conversación se **cierra** tras derivar por petición de una persona
# (RN-007-18/19), fraude sin identidad (RN-007-17), identificación fallida (RN-007-04/05), falla
# del sistema (RN-007-21/22) o límite de iteraciones (RN-007-23).
# Regla: RN-007-35 — Una respuesta con una razón de parada válida pero incoherente o vacía también
# es una salida inválida, con el mismo tratamiento de RN-007-34. Son tres casos: `tool_use` sin
# ninguna petición de herramienta, `end_turn` con peticiones de herramientas (que no se
# ejecutan), y `end_turn` sin texto o solo con espacios.
# AC-007-42 · Art. 10
@pytest.mark.parametrize(
    "response",
    [
        LLMResponse(text="", stop_reason="end_turn"),
        LLMResponse(text=" \n\n  \n", stop_reason="end_turn"),
        LLMResponse(
            text="Voy a consultar.",
            tool_calls=(_call("c1", "consultar_transacciones", **_LIST_ARGS),),
            stop_reason="end_turn",
        ),
        LLMResponse(text="", stop_reason="tool_use"),
    ],
    ids=["end_turn_empty", "end_turn_blank", "end_turn_with_calls", "tool_use_without_calls"],
)
async def test_ac_007_42_handle_message__incoherent_or_empty__escalates(
    response: LLMResponse,
) -> None:
    """AC-007-42: una respuesta incoherente o vacía deriva sin ejecutar herramientas."""
    conv = _verified_conv()
    banking = _banking()
    use_case, _, audit = _build([response], banking, conv)

    result = await use_case.handle(conv.conversation_id, "Hola")

    assert "list_transactions" not in _names(banking)
    assert _names(banking) == ["escalate"]
    _assert_llm_failure(result, banking, audit, "RN-007-35")


def _llm_events(audit: FakeAgentAuditLog) -> list[AgentAuditEvent]:
    return [e for e in audit.events if e.event_type == "llm_response"]


# Regla: RN-007-28 — Cada evento genera un registro de auditoría en `AuditLogPort`, en JSON.
# Regla: RN-007-36 — Por cada respuesta del LLM queda un registro de auditoría de tipo respuesta
# del LLM (RN-007-28).
# AC-007-43 · Art. 8
async def test_ac_007_43_handle_message__each_llm_response__audited_without_text() -> None:
    """AC-007-43: 3 registros llm_response en orden, sin texto del asistente ni PAN/documento."""
    pan, document = "4111111111114321", "D-1001"
    text = f"Tu tarjeta {pan} y documento {document} están al día."
    conv = _verified_conv()
    conv.provided_documents.add(document)
    use_case, _, audit = _build(
        [
            tool_use_response(_call("c1", "consultar_transacciones", **_LIST_ARGS)),
            end_turn_response(text),
            LLMResponse(text="Texto cortado", stop_reason="max_tokens"),
        ],
        _banking(),
        conv,
    )

    await use_case.handle(conv.conversation_id, "Mis movimientos")
    await use_case.handle(conv.conversation_id, "Otra cosa")

    events = _llm_events(audit)
    assert [
        (
            e.conversation_id,
            e.at,
            e.tool,
            e.input,
            e.output,
            e.rule,
        )
        for e in events
    ] == [
        (
            conv.conversation_id,
            _NOW,
            None,
            {"call": 1},
            {
                "stop_reason": "tool_use",
                "decision": "CONTINUE",
                "tool_call_count": 1,
                "tool_calls": ["consultar_transacciones"],
            },
            "RN-007-32",
        ),
        (
            conv.conversation_id,
            _NOW,
            None,
            {"call": 2},
            {
                "stop_reason": "end_turn",
                "decision": "REPLY",
                "tool_call_count": 0,
                "tool_calls": [],
            },
            "RN-007-32",
        ),
        (
            conv.conversation_id,
            _NOW,
            None,
            {"call": 1},
            {
                "stop_reason": "max_tokens",
                "decision": "ESCALATE",
                "tool_call_count": 0,
                "tool_calls": [],
            },
            "RN-007-34",
        ),
    ]
    assert all(e.reason for e in events)
    assert all(
        "están al día" not in json.dumps(asdict(e), default=str)
        and "Texto cortado" not in json.dumps(asdict(e), default=str)
        for e in events
    )
    everything = json.dumps([asdict(e) for e in audit.events], default=str)
    assert pan not in everything
    assert document not in everything


# Regla: RN-007-36 — Al superar el tope de RN-007-23, el registro de esa llamada lleva la decisión
# `ESCALATE` y la regla `RN-007-23`.
# AC-007-43 · Art. 8
async def test_ac_007_43_handle_message__iteration_cap__8th_call_audited_as_escalate() -> None:
    """AC-007-43: la 8.ª llamada de la fila 8/8 de AC-007-38 se audita ESCALATE con RN-007-23."""
    conv = _verified_conv()
    script: list[LLMResponse | LLMError] = [
        tool_use_response(_call(f"c{n}", "consultar_transacciones", **_LIST_ARGS))
        for n in range(1, 9)
    ]
    use_case, _, audit = _build(script, _banking(), conv, max_iterations=8)

    await use_case.handle(conv.conversation_id, "Mis movimientos")

    events = _llm_events(audit)
    assert len(events) == 8
    assert events[-1].input == {"call": 8}
    assert events[-1].output is not None
    assert events[-1].output["decision"] == "ESCALATE"
    assert events[-1].rule == "RN-007-23"
    assert all(e.output is not None and e.output["decision"] == "CONTINUE" for e in events[:-1])
