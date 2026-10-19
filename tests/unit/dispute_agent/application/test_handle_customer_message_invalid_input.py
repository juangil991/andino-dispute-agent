"""Tests de HandleCustomerMessage ante INVALID_INPUT corregible de consultar_transacciones.

Spec 010: AC-010-01, AC-010-02, AC-010-03, AC-010-07, AC-010-08.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.banking_errors import invalid_input
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM, end_turn_response, tool_use_response
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    CardRef,
    CustomerMatch,
    CustomerSearch,
    EscalationRegistered,
    TransactionPage,
)
from dispute_agent.application.ports.llm import ToolCall, ToolResult
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import HandleCustomerMessage
from dispute_agent.domain import messages
from dispute_agent.domain.identification import IdentificationReply
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus, KnownCard
from dispute_agent.domain.models.decision import EscalationReason
from dispute_agent.domain.models.outcome import OutcomeKind
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 19)
_CARD = KnownCard("CARD-L1", "1111")
_VALID_ARGS: dict[str, object] = {
    "card_last4": "1111",
    "date_from": "2026-09-19",
    "date_to": "2026-10-19",
}


class _Repo:
    """Repositorio de conversaciones en memoria, local al test."""

    def __init__(self, *conversations: Conversation) -> None:
        self.items = {c.conversation_id: c for c in conversations}

    def get(self, conversation_id: str) -> Conversation | None:
        return self.items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self.items[conversation.conversation_id] = conversation


def _tx() -> object:
    return (
        DisputedTransactionBuilder()
        .transaction_id("TX-L1")
        .card("CARD-L1", "**** 1111")
        .amount("85000.00", "COP")
        .days_ago(7, _TODAY)
        .national()
        .build()
    )


def _build(
    script: list[object], banking: FakeBankingTools, conv: Conversation
) -> tuple[HandleCustomerMessage, FakeLLM]:
    audit = FakeAgentAuditLog()
    clock = FixedAgentClock(_NOW)
    escalation = EscalationService(banking, audit, clock)
    dispute_actions = DisputeActions(
        DisputePolicy(Decimal(4000)), banking, escalation, audit, clock
    )
    fraud_actions = FraudActions(banking, dispute_actions, escalation, audit, clock)
    llm = FakeLLM(script)  # type: ignore[arg-type]
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
        8,
    )
    return use_case, llm


def _banking(*outcomes: object) -> FakeBankingTools:
    return (
        FakeBankingTools()
        .respond("list_transactions", *outcomes)
        .respond("escalate", EscalationRegistered("E-0001", "PENDING", _NOW, "OTHER"))
    )


def _results_seen(llm: FakeLLM, request_index: int) -> tuple[ToolResult, ...]:
    return llm.requests[request_index].messages[-1].tool_results


# Regla: RN-010-01 — `INVALID_INPUT` de `consultar_transacciones` no es falla del sistema: se
# devuelve al LLM un error `invalid_input` con el campo, sin derivar ni cerrar. RN-010-05.
# AC-010-01
@pytest.mark.parametrize(
    ("arguments", "field"),
    [
        ({**_VALID_ARGS, "date_to": "2026-10-20"}, "date_to"),
        ({**_VALID_ARGS, "date_from": "2026-06-01"}, "date_range"),
        ({**_VALID_ARGS, "date_from": "2026-10-19", "date_to": "2026-10-01"}, "date_range"),
        ({**_VALID_ARGS, "card_last4": "11"}, "card_last4"),
    ],
    ids=["future_date_to", "range_over_90_days", "from_after_to", "short_card"],
)
async def test_ac_010_01_handle_message__list_transactions_invalid_input__llm_corrects_and_continues(  # noqa: E501
    arguments: dict[str, object], field: str
) -> None:
    """AC-010-01: el LLM recibe invalid_input, corrige y la 2.ª consulta se atiende normal."""
    conv = ConversationBuilder().verified("C-0001", (_CARD,)).build()
    banking = _banking(invalid_input(field), TransactionPage((_tx(),), False))  # type: ignore[arg-type]
    use_case, llm = _build(
        [
            tool_use_response(ToolCall("c1", "consultar_transacciones", arguments)),
            tool_use_response(ToolCall("c2", "consultar_transacciones", dict(_VALID_ARGS))),
            end_turn_response("Encontré tu cobro."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    first = _results_seen(llm, 1)[0]
    assert first.is_error
    assert json.loads(first.content) == {
        "error": "invalid_input",
        "field": field,
        "corrections_remaining": 1,
        "message": messages.invalid_input_message("consultar_transacciones", field),
    }
    second = json.loads(_results_seen(llm, 2)[0].content)
    assert [t["transaction_id"] for t in second["transactions"]] == ["TX-L1"]
    assert "TX-L1" in conv.seen_transactions
    assert conv.status is ConversationStatus.ACTIVE
    assert result.status is ConversationStatus.ACTIVE
    assert result.outcomes == ()
    assert "escalate" not in [name for name, _ in banking.calls]


# Regla: RN-010-02 — El LLM recibe un texto fijo: sin el texto del servidor, el documento ni
# valores enviados.
# AC-010-03
async def test_ac_010_03_handle_message__invalid_input__llm_gets_fixed_text_without_values() -> (
    None
):
    """AC-010-03: el contenido es el texto fijo de §7.2, sin documento ni valores."""
    conv = ConversationBuilder().verified("C-0001", (_CARD,)).build()
    conv.provided_documents.add("1020304050")
    server_text = "Documento 1020304050 inválido en date_to=2026-10-20"
    banking = _banking(invalid_input("date_to", server_text))
    use_case, llm = _build(
        [
            tool_use_response(
                ToolCall(
                    "c1",
                    "consultar_transacciones",
                    {**_VALID_ARGS, "date_to": "2026-10-20"},
                )
            ),
            end_turn_response("Revisemos las fechas."),
        ],
        banking,
        conv,
    )

    await use_case.handle(conv.conversation_id, "Mi documento es 1020304050")

    content = _results_seen(llm, 1)[0].content
    assert json.loads(content)["message"] == (
        "Los datos enviados a consultar_transacciones no son válidos (campo: date_to). "
        "Corrígelos y vuelve a llamar a la herramienta; si no puedes formarlos con lo que "
        "dijo la cliente, pídeselos."
    )
    for forbidden in ("1020304050", server_text, "2026-10-20", "2026-09-19", "1111"):
        assert forbidden not in content


# Regla: RN-010-05 — Un `INVALID_INPUT` no da nada por hecho: no registra transacciones como
# vistas ni genera `outcomes` de lista vacía.
# AC-010-07
async def test_ac_010_07_handle_message__list_invalid_input__nothing_is_assumed() -> None:
    """AC-010-07: tras el rechazo, evaluar_disputa responde transaction_not_listed."""
    conv = ConversationBuilder().verified("C-0001", (_CARD,)).build()
    banking = _banking(invalid_input("date_to"))
    use_case, llm = _build(
        [
            tool_use_response(
                ToolCall(
                    "c1",
                    "consultar_transacciones",
                    {**_VALID_ARGS, "date_to": "2026-10-20"},
                )
            ),
            tool_use_response(ToolCall("c2", "evaluar_disputa", {"transaction_id": "TX-L1"})),
            end_turn_response("No pude consultar."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    evaluated = json.loads(_results_seen(llm, 2)[0].content)
    assert evaluated["result"] == "transaction_not_listed"
    assert "outcomes" not in evaluated
    assert conv.seen_transactions == {}
    kinds = {o.kind for o in result.outcomes}
    assert OutcomeKind.NO_TRANSACTIONS_FOUND not in kinds
    assert OutcomeKind.REFINEMENT_REQUIRED not in kinds
    assert conv.status is ConversationStatus.ACTIVE


# Regla: RN-010-05 — un rechazo no da nada por hecho: la cliente sigue sin localizar ni verificar.
# AC-010-07 · Art. 7 (identificación antes que información)
async def test_ac_010_07_handle_message__search_invalid_input_then_evaluate__customer_stays_unlocated() -> (  # noqa: E501
    None
):
    """AC-010-07 (fila 2): buscar_cliente rechazada y luego evaluar_disputa ⇒ sin localizar."""
    conv = ConversationBuilder().build()
    banking = _search_banking(invalid_input("document"))
    use_case, _ = _build(
        [
            tool_use_response(ToolCall("c1", "buscar_cliente", {"document": "!!"})),
            tool_use_response(ToolCall("c2", "evaluar_disputa", {"transaction_id": "TX-L1"})),
            end_turn_response("Texto libre del LLM."),
        ],
        banking,
        conv,
    )

    await use_case.handle(conv.conversation_id, "mi documento es !!")

    assert conv.located_customer_id is None
    assert conv.verified_customer_id is None


# Regla: RN-010-05 — dos rechazos y una búsqueda sin coincidencias suman un solo fallo (RN-007-05).
# AC-010-07 · Art. 10 (no escalar lo que el agente puede resolver)
async def test_ac_010_07_handle_message__two_invalid_inputs_then_no_match__stays_active() -> None:
    """AC-010-07 (fila 3): 2 rechazadas + 1 sin coincidencias ⇒ failed_searches 1 y ACTIVE."""
    conv = ConversationBuilder().build()
    banking = _search_banking(invalid_input("document"), invalid_input("document"), _NO_MATCH)
    use_case, _ = _build(
        [
            tool_use_response(ToolCall("c1", "buscar_cliente", {"document": "!!"})),
            tool_use_response(ToolCall("c2", "buscar_cliente", {"document": "??"})),
            tool_use_response(ToolCall("c3", "buscar_cliente", {"document": "D-9999"})),
            end_turn_response("No te encontré."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "mi documento es !!")

    assert conv.failed_searches == 1
    assert conv.status is ConversationStatus.ACTIVE
    assert result.status is ConversationStatus.ACTIVE
    assert "escalate" not in [name for name, _ in banking.calls]


def _search_banking(*outcomes: object) -> FakeBankingTools:
    return (
        FakeBankingTools()
        .respond("search_customer", *outcomes)
        .respond("escalate", EscalationRegistered("E-0001", "PENDING", _NOW, "OTHER"))
    )


_ONE_MATCH = CustomerSearch((CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 1111"),)),), False)
_NO_MATCH = CustomerSearch((), False)


# Regla: RN-010-01 — `INVALID_INPUT` de `buscar_cliente` vuelve al LLM para corregir, sin derivar.
# AC-010-02
async def test_ac_010_02_handle_message__search_invalid_input__llm_corrects_and_locates() -> None:
    """AC-010-02: el LLM recibe invalid_input con el campo y la 2.ª búsqueda localiza."""
    conv = ConversationBuilder().build()
    banking = _search_banking(invalid_input("card_last4"), _ONE_MATCH)
    use_case, llm = _build(
        [
            tool_use_response(ToolCall("c1", "buscar_cliente", {"card_last4": "11"})),
            tool_use_response(ToolCall("c2", "buscar_cliente", {"card_last4": "1111"})),
            end_turn_response("Gracias."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "mi tarjeta termina en 11")

    first = _results_seen(llm, 1)[0]
    assert first.is_error
    assert json.loads(first.content) == {
        "error": "invalid_input",
        "field": "card_last4",
        "corrections_remaining": 1,
        "message": messages.invalid_input_message("buscar_cliente", "card_last4"),
    }
    assert json.loads(_results_seen(llm, 2)[0].content)["matches"] == 1
    assert conv.located_customer_id == "C-0001"
    assert conv.status is ConversationStatus.ACTIVE
    assert result.status is ConversationStatus.ACTIVE
    assert "escalate" not in [name for name, _ in banking.calls]


# Regla: RN-010-05 — un rechazo no es una búsqueda sin coincidencias: no suma a failed_searches.
# AC-010-07
async def test_ac_010_07_handle_message__search_invalid_input__does_not_count_as_failed_search() -> (  # noqa: E501
    None
):
    """AC-010-07: rechazada + búsqueda sin coincidencias ⇒ 1 fallo y sigue ACTIVE."""
    conv = ConversationBuilder().build()
    banking = _search_banking(invalid_input("document"), _NO_MATCH)
    use_case, _ = _build(
        [
            tool_use_response(ToolCall("c1", "buscar_cliente", {"document": "!!"})),
            tool_use_response(ToolCall("c2", "buscar_cliente", {"document": "D-9999"})),
            end_turn_response("No te encontré."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "mi documento es !!")

    assert conv.failed_searches == 1
    assert conv.status is ConversationStatus.ACTIVE
    assert result.status is ConversationStatus.ACTIVE
    assert "escalate" not in [name for name, _ in banking.calls]


# Regla: RN-010-06 — sin verificar al terminar el turno, el reply es el texto fijo INVALID_SEARCH.
# AC-010-08
async def test_ac_010_08_handle_message__unverified_after_search_invalid_input__fixed_invalid_search_reply() -> (  # noqa: E501
    None
):
    """AC-010-08: el reply es el texto fijo INVALID_SEARCH, no el texto del LLM."""
    conv = ConversationBuilder().build()
    banking = _search_banking(invalid_input("document"))
    use_case, llm = _build(
        [
            tool_use_response(ToolCall("c1", "buscar_cliente", {"document": "!!"})),
            end_turn_response("Texto libre del LLM que no debe salir."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "mi documento es !!")

    assert result.reply == messages.IDENTIFICATION_REPLIES[IdentificationReply.INVALID_SEARCH]
    assert result.status is ConversationStatus.ACTIVE
    assert len(llm.requests) == 2
    assert conv.failed_searches == 0
    assert conv.turn_attempts_remaining is None


def _escalations(banking: FakeBankingTools) -> list[dict[str, object]]:
    return [args for name, args in banking.calls if name == "escalate"]


def _list_call(call_id: str) -> object:
    bad = {**_VALID_ARGS, "date_to": "2026-10-20"}
    return tool_use_response(ToolCall(call_id, "consultar_transacciones", dict(bad)))


# Regla: RN-010-03 / RN-010-04 — el 3.er INVALID_INPUT del mensaje no se corrige: deriva con
# INSUFFICIENT_OR_CONTRADICTORY_INFO, resumen completo sin transacción y cierra.
# AC-010-04
async def test_ac_010_04_handle_message__third_invalid_input_in_list__escalates_insufficient_info() -> (  # noqa: E501
    None
):
    """AC-010-04: 2 rechazos vuelven al LLM; el 3.º deriva, cierra y no se devuelve a corregir."""
    conv = ConversationBuilder().verified("C-0001", (_CARD,)).build()
    banking = _banking(*[invalid_input("date_to")] * 3)
    use_case, llm = _build(
        [
            _list_call("c1"),
            _list_call("c2"),
            _list_call("c3"),
            end_turn_response("Derivamos tu caso."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    first = json.loads(_results_seen(llm, 1)[0].content)
    second = json.loads(_results_seen(llm, 2)[0].content)
    assert (first["error"], first["corrections_remaining"]) == ("invalid_input", 1)
    assert (second["error"], second["corrections_remaining"]) == ("invalid_input", 0)
    third = json.loads(_results_seen(llm, 3)[0].content)
    assert third["error"] == "system_unavailable"
    escalations = _escalations(banking)
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.INSUFFICIENT_OR_CONTRADICTORY_INFO
    assert escalations[0]["note"] == (
        "RN-010-04: consultar_transacciones INVALID_INPUT (campo: date_to) tras 2 correcciones"
    )
    assert escalations[0]["transaction_id"] is None
    assert escalations[0]["card_id"] is None
    assert escalations[0]["prior_actions"] == ()
    assert escalations[0]["dispute_id"] is None
    assert [o.kind for o in result.outcomes] == [OutcomeKind.ESCALATED]
    assert result.outcomes[0].rule == "RN-010-04"
    assert result.outcomes[0].transaction_id is None
    assert conv.status is ConversationStatus.ESCALATED
    assert result.status is ConversationStatus.ESCALATED


# Regla: RN-010-04 — sin verificar, resumen limitado y reply fijo de cierre ESCALATED.
# AC-010-05
async def test_ac_010_05_handle_message__third_invalid_input_in_search_unverified__limited_summary_and_closed_reply() -> (  # noqa: E501
    None
):
    """AC-010-05: 3.er rechazo de buscar_cliente sin verificar deriva con resumen limitado."""
    conv = ConversationBuilder().build()
    banking = _search_banking(*[invalid_input("document")] * 3)
    call = ToolCall("c", "buscar_cliente", {"document": "!!"})
    use_case, _ = _build(
        [
            tool_use_response(call),
            tool_use_response(call),
            tool_use_response(call),
            end_turn_response("Texto libre del LLM."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "mi documento es !!")

    escalations = _escalations(banking)
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.INSUFFICIENT_OR_CONTRADICTORY_INFO
    assert escalations[0]["note"] == (
        "RN-010-04: buscar_cliente INVALID_INPUT (campo: document) tras 2 correcciones"
    )
    assert escalations[0]["transaction_id"] is None
    assert escalations[0]["card_id"] is None
    assert escalations[0]["prior_actions"] == ()
    assert escalations[0]["dispute_id"] is None
    assert result.reply == messages.IDENTIFICATION_REPLIES[IdentificationReply.CLOSED_ESCALATED]
    assert result.status is ConversationStatus.ESCALATED
    assert conv.status is ConversationStatus.ESCALATED


# Regla: RN-010-03 — el tope es combinado entre herramientas y se reinicia con cada mensaje.
# AC-010-06
async def test_ac_010_06_handle_message__shared_cap_and_reset_per_message__third_escalates_new_message_resets() -> (  # noqa: E501
    None
):
    """AC-010-06: 1 rechazo en cada herramienta + 1 más deriva; un mensaje nuevo reinicia."""
    conv = ConversationBuilder().verified("C-0001", (_CARD,)).build()
    banking = (
        FakeBankingTools()
        .respond("search_customer", invalid_input("card_last4"))
        .respond("list_transactions", invalid_input("date_to"), invalid_input("date_to"))
        .respond("escalate", EscalationRegistered("E-0001", "PENDING", _NOW, "OTHER"))
    )
    use_case, _ = _build(
        [
            tool_use_response(ToolCall("c1", "buscar_cliente", {"card_last4": "11"})),
            _list_call("c2"),
            _list_call("c3"),
            end_turn_response("Derivamos tu caso."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    escalations = _escalations(banking)
    assert len(escalations) == 1
    assert escalations[0]["note"] == (
        "RN-010-04: consultar_transacciones INVALID_INPUT (campo: date_to) tras 2 correcciones"
    )
    assert result.status is ConversationStatus.ESCALATED

    # Reinicio: dos rechazos en un mensaje, y el siguiente mensaje empieza de cero.
    conv2 = ConversationBuilder().verified("C-0001", (_CARD,)).build()
    banking2 = _banking(*[invalid_input("date_to")] * 3)
    use_case2, llm2 = _build(
        [
            _list_call("d1"),
            _list_call("d2"),
            end_turn_response("Revisemos."),
            _list_call("d3"),
            end_turn_response("Revisemos otra vez."),
        ],
        banking2,
        conv2,
    )
    await use_case2.handle(conv2.conversation_id, "primer mensaje")
    result2 = await use_case2.handle(conv2.conversation_id, "segundo mensaje")

    reset = json.loads(_results_seen(llm2, 4)[0].content)
    assert (reset["error"], reset["corrections_remaining"]) == ("invalid_input", 1)
    assert _escalations(banking2) == []
    assert result2.status is ConversationStatus.ACTIVE


def _verified_with_tx() -> Conversation:
    conv = ConversationBuilder().verified("C-0001", (_CARD,)).build()
    conv.remember_transactions([_tx()])  # type: ignore[list-item]
    return conv


def _located() -> Conversation:
    return ConversationBuilder().located("C-0001", (_CARD,)).build()


_INTERNAL = BankingToolError("INTERNAL", "detalle interno", False)


# Regla: RN-010-09 — INVALID_INPUT de iniciar_disputa y bloquear_tarjeta deriva con
# UNRECOVERABLE_SYSTEM_FAILURE (RN-007-21); INTERNAL de consultar_transacciones también deriva;
# verificar_identidad con INVALID_INPUT sigue RN-007-40 (pide las fechas). No consumen tope.
# AC-010-11 · Art. 10 (ante la duda, escalar)
@pytest.mark.parametrize(
    ("conv_factory", "call", "core_tool", "error", "derives"),
    [
        (
            _verified_with_tx,
            ToolCall("c1", "evaluar_disputa", {"transaction_id": "TX-L1"}),
            "open_dispute",
            invalid_input("transaction_id"),
            True,
        ),
        (
            _verified_with_tx,
            ToolCall("c1", "reportar_fraude", {"card_last4": "1111"}),
            "block_card",
            invalid_input("card_id"),
            True,
        ),
        (
            lambda: ConversationBuilder().verified("C-0001", (_CARD,)).build(),
            ToolCall("c1", "consultar_transacciones", dict(_VALID_ARGS)),
            "list_transactions",
            _INTERNAL,
            True,
        ),
        (
            _located,
            ToolCall(
                "c1",
                "verificar_identidad",
                {"birth_date": "1990-03-15", "document_issue_date": "2008-04-20"},
            ),
            "verify_identity",
            invalid_input("birth_date"),
            False,
        ),
    ],
    ids=[
        "iniciar_disputa_invalid_input",
        "bloquear_tarjeta_invalid_input",
        "consultar_transacciones_internal",
        "verificar_identidad_invalid_input",
    ],
)
async def test_ac_010_11_handle_message__unchanged_failures__still_escalate_or_ask_dates(
    conv_factory: object,
    call: ToolCall,
    core_tool: str,
    error: BankingToolError,
    derives: bool,
) -> None:
    """AC-010-11: solo las lecturas con INVALID_INPUT se corrigen; lo demás sigue como antes."""
    conv = conv_factory()  # type: ignore[operator]
    banking = _banking().respond(core_tool, error)
    use_case, _ = _build(
        [tool_use_response(call), end_turn_response("Texto libre del LLM.")], banking, conv
    )

    result = await use_case.handle(conv.conversation_id, "mensaje de la cliente")

    escalations = _escalations(banking)
    assert conv.turn_invalid_inputs == 0
    if derives:
        assert len(escalations) == 1
        assert escalations[0]["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
        assert result.status is ConversationStatus.ESCALATED
        assert conv.status is ConversationStatus.ESCALATED
    else:
        assert escalations == []
        assert result.reply == messages.IDENTIFICATION_REPLIES[IdentificationReply.INVALID_DATES]
        assert result.status is ConversationStatus.ACTIVE
