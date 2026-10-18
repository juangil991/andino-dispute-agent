"""Repositorio de disputas cuya escritura falla hasta que se repara."""

from datetime import datetime

from core_banking_mcp.domain.models.dispute import Dispute, DisputeReason, DisputeStatus
from tests.fakes.fake_dispute_repository import FakeDisputeRepository


class FailingDisputeRepository(FakeDisputeRepository):
    def __init__(self) -> None:
        super().__init__()
        self._failing = True

    def repair(self) -> None:
        self._failing = False

    def add(
        self,
        conversation_id: str,
        idempotency_key: str,
        transaction_id: str,
        reason: DisputeReason,
        status: DisputeStatus,
        opened_at: datetime,
    ) -> Dispute:
        if self._failing:
            raise RuntimeError("fallo simulado del core (detalle interno secreto)")
        return super().add(
            conversation_id, idempotency_key, transaction_id, reason, status, opened_at
        )
