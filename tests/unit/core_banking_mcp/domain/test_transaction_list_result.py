"""Tests de dominio del tope de transacciones (feature 003)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from core_banking_mcp.domain.models.transaction import (
    MAX_TRANSACTIONS,
    Transaction,
    TransactionListResult,
    TransactionStatus,
)


def _tx(index: int) -> Transaction:
    return Transaction(
        transaction_id=f"tx-{index:03d}",
        card_id="card-1",
        card_last4="4321",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=index),
        merchant="Comercio Ficticio",
        amount=Decimal("10.00"),
        currency="COP",
        status=TransactionStatus.CONFIRMED,
    )


# Regla: RN-003-10 — Tope de 50 transacciones. Sin transacciones en el rango, la respuesta es exitosa con lista vacía y `refinement_required = false`. Con 1 a 50 se devuelven todas con `refinement_required = false`. Con más de 50, la respuesta es exitosa, **sin ninguna transacción** y con `refinement_required = true` para que se acote el rango.  # noqa: E501
# AC-003-06 · Art. 3
def test_ac_003_06_no_matches_is_empty_success() -> None:
    """AC-003-06: sin transacciones en el rango, lista vacía y sin refinar."""
    result = TransactionListResult.from_matches([])

    assert result.transactions == ()
    assert result.refinement_required is False


# Regla: RN-003-10 — Tope de 50 transacciones. Sin transacciones en el rango, la respuesta es exitosa con lista vacía y `refinement_required = false`. Con 1 a 50 se devuelven todas con `refinement_required = false`. Con más de 50, la respuesta es exitosa, **sin ninguna transacción** y con `refinement_required = true` para que se acote el rango.  # noqa: E501
# AC-003-08 · Art. 3
@pytest.mark.parametrize(
    ("count", "returned", "refinement"),
    [(49, 49, False), (50, 50, False), (51, 0, True)],
    ids=["49-returns-all", "50-returns-all-edge", "51-returns-none-refine"],
)
def test_ac_003_08_more_than_fifty_requires_refinement(
    count: int, returned: int, refinement: bool
) -> None:
    """AC-003-08: más de 50 transacciones devuelve vacío y pide refinar."""
    assert MAX_TRANSACTIONS == 50

    result = TransactionListResult.from_matches([_tx(i) for i in range(count)])

    assert len(result.transactions) == returned
    assert result.refinement_required is refinement


# Soporte de tests: el orden recibido se conserva en from_matches · Art. 3
def test_support_from_matches_preserves_received_order() -> None:
    """Soporte: from_matches no reordena (el orden lo define el repositorio)."""
    matches = [_tx(2), _tx(0), _tx(1)]

    result = TransactionListResult.from_matches(matches)

    assert result.transactions == tuple(matches)


# Soporte de tests: refinement_required con transacciones es un estado inválido · Art. 3
def test_support_refinement_with_transactions_is_invalid() -> None:
    """Soporte: el invariante rechaza refinar con transacciones presentes."""
    with pytest.raises(ValueError, match="refinement_required"):
        TransactionListResult((_tx(0),), True)
