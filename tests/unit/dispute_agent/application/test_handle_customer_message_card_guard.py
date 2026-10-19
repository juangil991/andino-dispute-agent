"""Tests de HandleCustomerMessage: guarda de tarjeta propia y tope compartido.

Spec 011: AC-011-03, AC-011-04, AC-011-05, AC-011-06, AC-011-08 (tres tarjetas ajenas), AC-011-09.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.banking_errors import invalid_input, not_found
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM, end_turn_response, tool_use_response
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolUnavailableError,
    EscalationRegistered,
    TransactionPage,
)
from dispute_agent.application.ports.llm import ToolCall, ToolResult
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import HandleCustomerMessage
from dispute_agent.domain import messages
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus, KnownCard
from dispute_agent.domain.models.decision import EscalationReason
from dispute_agent.domain.models.outcome import OutcomeKind
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_NOW = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 19)
_CARDS = (KnownCard("CARD-A", "4321"), KnownCard("CARD-B", "8765"))


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
        .transaction_id("TX-A1")
        .card("CARD-A", "**** 4321")
        .amount("85000.00", "COP")
        .days_ago(7, _TODAY)
        .national()
        .build()
    )


def _banking() -> FakeBankingTools:
    return (
        FakeBankingTools()
        .respond("list_transactions", TransactionPage((_tx(),), False))  # type: ignore[arg-type]
        .respond("escalate", EscalationRegistered("E-0001", "PENDING", _NOW, "OTHER"))
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


def _list(call_id: str, card: str, date_from: str = "2026-09-19") -> object:
    args = {"card_last4": card, "date_from": date_from, "date_to": "2026-10-19"}
    return tool_use_response(ToolCall(call_id, "consultar_transacciones", args))


def _seen(llm: FakeLLM, request_index: int) -> tuple[ToolResult, ...]:
    return llm.requests[request_index].messages[-1].tool_results


def _names(banking: FakeBankingTools, name: str) -> list[dict[str, object]]:
    return [args for call, args in banking.calls if call == name]


def _verified() -> Conversation:
    return ConversationBuilder().verified("C-0001", _CARDS).build()


# Regla: RN-011-03 — una tarjeta que no es de la clienta no llega al core; RN-011-08.
# AC-011-03
async def test_ac_011_03_handle__foreign_card__core_not_called_and_unknown_card_returned() -> None:
    """AC-011-03: tarjeta ajena => sin llamada al core y unknown_card con 1 corrección restante."""
    conv = _verified()
    banking = _banking()
    use_case, llm = _build(
        [_list("c1", "4231"), end_turn_response("Revisemos la tarjeta.")], banking, conv
    )

    result = await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    assert _names(banking, "list_transactions") == []
    first = _seen(llm, 1)[0]
    assert first.is_error
    assert json.loads(first.content) == {
        "error": "unknown_card",
        "cards_last4": ["4321", "8765"],
        "corrections_remaining": 1,
        "message": messages.unknown_card_message(("4321", "8765")),
    }
    assert conv.status is ConversationStatus.ACTIVE
    assert _names(banking, "escalate") == []
    kinds = {o.kind for o in result.outcomes}
    assert OutcomeKind.NO_TRANSACTIONS_FOUND not in kinds
    assert OutcomeKind.REFINEMENT_REQUIRED not in kinds


# Regla: RN-011-03 — tras la corrección, la consulta con una tarjeta propia se atiende normal.
# AC-011-04
async def test_ac_011_04_handle__llm_corrects_card__query_proceeds() -> None:
    """AC-011-04: 2.ª petición con tarjeta propia y 90 días llega al core y queda disponible."""
    conv = _verified()
    banking = _banking()
    use_case, llm = _build(
        [_list("c1", "4231"), _list("c2", "4321", "2026-07-22"), end_turn_response("Listo.")],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    second = json.loads(_seen(llm, 2)[0].content)
    assert [t["transaction_id"] for t in second["transactions"]] == ["TX-A1"]
    assert len(_names(banking, "list_transactions")) == 1
    assert "TX-A1" in conv.seen_transactions
    assert conv.status is ConversationStatus.ACTIVE
    assert result.status is ConversationStatus.ACTIVE
    assert _names(banking, "escalate") == []


# Regla: RN-011-03 — sin tarjetas conocidas la guarda no actúa.
# AC-011-05
async def test_ac_011_05_handle__no_known_cards__request_reaches_core() -> None:
    """AC-011-05: sin known_cards la petición llega al core y no se devuelve unknown_card."""
    conv = ConversationBuilder().verified("C-0001", ()).build()
    banking = _banking()
    use_case, llm = _build([_list("c1", "4231"), end_turn_response("Listo.")], banking, conv)

    await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    assert len(_names(banking, "list_transactions")) == 1
    assert "error" not in json.loads(_seen(llm, 1)[0].content)


# Regla: RN-011-03 — la guarda solo actúa con exactamente 4 dígitos; lo mal formado va al core.
# AC-011-05b
@pytest.mark.parametrize("malformed", ["11", "4111111111111111"])
async def test_ac_011_05b_handle__malformed_card_last4__reaches_core_and_invalid_input_applies(
    malformed: str,
) -> None:
    """AC-011-05b: card_last4 mal formado llega al core; el LLM recibe invalid_input."""
    conv = _verified()
    banking = FakeBankingTools().respond(
        "list_transactions",
        invalid_input("card_last4"),
        TransactionPage((_tx(),), False),  # type: ignore[arg-type]
    )
    use_case, llm = _build(
        [_list("c1", malformed), end_turn_response("Revisemos la tarjeta.")], banking, conv
    )

    await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    assert len(_names(banking, "list_transactions")) == 1
    first = _seen(llm, 1)[0]
    assert first.is_error
    assert json.loads(first.content)["error"] == "invalid_input"
    assert conv.status is ConversationStatus.ACTIVE


# Regla: RN-011-04 — texto fijo, sin el valor enviado ni datos ajenos.
# AC-011-06
async def test_ac_011_06_handle__unknown_card_text_is_fixed_and_hides_sent_value() -> None:
    """AC-011-06: el contenido es el texto fijo de §7.1 y no contiene los dígitos enviados."""
    conv = _verified()
    use_case, llm = _build([_list("c1", "9999"), end_turn_response("Revisemos.")], _banking(), conv)

    await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    content = _seen(llm, 1)[0].content
    assert json.loads(content)["message"] == (
        "Esa tarjeta no está entre las de la clienta (terminadas en 4321 y 8765). "
        "Usa una de ellas o pregúntale a la clienta cuál es; no repitas los mismos dígitos."
    )
    assert "9999" not in content


# Regla: RN-011-06 / RN-011-07 — el 3.er rechazo del mensaje deriva y cierra.
# AC-011-08
async def test_ac_011_08_handle__three_foreign_cards__escalates_with_rn_011_07() -> None:
    """AC-011-08: 2 rechazos vuelven al LLM; el 3.º deriva con la nota RN-011-07 y cierra."""
    conv = _verified()
    banking = _banking()
    use_case, llm = _build(
        [
            _list("c1", "4231"),
            _list("c2", "4232"),
            _list("c3", "4233"),
            end_turn_response("Derivamos tu caso."),
        ],
        banking,
        conv,
    )

    result = await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    first = json.loads(_seen(llm, 1)[0].content)
    second = json.loads(_seen(llm, 2)[0].content)
    assert (first["error"], first["corrections_remaining"]) == ("unknown_card", 1)
    assert (second["error"], second["corrections_remaining"]) == ("unknown_card", 0)
    assert json.loads(_seen(llm, 3)[0].content)["error"] == "system_unavailable"
    assert _names(banking, "list_transactions") == []
    escalations = _names(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.INSUFFICIENT_OR_CONTRADICTORY_INFO
    assert escalations[0]["note"] == (
        "RN-011-07: consultar_transacciones UNKNOWN_CARD tras 2 correcciones"
    )
    assert escalations[0]["transaction_id"] is None
    assert escalations[0]["card_id"] is None
    assert escalations[0]["prior_actions"] == ()
    assert escalations[0]["dispute_id"] is None
    assert [o.kind for o in result.outcomes] == [OutcomeKind.ESCALATED]
    assert result.outcomes[0].transaction_id is None
    assert conv.status is ConversationStatus.ESCALATED
    assert result.status is ConversationStatus.ESCALATED


# Regla: RN-011-05 — NOT_FOUND de consultar_transacciones es un error de negocio corregible.
# AC-011-07
async def test_ac_011_07_handle__not_found_from_core__returned_to_llm_without_escalation() -> None:
    """AC-011-07: NOT_FOUND del core vuelve al LLM como not_found, sin derivar ni outcomes."""
    conv = _verified()
    banking = _banking().respond("list_transactions", not_found())
    use_case, llm = _build([_list("c1", "4321"), end_turn_response("Revisemos.")], banking, conv)

    result = await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    first = _seen(llm, 1)[0]
    assert first.is_error
    assert json.loads(first.content) == {
        "error": "not_found",
        "corrections_remaining": 1,
        "message": messages.NOT_FOUND_CARD_MESSAGE,
    }
    assert _names(banking, "escalate") == []
    assert result.outcomes == ()
    assert conv.status is ConversationStatus.ACTIVE
    assert result.status is ConversationStatus.ACTIVE


# Regla: RN-011-06 / RN-011-07 — NOT_FOUND comparte el tope; la nota nombra el 3.er rechazo.
# AC-011-08
@pytest.mark.parametrize(
    ("core_errors", "script_cards", "kind"),
    [
        ([not_found(), not_found(), not_found()], ["4321", "4321", "4321"], "NOT_FOUND"),
        ([invalid_input("card_last4"), not_found()], ["4321", "4231", "4321"], "NOT_FOUND"),
    ],
    ids=["three_not_found", "mixed"],
)
async def test_ac_011_08_handle__three_not_found_or_mixed__escalates_with_rn_011_07(
    core_errors: list[object], script_cards: list[str], kind: str
) -> None:
    """AC-011-08: el 3.er rechazo (NOT_FOUND) deriva con la nota RN-011-07 y cierra."""
    conv = _verified()
    banking = _banking().respond("list_transactions", *core_errors)
    script: list[object] = [_list(f"c{i}", card) for i, card in enumerate(script_cards, 1)]
    script.append(end_turn_response("Derivamos tu caso."))
    use_case, llm = _build(script, banking, conv)

    result = await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    first = json.loads(_seen(llm, 1)[0].content)
    second = json.loads(_seen(llm, 2)[0].content)
    third = json.loads(_seen(llm, 3)[0].content)
    assert first["corrections_remaining"] == 1
    assert second["corrections_remaining"] == 0
    if kind == "NOT_FOUND" and script_cards[1] == "4231":
        assert (first["error"], second["error"]) == ("invalid_input", "unknown_card")
    assert third["error"] == "system_unavailable"
    escalations = _names(banking, "escalate")
    assert len(escalations) == 1
    assert escalations[0]["reason"] is EscalationReason.INSUFFICIENT_OR_CONTRADICTORY_INFO
    assert (
        escalations[0]["note"] == f"RN-011-07: consultar_transacciones {kind} tras 2 correcciones"
    )
    assert escalations[0]["transaction_id"] is None
    assert escalations[0]["card_id"] is None
    assert escalations[0]["dispute_id"] is None
    assert [o.kind for o in result.outcomes] == [OutcomeKind.ESCALATED]
    assert result.outcomes[0].transaction_id is None
    assert conv.status is ConversationStatus.ESCALATED
    assert result.status is ConversationStatus.ESCALATED


# Regla: RN-011-10 — el desvío no se amplía: otros fallos derivan; INVALID_INPUT sigue corrigiendo.
# AC-011-11
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (BankingToolError("INTERNAL", "fallo interno", False), "system_unavailable"),
        (BankingToolUnavailableError("tiempo límite"), "system_unavailable"),
        (
            BankingToolUnavailableError("respuesta fuera de esquema de consultar_transacciones"),
            "system_unavailable",
        ),
        (invalid_input("date_from"), "invalid_input"),
    ],
    ids=["internal", "timeout", "schema_violation", "invalid_input"],
)
async def test_ac_011_11_handle__other_failures_still_escalate_and_invalid_input_still_corrects(
    failure: Exception, expected: str
) -> None:
    """AC-011-11: INTERNAL, tiempo límite y fuera de esquema derivan; INVALID_INPUT corrige."""
    conv = _verified()
    banking = _banking().respond("list_transactions", failure)
    use_case, llm = _build([_list("c1", "4321"), end_turn_response("Listo.")], banking, conv)

    result = await use_case.handle(conv.conversation_id, "Quiero disputar un cobro")

    assert json.loads(_seen(llm, 1)[0].content)["error"] == expected
    if expected == "system_unavailable":
        escalations = _names(banking, "escalate")
        assert len(escalations) == 1
        assert escalations[0]["reason"] is EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE
        assert result.status is ConversationStatus.ESCALATED
        assert conv.status is ConversationStatus.ESCALATED
    else:
        assert _names(banking, "escalate") == []
        assert result.status is ConversationStatus.ACTIVE


# Regla: RN-011-06 — el contador vuelve a 0 con cada mensaje nuevo.
# AC-011-09
async def test_ac_011_09_handle__new_message_resets_correction_counter() -> None:
    """AC-011-09: tras 2 rechazos, un mensaje nuevo con tarjeta ajena es la 1.ª corrección."""
    conv = _verified()
    # 1.er rechazo: tarjeta ajena (unknown_card); 2.º: tarjeta propia con not_found.
    banking = _banking().respond("list_transactions", not_found())
    use_case, llm = _build(
        [
            _list("d1", "4231"),
            _list("d2", "4321"),
            end_turn_response("Revisemos."),
            _list("d3", "4233"),
            end_turn_response("Revisemos otra vez."),
        ],
        banking,
        conv,
    )

    await use_case.handle(conv.conversation_id, "primer mensaje")
    result = await use_case.handle(conv.conversation_id, "segundo mensaje")

    first = json.loads(_seen(llm, 1)[0].content)
    second = json.loads(_seen(llm, 2)[0].content)
    assert (first["error"], first["corrections_remaining"]) == ("unknown_card", 1)
    assert (second["error"], second["corrections_remaining"]) == ("not_found", 0)
    reset = json.loads(_seen(llm, 4)[0].content)
    assert (reset["error"], reset["corrections_remaining"]) == ("unknown_card", 1)
    assert _names(banking, "escalate") == []
    assert result.status is ConversationStatus.ACTIVE
