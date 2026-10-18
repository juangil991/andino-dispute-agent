"""Filtro determinista de datos personales en las respuestas (RN-007-26)."""

import re
from collections.abc import Iterable

_PAN = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")


def mask_document(document: str) -> str:
    """Enmascara un documento: ``****`` + 2 últimos caracteres (RN-001-09)."""
    if len(document) <= 4:
        return "****"
    return "****" + document[-2:]


def redact_reply(text: str, documents: Iterable[str]) -> str:
    """Redacta secuencias de 13-19 dígitos y enmascara los documentos aportados."""
    result = _PAN.sub("[REDACTED]", text)
    for document in sorted({d for d in documents if d}, key=len, reverse=True):
        result = result.replace(document, mask_document(document))
    return result
