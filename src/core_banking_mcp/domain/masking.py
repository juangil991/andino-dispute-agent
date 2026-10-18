"""Enmascarado de datos sensibles (documento y tarjeta)."""

import re

_MASK = "****"
_REDACTED = "[REDACTED]"
_CARD_NUMBER_RUN = re.compile(r"[0-9]{13,19}")


def mask_document(document: str) -> str:
    """Enmascara un documento dejando visibles solo los 2 últimos caracteres."""
    if len(document) <= 4:
        return _MASK
    return f"{_MASK}{document[-2:]}"


def mask_card(last4: str) -> str:
    """Devuelve la tarjeta enmascarada a partir de sus últimos 4 dígitos."""
    return f"{_MASK} {last4}"


def redact_card_numbers(text: str) -> str:
    """Sustituye por [REDACTED] toda secuencia de 13 a 19 dígitos seguidos."""
    return _CARD_NUMBER_RUN.sub(_REDACTED, text)
