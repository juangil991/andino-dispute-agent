"""Repositorio de derivaciones en memoria."""

from collections.abc import Iterable
from datetime import datetime

from core_banking_mcp.domain.models.escalation import (
    Escalation,
    EscalationReason,
    EscalationStatus,
    PriorAction,
)


class FakeEscalationRepository:
    def __init__(self, escalations: Iterable[Escalation] = ()) -> None:
        self._escalations = list(escalations)
        self.add_called = False

    @property
    def escalations(self) -> list[Escalation]:
        return list(self._escalations)

    def find_by_key(self, conversation_id: str, idempotency_key: str) -> Escalation | None:
        for e in self._escalations:
            if e.conversation_id == conversation_id and e.idempotency_key == idempotency_key:
                return e
        return None

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
        self.add_called = True
        if self.find_by_key(conversation_id, idempotency_key) is not None:
            raise ValueError("clave de idempotencia ya registrada en la conversación")
        escalation = Escalation(
            escalation_id=f"ESC-{len(self._escalations) + 1:06d}",
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            reason=reason,
            status=EscalationStatus.PENDING,
            escalated_at=escalated_at,
            identity_verified=identity_verified,
            customer_id=customer_id,
            transaction_id=transaction_id,
            card_id=card_id,
            prior_actions=prior_actions,
            dispute_id=dispute_id,
            note=note,
        )
        self._escalations.append(escalation)
        return escalation
