"""Repositorio de tarjetas y bloqueos en memoria."""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime

from core_banking_mcp.domain.models.card_block import BlockReason, CardBlock, OwnedCard
from core_banking_mcp.domain.models.customer import CardStatus


class FakeCardRepository:
    def __init__(
        self,
        cards: Mapping[str, Iterable[OwnedCard]] | None = None,
        blocks: Iterable[CardBlock] = (),
    ) -> None:
        self._cards: dict[str, list[OwnedCard]] = {
            customer_id: list(owned) for customer_id, owned in (cards or {}).items()
        }
        self._blocks = list(blocks)
        self.block_called = False

    @property
    def blocks(self) -> list[CardBlock]:
        return list(self._blocks)

    def find_customer_card(self, customer_id: str, card_id: str) -> OwnedCard | None:
        for card in self._cards.get(customer_id, []):
            if card.card_id == card_id:
                return card
        return None

    def find_block_by_key(self, conversation_id: str, idempotency_key: str) -> CardBlock | None:
        for b in self._blocks:
            if b.conversation_id == conversation_id and b.idempotency_key == idempotency_key:
                return b
        return None

    def find_block_by_card(self, card_id: str) -> CardBlock | None:
        for b in self._blocks:
            if b.card_id == card_id:
                return b
        return None

    def block(
        self,
        conversation_id: str,
        idempotency_key: str,
        card_id: str,
        reason: BlockReason,
        blocked_at: datetime,
    ) -> CardBlock:
        self.block_called = True
        if self.find_block_by_key(conversation_id, idempotency_key) is not None:
            raise ValueError("clave de idempotencia ya registrada en la conversación")
        if self.find_block_by_card(card_id) is not None:
            raise ValueError("la tarjeta ya tiene un bloqueo registrado")
        record = CardBlock(
            card_id=card_id,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            reason=reason,
            blocked_at=blocked_at,
        )
        for owned in self._cards.values():
            for i, card in enumerate(owned):
                if card.card_id == card_id:
                    owned[i] = replace(card, status=CardStatus.BLOCKED)
        self._blocks.append(record)
        return record
