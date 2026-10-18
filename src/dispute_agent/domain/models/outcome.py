"""Resultado estructurado de una acción o decisión del turno (spec §7.3)."""

from dataclasses import dataclass
from enum import Enum

from dispute_agent.domain.errors import InvalidOutcomeError


class OutcomeKind(Enum):
    """Tipos de resultado de spec §7.3."""

    DISPUTE_OPENED = "DISPUTE_OPENED"
    NOT_DISPUTABLE = "NOT_DISPUTABLE"
    ESCALATED = "ESCALATED"
    CARD_BLOCKED = "CARD_BLOCKED"
    CARD_ALREADY_BLOCKED = "CARD_ALREADY_BLOCKED"
    CARD_NOT_BLOCKABLE = "CARD_NOT_BLOCKABLE"
    DISPUTE_ALREADY_OPEN = "DISPUTE_ALREADY_OPEN"
    NO_TRANSACTIONS_FOUND = "NO_TRANSACTIONS_FOUND"
    REFINEMENT_REQUIRED = "REFINEMENT_REQUIRED"
    ITERATION_LIMIT = "ITERATION_LIMIT"
    LLM_FAILURE = "LLM_FAILURE"
    ESCALATION_FAILED = "ESCALATION_FAILED"


@dataclass(frozen=True)
class Outcome:
    """Lo ocurrido en el turno, con textos fijos en español."""

    kind: OutcomeKind
    rule: str
    reason: str
    next_steps: str
    transaction_id: str | None = None
    masked_card: str | None = None
    reference: str | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise InvalidOutcomeError("reason no puede estar vacío")
        if not self.next_steps.strip():
            raise InvalidOutcomeError("next_steps no puede estar vacío")
