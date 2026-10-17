"""Enmascarado de datos sensibles (documento y tarjeta)."""

_MASK = "****"


def mask_document(document: str) -> str:
    """Enmascara un documento dejando visibles solo los 2 últimos caracteres."""
    if len(document) <= 4:
        return _MASK
    return f"{_MASK}{document[-2:]}"


def mask_card(last4: str) -> str:
    """Devuelve la tarjeta enmascarada a partir de sus últimos 4 dígitos."""
    return f"{_MASK} {last4}"
