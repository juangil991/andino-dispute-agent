"""Tests del value object SearchCriteria (RN-001-01, RN-001-05)."""

import pytest

from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.search import SearchCriteria


@pytest.mark.parametrize(
    ("document", "full_name", "card_last4", "field"),
    [
        (None, None, None, "criteria"),
        ("", None, None, "document"),
        ("D" * 33, None, None, "document"),
        (None, "   ", None, "full_name"),
        (None, "N" * 101, None, "full_name"),
        (None, None, "123", "card_last4"),
        (None, None, "12345", "card_last4"),
        (None, None, "12a4", "card_last4"),
    ],
)
def test_ac_001_09_invalid_criteria_are_rejected(
    document: str | None,
    full_name: str | None,
    card_last4: str | None,
    field: str,
) -> None:
    """AC-001-09: criterios inválidos lanzan InvalidInputError."""
    with pytest.raises(InvalidInputError) as exc_info:
        SearchCriteria.create(document, full_name, card_last4)
    assert exc_info.value.field == field


def test_ac_001_08_all_criteria_are_kept_normalized() -> None:
    """AC-001-08: con los tres criterios se conservan los valores normalizados."""
    criteria = SearchCriteria.create("  D-1001 ", "  José   ÁLVAREZ ", "1234")
    assert criteria.document == "d-1001"
    assert criteria.full_name == "jose alvarez"
    assert criteria.card_last4 == "1234"


def test_ac_001_09_boundary_lengths_are_valid() -> None:
    """AC-001-09: 32 caracteres de documento y 100 de nombre son válidos."""
    criteria = SearchCriteria.create("D" * 32, "N" * 100, None)
    assert criteria.document == "d" * 32
    assert criteria.full_name == "n" * 100
    assert criteria.card_last4 is None


def test_ac_001_09_length_is_counted_after_strip_not_after_collapse() -> None:
    """AC-001-09: RN-001-05 cuenta la longitud tras recortar, no tras colapsar espacios."""
    full_name = "A" + " " * 2 + "B" * 98  # 101 recortado, 100 colapsado
    with pytest.raises(InvalidInputError) as exc_info:
        SearchCriteria.create(None, full_name, None)
    assert exc_info.value.field == "full_name"
