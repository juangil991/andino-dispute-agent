"""Builder de bloqueos de tarjeta ficticios y deterministas."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from core_banking_mcp.domain.models.card_block import BlockReason, CardBlock


@dataclass
class CardBlockBuilder:
    card_id: str = "CARD-0001"
    conversation_id: str = "conv-0001"
    idempotency_key: str = "key-0001"
    reason: BlockReason = BlockReason.FRAUD_SUSPECTED
    blocked_at: datetime = field(default_factory=lambda: datetime(2026, 4, 1, 10, 0, tzinfo=UTC))

    def with_card(self, card_id: str) -> "CardBlockBuilder":
        self.card_id = card_id
        return self

    def with_conversation(self, conversation_id: str) -> "CardBlockBuilder":
        self.conversation_id = conversation_id
        return self

    def with_key(self, idempotency_key: str) -> "CardBlockBuilder":
        self.idempotency_key = idempotency_key
        return self

    def with_reason(self, reason: BlockReason) -> "CardBlockBuilder":
        self.reason = reason
        return self

    def with_blocked_at(self, blocked_at: datetime) -> "CardBlockBuilder":
        self.blocked_at = blocked_at
        return self

    def build(self) -> CardBlock:
        return CardBlock(
            card_id=self.card_id,
            conversation_id=self.conversation_id,
            idempotency_key=self.idempotency_key,
            reason=self.reason,
            blocked_at=self.blocked_at,
        )
