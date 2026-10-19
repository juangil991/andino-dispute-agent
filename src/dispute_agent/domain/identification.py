"""Pasos y textos de la atención antes de verificar la identidad (spec §4.8, RN-007-38)."""

from enum import Enum
from typing import TYPE_CHECKING

from dispute_agent.domain.models.outcome import OutcomeKind

if TYPE_CHECKING:
    from dispute_agent.domain.models.conversation import Conversation


class IdentificationStep(Enum):
    """Último paso de identificación ocurrido en el turno (RN-007-41)."""

    LOCATED = "LOCATED"
    MORE_DATA_NEEDED = "MORE_DATA_NEEDED"
    NOT_FOUND = "NOT_FOUND"
    WRONG_DATES = "WRONG_DATES"
    INVALID_DATES = "INVALID_DATES"


class IdentificationReply(Enum):
    """Textos fijos de spec §7.4."""

    REMINDER_LOCATE = "REMINDER_LOCATE"
    REMINDER_VERIFY = "REMINDER_VERIFY"
    ASK_DATES = "ASK_DATES"
    ASK_MORE_DATA = "ASK_MORE_DATA"
    NOT_FOUND = "NOT_FOUND"
    WRONG_DATES_2 = "WRONG_DATES_2"
    WRONG_DATES_1 = "WRONG_DATES_1"
    INVALID_DATES = "INVALID_DATES"
    CLOSED_ESCALATED = "CLOSED_ESCALATED"
    CLOSED_ESCALATION_FAILED = "CLOSED_ESCALATION_FAILED"


_STEP_REPLIES: dict[IdentificationStep, IdentificationReply] = {
    IdentificationStep.LOCATED: IdentificationReply.ASK_DATES,
    IdentificationStep.MORE_DATA_NEEDED: IdentificationReply.ASK_MORE_DATA,
    IdentificationStep.NOT_FOUND: IdentificationReply.NOT_FOUND,
    IdentificationStep.INVALID_DATES: IdentificationReply.INVALID_DATES,
}


def select_identification_reply(
    conv: "Conversation", last_outcome_kind: OutcomeKind | None
) -> IdentificationReply:
    """Elige el texto fijo del turno en el orden de RN-007-38."""
    # Import local: Conversation depende de IdentificationStep (evita el ciclo).
    from dispute_agent.domain.models.conversation import ConversationStatus

    if conv.status is ConversationStatus.ESCALATED:
        if last_outcome_kind is OutcomeKind.ESCALATION_FAILED:
            return IdentificationReply.CLOSED_ESCALATION_FAILED
        return IdentificationReply.CLOSED_ESCALATED
    step = conv.turn_identification
    if step is IdentificationStep.WRONG_DATES:
        if conv.turn_attempts_remaining == 1:
            return IdentificationReply.WRONG_DATES_1
        return IdentificationReply.WRONG_DATES_2
    if step is not None:
        return _STEP_REPLIES[step]
    if conv.located_customer_id is not None:
        return IdentificationReply.REMINDER_VERIFY
    return IdentificationReply.REMINDER_LOCATE
