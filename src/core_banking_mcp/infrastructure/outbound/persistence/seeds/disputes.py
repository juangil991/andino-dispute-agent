"""Semillas ficticias de disputas (plan §4, Art. 1). Datos fijos, sin aleatoriedad."""

from datetime import datetime, timedelta, timezone

from core_banking_mcp.domain.models.dispute import DisputeReason, DisputeStatus
from core_banking_mcp.infrastructure.outbound.persistence.sqlalchemy_dispute_repository import (
    SqlAlchemyDisputeRepository,
)

_BOGOTA = timezone(timedelta(hours=-5))
_SEED_CONVERSATION = "SEED"

# (clave de idempotencia, transacción, motivo, estado, instante en Bogotá)
SEED_DISPUTES: tuple[tuple[str, str, DisputeReason, DisputeStatus, datetime], ...] = (
    (
        "SEED-1",
        "TX-000002",
        DisputeReason.UNRECOGNIZED_CHARGE,
        DisputeStatus.OPEN,
        datetime(2026, 9, 14, 10, 0, tzinfo=_BOGOTA),
    ),
    (
        "SEED-2",
        "TX-000006",
        DisputeReason.NOT_RECEIVED,
        DisputeStatus.CLOSED,
        datetime(2026, 9, 20, 9, 30, tzinfo=_BOGOTA),
    ),
    (
        "SEED-3",
        "TX-000008",
        DisputeReason.INCORRECT_AMOUNT,
        DisputeStatus.REJECTED,
        datetime(2026, 9, 25, 16, 45, tzinfo=_BOGOTA),
    ),
)


def seed_disputes(repository: SqlAlchemyDisputeRepository) -> None:
    """Inserta las disputas semilla en orden (el repositorio asigna los DSP-*)."""
    for key, transaction_id, reason, status, opened_at in SEED_DISPUTES:
        repository.add(_SEED_CONVERSATION, key, transaction_id, reason, status, opened_at)
