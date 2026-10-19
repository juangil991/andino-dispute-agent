"""Soporte de tests: textos fijos y selector de RN-007-38 · Art. 7 (spec §7.4, §4.8)."""

import pytest

from dispute_agent.domain.identification import (
    IdentificationReply,
    IdentificationStep,
    select_identification_reply,
)
from dispute_agent.domain.messages import IDENTIFICATION_REPLIES
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus
from dispute_agent.domain.models.outcome import OutcomeKind

_ASK_DATES_TAIL = "indícame tu fecha de nacimiento y la fecha de expedición de tu documento."

_LITERALS: dict[IdentificationReply, str] = {
    IdentificationReply.REMINDER_LOCATE: (
        "Antes de ayudarte necesito identificarte. Indícame tu número de documento, "
        "tu nombre completo o los últimos 4 dígitos de tu tarjeta."
    ),
    IdentificationReply.REMINDER_VERIFY: (
        "Antes de ayudarte necesito confirmar tu identidad. Indícame tu fecha de "
        "nacimiento y la fecha de expedición de tu documento."
    ),
    IdentificationReply.ASK_DATES: (
        "Gracias. Para confirmar tu identidad, indícame tu fecha de nacimiento y la "
        "fecha de expedición de tu documento."
    ),
    IdentificationReply.ASK_MORE_DATA: (
        "Necesito un dato adicional para identificarte. Indícame tu número de "
        "documento o los últimos 4 dígitos de tu tarjeta."
    ),
    IdentificationReply.NOT_FOUND: (
        "No pudimos identificarte con esos datos. Revísalos e intenta con otro dato: "
        "tu número de documento, tu nombre completo o los últimos 4 dígitos de tu "
        "tarjeta."
    ),
    IdentificationReply.WRONG_DATES_2: (
        "Los datos no coinciden con los registrados. Te quedan 2 intentos. Indícame "
        "de nuevo tu fecha de nacimiento y la fecha de expedición de tu documento."
    ),
    IdentificationReply.WRONG_DATES_1: (
        "Los datos no coinciden con los registrados. Te queda 1 intento. Indícame "
        "de nuevo tu fecha de nacimiento y la fecha de expedición de tu documento."
    ),
    IdentificationReply.INVALID_DATES: (
        "Las fechas no son válidas. Indícame tu fecha de nacimiento y la fecha de "
        "expedición de tu documento con el formato AAAA-MM-DD."
    ),
    IdentificationReply.INVALID_SEARCH: (
        "Esos datos no son válidos. Revísalos e indícame tu número de documento, "
        "tu nombre completo o los últimos 4 dígitos de tu tarjeta."
    ),
    IdentificationReply.CLOSED_ESCALATED: (
        "Tu caso requiere la revisión de una persona. Una persona continuará la atención."
    ),
    IdentificationReply.CLOSED_ESCALATION_FAILED: (
        "No pudimos derivar tu caso a un analista en este momento. "
        "Por favor, vuelve a contactar al banco más tarde."
    ),
}


def _conv(
    *,
    located: str | None = None,
    escalated: bool = False,
    step: IdentificationStep | None = None,
    remaining: int | None = None,
) -> Conversation:
    conv = Conversation(conversation_id="conv-1", located_customer_id=located)
    if escalated:
        conv.status = ConversationStatus.ESCALATED
    if step is not None:
        conv.record_identification(step, remaining)
    return conv


