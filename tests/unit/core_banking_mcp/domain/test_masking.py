"""Tests de enmascarado de documento y tarjeta (AC-001-11, AC-001-12)."""

import pytest

from core_banking_mcp.domain.masking import mask_card, mask_document, redact_card_numbers


def test_ac_001_11_document_and_card_are_masked() -> None:
    """AC-001-11: el documento y la tarjeta se devuelven enmascarados."""
    assert mask_document("CC1234567") == "****67"
    assert mask_card("4321") == "**** 4321"


def test_ac_001_12_short_document_is_fully_masked() -> None:
    """AC-001-12: documentos de 4 o menos caracteres se enmascaran por completo."""
    assert mask_document("AB12") == "****"
    assert mask_document("AB123") == "****23"


# Regla: RN-004-16 — Como `transaction_id` e `idempotency_key` son texto libre, toda
# secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por
# `[REDACTED]`.
# AC-004-17 · Art. 8
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("4111111111114321", "[REDACTED]"),
        ("pago-4111111111114321", "pago-[REDACTED]"),
        ("1234567890123", "[REDACTED]"),
        ("1234567890123456789", "[REDACTED]"),
        ("123456789012", "123456789012"),
        ("TX-L1", "TX-L1"),
        ("4111111111114321-5500000000000004", "[REDACTED]-[REDACTED]"),
    ],
)
def test_ac_004_17_redact_card_numbers_replaces_13_to_19_digit_runs(
    text: str, expected: str
) -> None:
    """AC-004-17: las secuencias de 13 a 19 dígitos se sustituyen por [REDACTED]."""
    assert redact_card_numbers(text) == expected
