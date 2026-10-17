"""Normalización de nombre y documento para la búsqueda de clientes."""

import unicodedata


def normalize_name(value: str) -> str:
    """Normaliza un nombre: sin acentos, minúsculas y espacios colapsados."""
    decomposed = unicodedata.normalize("NFD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


def normalize_document(value: str) -> str:
    """Normaliza un documento: recortado y sin distinguir mayúsculas."""
    return value.strip().casefold()
