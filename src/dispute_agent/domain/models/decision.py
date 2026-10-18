"""Decisión de DisputePolicy y enums asociados."""

from dataclasses import dataclass
from enum import Enum

from dispute_agent.domain.errors import InvalidDecisionError


class Decision(Enum):
    """Decisión sobre una transacción disputada."""

    RESOLVE = "RESOLVE"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class AgentAction(Enum):
    """Acción de escritura que la aplicación puede ejecutar."""

    OPEN_DISPUTE = "OPEN_DISPUTE"
    BLOCK_CARD = "BLOCK_CARD"
    ESCALATE = "ESCALATE"


class EscalationReason(Enum):
    """Motivo de derivación (catálogo cerrado, RN-006-02)."""

    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"
    AMOUNT_OVER_THRESHOLD = "AMOUNT_OVER_THRESHOLD"
    INSUFFICIENT_OR_CONTRADICTORY_INFO = "INSUFFICIENT_OR_CONTRADICTORY_INFO"
    INCONCLUSIVE_RULES = "INCONCLUSIVE_RULES"
    UNRECOVERABLE_SYSTEM_FAILURE = "UNRECOVERABLE_SYSTEM_FAILURE"
    IDENTITY_VERIFICATION_FAILED = "IDENTITY_VERIFICATION_FAILED"
    OTHER = "OTHER"


class PriorAction(Enum):
    """Acción previa a la derivación; el orden de declaración es el canónico (RN-006-05)."""

    DISPUTE_OPENED = "DISPUTE_OPENED"
    CARD_BLOCKED = "CARD_BLOCKED"


@dataclass(frozen=True)
class DisputeDecision:
    """Resultado determinista de DisputePolicy para una transacción."""

    decision: Decision
    rule: str
    escalation_reason: EscalationReason | None
    allowed_actions: frozenset[AgentAction]
    customer_reason: str
    next_steps: str

    def __post_init__(self) -> None:
        if (self.decision is Decision.ESCALATE) != (self.escalation_reason is not None):
            raise InvalidDecisionError("ESCALATE exige escalation_reason y solo él lo admite")
        if self.decision is Decision.RESOLVE and self.allowed_actions != {AgentAction.OPEN_DISPUTE}:
            raise InvalidDecisionError("RESOLVE solo permite OPEN_DISPUTE")
        if self.decision is Decision.REJECT and self.allowed_actions:
            raise InvalidDecisionError("REJECT no permite acciones")
