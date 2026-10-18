"""Repositorio de tarjetas sobre SQLAlchemy; mapea filas a dominio."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core_banking_mcp.domain.models.card_block import BlockReason, CardBlock, OwnedCard
from core_banking_mcp.domain.models.customer import CardStatus
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    CardBlockRow,
    CardRow,
)


def _naive_utc(instant: datetime) -> datetime:
    return instant.astimezone(UTC).replace(tzinfo=None)


def _to_block(row: CardBlockRow, card_ref: str) -> CardBlock:
    return CardBlock(
        card_id=card_ref,
        conversation_id=row.conversation_id,
        idempotency_key=row.idempotency_key,
        reason=BlockReason(row.reason),
        blocked_at=row.blocked_at.replace(tzinfo=UTC),
    )


class SqlAlchemyCardRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_customer_card(self, customer_id: str, card_id: str) -> OwnedCard | None:
        row = self._session.scalar(
            select(CardRow).where(CardRow.customer_id == customer_id, CardRow.card_ref == card_id)
        )
        if row is None:
            return None
        return OwnedCard(row.card_ref, row.last4, CardStatus(row.status))

    def find_block_by_key(self, conversation_id: str, idempotency_key: str) -> CardBlock | None:
        result = self._session.execute(
            select(CardBlockRow, CardRow.card_ref)
            .join(CardRow, CardRow.card_id == CardBlockRow.card_id)
            .where(
                CardBlockRow.conversation_id == conversation_id,
                CardBlockRow.idempotency_key == idempotency_key,
            )
        ).first()
        return None if result is None else _to_block(result[0], result[1])

    def find_block_by_card(self, card_id: str) -> CardBlock | None:
        result = self._session.execute(
            select(CardBlockRow, CardRow.card_ref)
            .join(CardRow, CardRow.card_id == CardBlockRow.card_id)
            .where(CardRow.card_ref == card_id)
        ).first()
        return None if result is None else _to_block(result[0], result[1])

    def block(
        self,
        conversation_id: str,
        idempotency_key: str,
        card_id: str,
        reason: BlockReason,
        blocked_at: datetime,
    ) -> CardBlock:
        """Bloquea la tarjeta y registra el bloqueo; ante un error hace rollback y relanza."""
        try:
            result = self._session.execute(
                update(CardRow)
                .where(CardRow.card_ref == card_id, CardRow.status == CardStatus.ACTIVE.value)
                .values(status=CardStatus.BLOCKED.value)
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]
                raise RuntimeError("la tarjeta no está ACTIVE")
            internal_id = self._session.scalar(
                select(CardRow.card_id).where(CardRow.card_ref == card_id)
            )
            assert internal_id is not None
            row = CardBlockRow(
                card_id=internal_id,
                conversation_id=conversation_id,
                idempotency_key=idempotency_key,
                reason=reason.value,
                blocked_at=_naive_utc(blocked_at),
            )
            self._session.add(row)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return _to_block(row, card_id)
