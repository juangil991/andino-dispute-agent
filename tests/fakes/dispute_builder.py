"""Builder de disputas ficticias y deterministas."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from core_banking_mcp.domain.models.dispute import Dispute, DisputeReason, DisputeStatus


@dataclass
class DisputeBuilder:
    dispute_id: str = "DSP-000001"
    conversation_id: str = "conv-0001"
    idempotency_key: str = "key-0001"
    transaction_id: str = "T-0001"
    reason: DisputeReason = DisputeReason.UNRECOGNIZED_CHARGE
    status: DisputeStatus = DisputeStatus.OPEN
    opened_at: datetime = field(default_factory=lambda: datetime(2026, 4, 1, 10, 0, tzinfo=UTC))

    def with_id(self, dispute_id: str) -> "DisputeBuilder":
        self.dispute_id = dispute_id
        return self

    def with_status(self, status: DisputeStatus) -> "DisputeBuilder":
        self.status = status
        return self

    def with_transaction(self, transaction_id: str) -> "DisputeBuilder":
        self.transaction_id = transaction_id
        return self

    def with_conversation(self, conversation_id: str) -> "DisputeBuilder":
        self.conversation_id = conversation_id
        return self

    def with_key(self, idempotency_key: str) -> "DisputeBuilder":
        self.idempotency_key = idempotency_key
        return self

    def with_reason(self, reason: DisputeReason) -> "DisputeBuilder":
        self.reason = reason
        return self

    def with_opened_at(self, opened_at: datetime) -> "DisputeBuilder":
        self.opened_at = opened_at
        return self

    def build(self) -> Dispute:
        return Dispute(
            dispute_id=self.dispute_id,
            conversation_id=self.conversation_id,
            idempotency_key=self.idempotency_key,
            transaction_id=self.transaction_id,
            reason=self.reason,
            status=self.status,
            opened_at=self.opened_at,
        )
