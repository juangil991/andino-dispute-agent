"""Repositorio de tarjetas y transacciones sobre SQLAlchemy; mapea filas a dominio."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core_banking_mcp.domain.models.transaction import (
    CustomerCard,
    Transaction,
    TransactionStatus,
)
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    CardRow,
    TransactionRow,
)

_CENTS = Decimal(100)
_CENTS_STEP = Decimal("0.01")


def _naive_utc(instant: datetime) -> datetime:
    return instant.astimezone(UTC).replace(tzinfo=None)


def _to_transaction(row: TransactionRow, card_ref: str, last4: str) -> Transaction:
    return Transaction(
        transaction_id=row.transaction_id,
        card_id=card_ref,
        card_last4=last4,
        occurred_at=row.occurred_at.replace(tzinfo=UTC),
        merchant=row.merchant,
        amount=(Decimal(row.amount_minor) / _CENTS).quantize(_CENTS_STEP),
        currency=row.currency,
        status=TransactionStatus(row.status),
    )


class SqlAlchemyTransactionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, card_ref: str, transaction: Transaction) -> None:
        """Inserta la transacción en la tarjeta `card_ref`; guarda el instante en UTC."""
        card_pk = self._session.scalar(select(CardRow.card_id).where(CardRow.card_ref == card_ref))
        if card_pk is None:
            raise ValueError(f"tarjeta desconocida: {card_ref}")
        self._session.add(
            TransactionRow(
                transaction_id=transaction.transaction_id,
                card_id=card_pk,
                occurred_at=_naive_utc(transaction.occurred_at),
                merchant=transaction.merchant,
                amount_minor=int(transaction.amount * _CENTS),
                currency=transaction.currency,
                status=transaction.status.value,
            )
        )
        self._session.commit()

    def find_customer_cards(self, customer_id: str, last4: str) -> list[CustomerCard]:
        stmt = (
            select(CardRow)
            .where(CardRow.customer_id == customer_id, CardRow.last4 == last4)
            .order_by(CardRow.card_ref)
        )
        return [CustomerCard(row.card_ref, row.last4) for row in self._session.scalars(stmt)]

    def find_transactions(
        self, card_ids: list[str], start: datetime, end: datetime, limit: int
    ) -> list[Transaction]:
        stmt = (
            select(TransactionRow, CardRow.card_ref, CardRow.last4)
            .join(CardRow, TransactionRow.card_id == CardRow.card_id)
            .where(
                CardRow.card_ref.in_(card_ids),
                TransactionRow.occurred_at >= _naive_utc(start),
                TransactionRow.occurred_at < _naive_utc(end),
            )
            .order_by(TransactionRow.occurred_at.desc(), TransactionRow.transaction_id.asc())
            .limit(limit)
        )
        return [
            _to_transaction(row, card_ref, last4)
            for row, card_ref, last4 in self._session.execute(stmt)
        ]

    def find_customer_transaction(
        self, customer_id: str, transaction_id: str
    ) -> Transaction | None:
        """Transacción si pertenece a una tarjeta del cliente (cualquier estado); si no, None."""
        stmt = (
            select(TransactionRow, CardRow.card_ref, CardRow.last4)
            .join(CardRow, TransactionRow.card_id == CardRow.card_id)
            .where(
                CardRow.customer_id == customer_id,
                TransactionRow.transaction_id == transaction_id,
            )
        )
        found = self._session.execute(stmt).first()
        if found is None:
            return None
        row, card_ref, last4 = found
        return _to_transaction(row, card_ref, last4)