@pytest.mark.parametrize(
    ("conv", "outcome", "expected"),
    [
        pytest.param(
            _conv(escalated=True), None, IdentificationReply.CLOSED_ESCALATED, id="closed"
        ),
        pytest.param(
            _conv(escalated=True),
            OutcomeKind.ESCALATION_FAILED,
            IdentificationReply.CLOSED_ESCALATION_FAILED,
            id="closed-escalation-failed",
        ),
        pytest.param(
            _conv(escalated=True, step=IdentificationStep.NOT_FOUND),
            OutcomeKind.ESCALATED,
            IdentificationReply.CLOSED_ESCALATED,
            id="closed-wins-over-trace",
        ),
        pytest.param(
            _conv(step=IdentificationStep.LOCATED),
            None,
            IdentificationReply.ASK_DATES,
            id="trace-located",
        ),
        pytest.param(
            _conv(step=IdentificationStep.MORE_DATA_NEEDED),
            None,
            IdentificationReply.ASK_MORE_DATA,
            id="trace-more-data",
        ),
        pytest.param(
            _conv(step=IdentificationStep.NOT_FOUND),
            None,
            IdentificationReply.NOT_FOUND,
            id="trace-not-found",
        ),
        pytest.param(
            _conv(step=IdentificationStep.WRONG_DATES, remaining=2),
            None,
            IdentificationReply.WRONG_DATES_2,
            id="trace-wrong-dates-2",
        ),
        pytest.param(
            _conv(step=IdentificationStep.WRONG_DATES, remaining=1),
            None,
            IdentificationReply.WRONG_DATES_1,
            id="trace-wrong-dates-1",
        ),
        pytest.param(
            _conv(step=IdentificationStep.INVALID_DATES),
            None,
            IdentificationReply.INVALID_DATES,
            id="trace-invalid-dates",
        ),
        pytest.param(_conv(located="C-X"), None, IdentificationReply.REMINDER_VERIFY, id="located"),
        pytest.param(_conv(), None, IdentificationReply.REMINDER_LOCATE, id="not-located"),
    ],
)
def test_select_identification_reply__order_of_rn_007_38(
    conv: Conversation, outcome: OutcomeKind | None, expected: IdentificationReply
) -> None:
    """RN-007-38: cierre, luego rastro del turno, luego recordatorio (AC-007-44 a 49)."""
    assert select_identification_reply(conv, outcome) is expected


@pytest.mark.parametrize("reply", list(IdentificationReply), ids=lambda r: r.name)
def test_identification_replies__match_spec_literal_and_leak_nothing(
    reply: IdentificationReply,
) -> None:
    """Spec §7.4: texto literal, sin decir cuál fecha falló ni datos de las semillas."""
    text = IDENTIFICATION_REPLIES[reply]
    assert text == _LITERALS[reply]
    lowered = text.lower()
    assert "cuál" not in lowered
    for seed in ("C-0001", "Laura Méndez", "D-1001", "****"):
        assert seed not in text


def test_identification_replies__cover_every_reply() -> None:
    """Spec §7.4: hay exactamente 11 textos fijos (10 de la spec 007 + INVALID_SEARCH)."""
    assert set(IDENTIFICATION_REPLIES) == set(IdentificationReply)
    assert len(IdentificationReply) == 11


# Regla: RN-010-06 — INVALID_INPUT de buscar_cliente sin verificar responde con texto fijo.
# AC-010-08 · Art. 7 (sin identificación no hay datos)
def test_ac_010_08_select_identification_reply__invalid_search_step__returns_fixed_text() -> None:
    """AC-010-08: INVALID_INPUT de buscar_cliente sin verificar da el texto INVALID_SEARCH."""
    conv = _conv(step=IdentificationStep.INVALID_SEARCH)
    reply = select_identification_reply(conv, None)
    assert reply is IdentificationReply.INVALID_SEARCH
    assert IDENTIFICATION_REPLIES[reply] == (
        "Esos datos no son válidos. Revísalos e indícame tu número de documento, "
        "tu nombre completo o los últimos 4 dígitos de tu tarjeta."
    )
    assert conv.status is ConversationStatus.ACTIVE
    # RN-007-41: un paso posterior del mismo turno gana (último resultado).
    conv.record_identification(IdentificationStep.LOCATED)
    assert select_identification_reply(conv, None) is IdentificationReply.ASK_DATES


def test_conversation_begin_turn__resets_identification_trace() -> None:
    """RN-007-41: begin_turn pone a cero el rastro del turno."""
    conv = _conv(step=IdentificationStep.WRONG_DATES, remaining=1)
    conv.turn_blocked_tools.append("evaluar_disputa")
    conv.begin_turn()
    assert conv.turn_identification is None
    assert conv.turn_attempts_remaining is None
    assert conv.turn_blocked_tools == []


def test_conversation_record_identification__keeps_only_last_and_no_side_effects() -> None:
    """RN-007-41: conserva solo el último paso y no altera estado de negocio."""
    conv = _conv(located="C-X")
    conv.record_identification(IdentificationStep.WRONG_DATES, 2)
    conv.record_identification(IdentificationStep.INVALID_DATES)
    assert conv.turn_identification is IdentificationStep.INVALID_DATES
    assert conv.turn_attempts_remaining is None
    assert conv.failed_searches == 0
    assert conv.verified_customer_id is None
    assert conv.status is ConversationStatus.ACTIVE
