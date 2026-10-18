"""Puerto de salida: persistencia del bloqueo de tarjetas."""

from datetime import datetime
from typing import Protocol

from core_banking_mcp.domain.models.card_block import BlockReason, CardBlock, OwnedCard


class CardRepository(Protocol):
    def find_customer_card(self, customer_id: str, card_id: str) -> OwnedCard | None:
        """Tarjeta del cliente con ese identificador; `None` si no existe o es ajena."""
        ...

    def find_block_by_key(self, conversation_id: str, idempotency_key: str) -> CardBlock | None:
        """Bloqueo de esa conversación con esa clave de idempotencia, si existe."""
        ...

    def find_block_by_card(self, card_id: str) -> CardBlock | None:
        """Bloqueo registrado para la tarjeta, si existe."""
        ...

    def block(
        self,
        conversation_id: str,
        idempotency_key: str,
        card_id: str,
        reason: BlockReason,
        blocked_at: datetime,
    ) -> CardBlock:
        """Bloquea la tarjeta y registra el bloqueo de forma atómica (todo o nada)."""
        ...
