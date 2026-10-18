"""Repositorio de disputas sobre SQLAlchemy; mapea filas a dominio."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core_banking_mcp.domain.models.dispute import Dispute, DisputeReason, DisputeStatus
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import DisputeRow


def _naive_utc(instant: datetime) -> datetime:
    return instant.astimezone(UTC).replace(tzinfo=None)


def _to_domain(row: DisputeRow) -> Dispute:
    return Dispute(
        dispute_id=row.dispute_id,
        conversation_id=row.conversation_id,
        idempotency_key=row.idempotency_key,
        transaction_id=row.transaction_id,
        reason=DisputeReason(row.reason),
        status=DisputeStatus(row.status),
        opened_at=row.opened_at.replace(tzinfo=UTC),
    )


class SqlAlchemyDisputeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_idempotency_key(self, conversation_id: str, idempotency_key: str) -> Dispute | None:
        row = self._session.scalar(
            select(DisputeRow).where(
                DisputeRow.conversation_id == conversation_id,
                DisputeRow.idempotency_key == idempotency_key,
            )
        )
        return None if row is None else _to_domain(row)

    def find_open_by_transaction(self, transaction_id: str) -> Dispute | None:
        row = self._session.scalar(
            select(DisputeRow).where(
                DisputeRow.transaction_id == transaction_id,
                DisputeRow.status == DisputeStatus.OPEN.value,
            )
        )
        return None if row is None else _to_domain(row)

    def add(
        self,
        conversation_id: str,
        idempotency_key: str,
        transaction_id: str,
        reason: DisputeReason,
        status: DisputeStatus,
        opened_at: datetime,
    ) -> Dispute:
        """Persiste la disputa (DSP-NNNNNN); ante cualquier error hace rollback y relanza."""
        try:
            total = self._session.scalar(select(func.count()).select_from(DisputeRow)) or 0
            row = DisputeRow(
                dispute_id=f"DSP-{total + 1:06d}",
                transaction_id=transaction_id,
                conversation_id=conversation_id,
                idempotency_key=idempotency_key,
                reason=reason.value,
                status=status.value,
                opened_at=_naive_utc(opened_at),
            )
            self._session.add(row)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return _to_domain(row)
