"""Repositorio de derivaciones cuya escritura falla hasta que se repara."""

from collections.abc import Iterable
from datetime import datetime

from core_banking_mcp.domain.models.escalation import (
    Escalation,
    EscalationReason,
    PriorAction,
)
from tests.fakes.fake_escalation_repository import FakeEscalationRepository


class FailingEscalationRepository(FakeEscalationRepository):
    def __init__(self, escalations: Iterable[Escalation] = ()) -> None:
        super().__init__(escalations)
        self._failing = True

    def repair(self) -> None:
        self._failing = False

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
        if self._failing:
            self.add_called = True
            raise RuntimeError("fallo simulado del core (detalle interno secreto)")
        return super().add(
            conversation_id,
            idempotency_key,
            reason,
            escalated_at,
            identity_verified,
            customer_id,
            transaction_id,
            card_id,
            prior_actions,
            dispute_id,
            note,
        )
