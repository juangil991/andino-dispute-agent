"""Builder de derivaciones ficticias y deterministas."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from core_banking_mcp.domain.models.escalation import (
    Escalation,
    EscalationReason,
    EscalationStatus,
    PriorAction,
)


@dataclass
class EscalationBuilder:
    escalation_id: str = "ESC-000001"
    conversation_id: str = "conv-0001"
    idempotency_key: str = "key-0001"
    reason: EscalationReason = EscalationReason.OTHER
    escalated_at: datetime = field(default_factory=lambda: datetime(2026, 4, 1, 10, 0, tzinfo=UTC))
    identity_verified: bool = False
    customer_id: str | None = None
    transaction_id: str | None = None
    card_id: str | None = None
    prior_actions: frozenset[PriorAction] = frozenset()
    dispute_id: str | None = None
    note: str | None = None

    def with_id(self, escalation_id: str) -> "EscalationBuilder":
        self.escalation_id = escalation_id
        return self

    def with_conversation(self, conversation_id: str) -> "EscalationBuilder":
        self.conversation_id = conversation_id
        return self

    def with_key(self, idempotency_key: str) -> "EscalationBuilder":
        self.idempotency_key = idempotency_key
        return self

    def with_reason(self, reason: EscalationReason) -> "EscalationBuilder":
        self.reason = reason
        return self

    def with_escalated_at(self, escalated_at: datetime) -> "EscalationBuilder":
        self.escalated_at = escalated_at
        return self

    def verified_for(self, customer_id: str) -> "EscalationBuilder":
        self.identity_verified = True
        self.customer_id = customer_id
        return self

    def with_transaction(self, transaction_id: str | None) -> "EscalationBuilder":
        self.transaction_id = transaction_id
        return self

    def with_card(self, card_id: str | None) -> "EscalationBuilder":
        self.card_id = card_id
        return self

    def with_prior_actions(self, *actions: PriorAction) -> "EscalationBuilder":
        self.prior_actions = frozenset(actions)
        return self

    def with_dispute(self, dispute_id: str | None) -> "EscalationBuilder":
        self.dispute_id = dispute_id
        return self

    def with_note(self, note: str | None) -> "EscalationBuilder":
        self.note = note
        return self

    def build(self) -> Escalation:
        return Escalation(
            escalation_id=self.escalation_id,
            conversation_id=self.conversation_id,
            idempotency_key=self.idempotency_key,
            reason=self.reason,
            status=EscalationStatus.PENDING,
            escalated_at=self.escalated_at,
            identity_verified=self.identity_verified,
            customer_id=self.customer_id,
            transaction_id=self.transaction_id,
            card_id=self.card_id,
            prior_actions=self.prior_actions,
            dispute_id=self.dispute_id,
            note=self.note,
        )
