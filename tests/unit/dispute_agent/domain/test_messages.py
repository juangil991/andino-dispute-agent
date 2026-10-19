"""Textos fijos de spec 011 §7.1 y §7.2."""

import re

from dispute_agent.domain import messages


# Regla: RN-011-04 — texto fijo con solo los últimos 4 de la clienta.
# AC-011-06 · Art. 1
def test_ac_011_06_unknown_card_message__lists_own_last4_only() -> None:
    """AC-011-06: lista solo los últimos 4 de la clienta; une con ", " y " y "."""
    two = messages.unknown_card_message(("4321", "8765"))
    assert two == (
        "Esa tarjeta no está entre las de la clienta (terminadas en 4321 y 8765). "
        "Usa una de ellas o pregúntale a la clienta cuál es; no repitas los mismos dígitos."
    )
    three = messages.unknown_card_message(("4321", "8765", "1111"))
    assert "(terminadas en 4321, 8765 y 1111)" in three
    one = messages.unknown_card_message(("2468",))
    assert "(terminadas en 2468)" in one
    assert re.findall(r"\d+", one) == ["2468"]


# Regla: RN-011-05 — NOT_FOUND se devuelve con texto fijo.
# AC-011-07 · Art. 10
def test_ac_011_07_not_found_card_message__is_fixed_text() -> None:
    """AC-011-07: texto fijo de card not_found, sin valores enviados."""
    assert messages.NOT_FOUND_CARD_MESSAGE == (
        "No se encontró esa tarjeta. Pídele a la clienta que revise los últimos "
        "4 dígitos antes de volver a consultar."
    )
