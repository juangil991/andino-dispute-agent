"""Builder de tarjetas del cliente ficticias y deterministas."""

from dataclasses import dataclass

from core_banking_mcp.domain.models.card_block import OwnedCard
from core_banking_mcp.domain.models.customer import CardStatus


@dataclass
class OwnedCardBuilder:
    card_id: str = "CARD-0001"
    last4: str = "4321"
    status: CardStatus = CardStatus.ACTIVE

    def with_id(self, card_id: str) -> "OwnedCardBuilder":
        self.card_id = card_id
        return self

    def with_last4(self, last4: str) -> "OwnedCardBuilder":
        self.last4 = last4
        return self

    def with_status(self, status: CardStatus) -> "OwnedCardBuilder":
        self.status = status
        return self

    def build(self) -> OwnedCard:
        return OwnedCard(card_id=self.card_id, last4=self.last4, status=self.status)
