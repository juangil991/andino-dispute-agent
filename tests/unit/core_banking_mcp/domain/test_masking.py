"""Tests de enmascarado de documento y tarjeta (AC-001-11, AC-001-12)."""

from core_banking_mcp.domain.masking import mask_card, mask_document


def test_ac_001_11_document_and_card_are_masked() -> None:
    """AC-001-11: el documento y la tarjeta se devuelven enmascarados."""
    assert mask_document("CC1234567") == "****67"
    assert mask_card("4321") == "**** 4321"


def test_ac_001_12_short_document_is_fully_masked() -> None:
    """AC-001-12: documentos de 4 o menos caracteres se enmascaran por completo."""
    assert mask_document("AB12") == "****"
    assert mask_document("AB123") == "****23"
