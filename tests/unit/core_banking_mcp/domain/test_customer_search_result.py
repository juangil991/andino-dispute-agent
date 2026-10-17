"""Tests de CustomerSearchResult (RN-001-06/07)."""

import pytest

from core_banking_mcp.domain.models.customer import Customer
from core_banking_mcp.domain.models.search import MAX_RESULTS, CustomerSearchResult


def _customers(n: int) -> list[Customer]:
    return [Customer(f"C-{i:03d}", f"Cliente Ficticio {i}", f"DOC-{i:03d}") for i in range(n)]


@pytest.mark.parametrize(
    ("count", "expected_len", "refinement"),
    [(0, 0, False), (4, 4, False), (5, 5, False), (6, 0, True)],
)
def test_ac_001_07_result_is_capped_at_five(
    count: int, expected_len: int, refinement: bool
) -> None:
    """AC-001-07: con más de 5 coincidencias se devuelve [] y refinement_required=True."""
    matches = _customers(count)

    result = CustomerSearchResult.from_matches(matches)

    assert MAX_RESULTS == 5
    assert len(result.customers) == expected_len
    assert result.refinement_required is refinement
    if not refinement:
        assert result.customers == tuple(matches)


def test_ac_001_06_no_matches_is_empty_result() -> None:
    """AC-001-06: sin coincidencias el resultado es vacío y no pide refinar."""
    result = CustomerSearchResult.from_matches([])

    assert result.customers == ()
    assert result.refinement_required is False


def test_ac_001_07_invariants_reject_inconsistent_state() -> None:
    """AC-001-07: invariantes de CustomerSearchResult en construcción directa."""
    with pytest.raises(ValueError):
        CustomerSearchResult(customers=tuple(_customers(6)), refinement_required=False)
    with pytest.raises(ValueError):
        CustomerSearchResult(customers=tuple(_customers(1)), refinement_required=True)
