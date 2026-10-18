"""Tests del filtro determinista de datos personales (RN-007-26)."""

import pytest

from dispute_agent.domain.redaction import redact_reply

DOCS = {"D-1001"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("4111111111114321", "[REDACTED]"),
        ("4111 1111 1111 4321", "[REDACTED]"),
        ("4111-1111-1111-4321", "[REDACTED]"),
        ("D-1001", "****01"),
        ("**** 4321", "**** 4321"),
        ("85000.00 COP", "85000.00 COP"),
    ],
)
# Regla: RN-007-26 — Antes de enviarse, el `reply` pasa por un filtro determinista. Toda
# secuencia de 13 a 19 dígitos seguidos (incluso separados por espacios o guiones) se sustituye
# por `[REDACTED]`. Todo documento que el cliente haya aportado en la conversación se sustituye
# por su forma enmascarada (RN-001-09). Las tarjetas solo aparecen como `**** NNNN`. El filtro
# también se aplica a `outcomes`.
# AC-007-27 · Art. 7 (datos mínimos)
def test_ac_007_27_redact_reply__pii_variants(text: str, expected: str) -> None:
    """AC-007-27: el reply enviado no contiene PAN ni documentos en claro."""
    assert redact_reply(text, DOCS) == expected


# Soporte de tests: un número de más de 19 dígitos no se redacta · Art. 3
def test_redact_reply__long_number_untouched() -> None:
    """Un número de 20 dígitos no se redacta parcialmente."""
    text = "ref 12345678901234567890 ok"
    assert redact_reply(text, DOCS) == text


# Soporte de tests: documento corto se enmascara por completo · Art. 3
def test_redact_reply__short_document_fully_masked() -> None:
    """Un documento de 4 caracteres o menos se enmascara como ****."""
    assert redact_reply("doc AB12 aqui", {"AB12"}) == "doc **** aqui"
