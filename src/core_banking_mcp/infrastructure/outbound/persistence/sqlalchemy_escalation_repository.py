"""Repositorio de derivaciones sobre SQLAlchemy; mapea filas a dominio."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core_banking_mcp.domain.models.escalation import (
    Escalation,
    EscalationReason,
    EscalationStatus,
    PriorAction,
)
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    CardRow,
    EscalationRow,
)


def _naive_utc(instant: datetime) -> datetime:
    return instant.astimezone(UTC).replace(tzinfo=None)


def _encode_actions(actions: frozenset[PriorAction]) -> str:
    return ",".join(action.value for action in PriorAction if action in actions)


def _decode_actions(text: str) -> frozenset[PriorAction]:
    return frozenset(PriorAction(code) for code in text.split(",") if code)


def _to_domain(row: EscalationRow, card_ref: str | None) -> Escalation:
    return Escalation(
        escalation_id=row.escalation_id,
        conversation_id=row.conversation_id,
        idempotency_key=row.idempotency_key,
        reason=EscalationReason(row.reason),
        status=EscalationStatus(row.status),
        escalated_at=row.escalated_at.replace(tzinfo=UTC),
        identity_verified=row.identity_verified,
        customer_id=row.customer_id,
        transaction_id=row.transaction_id,
        card_id=card_ref,
        prior_actions=_decode_actions(row.prior_actions),
        dispute_id=row.dispute_id,
        note=row.note,
    )


class SqlAlchemyEscalationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_key(self, conversation_id: str, idempotency_key: str) -> Escalation | None:
        result = self._session.execute(
            select(EscalationRow, CardRow.card_ref)
            .outerjoin(CardRow, CardRow.card_id == EscalationRow.card_id)
            .where(
                EscalationRow.conversation_id == conversation_id,
                EscalationRow.idempotency_key == idempotency_key,
            )
        ).first()
        return None if result is None else _to_domain(result[0], result[1])

    def add(
        self,
        conversation_id: str,
        idempotency_key: str,
        reason: EscalationReason,
        escalated_at: datetime,
        identity_verified: bool,
        customer_id: str | None,
        transaction_id: str | None,
        card_id: str | None,
        prior_actions: frozenset[PriorAction],
        dispute_id: str | None,
        note: str | None,
    ) -> Escalation:
        """Persiste la derivación (ESC-NNNNNN); ante cualquier error hace rollback y relanza."""
        try:
            internal_card_id: int | None = None
            if card_id is not None:
                internal_card_id = self._session.scalar(
                    select(CardRow.card_id).where(CardRow.card_ref == card_id)
                )
            total = self._session.scalar(select(func.count()).select_from(EscalationRow)) or 0
            row = EscalationRow(
                escalation_id=f"ESC-{total + 1:06d}",
                conversation_id=conversation_id,
                idempotency_key=idempotency_key,
                reason=reason.value,
                status=EscalationStatus.PENDING.value,
                escalated_at=_naive_utc(escalated_at),
                identity_verified=identity_verified,
                customer_id=customer_id,
                transaction_id=transaction_id,
                card_id=internal_card_id,
                dispute_id=dispute_id,
                prior_actions=_encode_actions(prior_actions),
                note=note,
            )
            self._session.add(row)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return _to_domain(row, card_id)
