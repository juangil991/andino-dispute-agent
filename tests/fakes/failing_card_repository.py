"""Repositorio de tarjetas cuya escritura falla hasta que se repara."""

from collections.abc import Iterable, Mapping
from datetime import datetime

from core_banking_mcp.domain.models.card_block import BlockReason, CardBlock, OwnedCard
from tests.fakes.fake_card_repository import FakeCardRepository


class FailingCardRepository(FakeCardRepository):
    def __init__(
        self,
        cards: Mapping[str, Iterable[OwnedCard]] | None = None,
        blocks: Iterable[CardBlock] = (),
    ) -> None:
        super().__init__(cards=cards, blocks=blocks)
        self._failing = True

    def repair(self) -> None:
        self._failing = False

    def block(
        self,
        conversation_id: str,
        idempotency_key: str,
        card_id: str,
        reason: BlockReason,
        blocked_at: datetime,
    ) -> CardBlock:
        if self._failing:
            self.block_called = True
            raise RuntimeError("fallo simulado del core (detalle interno secreto)")
        return super().block(conversation_id, idempotency_key, card_id, reason, blocked_at)
