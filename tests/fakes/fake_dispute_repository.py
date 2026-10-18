"""Repositorio de disputas en memoria."""

from collections.abc import Iterable
from datetime import datetime

from core_banking_mcp.domain.models.dispute import Dispute, DisputeReason, DisputeStatus


class FakeDisputeRepository:
    def __init__(self, disputes: Iterable[Dispute] = ()) -> None:
        self._disputes = list(disputes)
        self.called = False

    @property
    def disputes(self) -> list[Dispute]:
        return list(self._disputes)

    def find_by_idempotency_key(self, conversation_id: str, idempotency_key: str) -> Dispute | None:
        self.called = True
        for d in self._disputes:
            if d.conversation_id == conversation_id and d.idempotency_key == idempotency_key:
                return d
        return None

    def find_open_by_transaction(self, transaction_id: str) -> Dispute | None:
        self.called = True
        for d in self._disputes:
            if d.transaction_id == transaction_id and d.status not in (
                DisputeStatus.CLOSED,
                DisputeStatus.REJECTED,
            ):
                return d
        return None

    def find_by_id(self, dispute_id: str) -> Dispute | None:
        self.called = True
        for d in self._disputes:
            if d.dispute_id == dispute_id:
                return d
        return None

    def add(
        self,
        conversation_id: str,
        idempotency_key: str,
        transaction_id: str,
        reason: DisputeReason,
        status: DisputeStatus,
        opened_at: datetime,
    ) -> Dispute:
        self.called = True
        dispute = Dispute(
            dispute_id=f"DSP-{len(self._disputes) + 1:06d}",
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            transaction_id=transaction_id,
            reason=reason,
            status=status,
            opened_at=opened_at,
        )
        self._disputes.append(dispute)
        return dispute
