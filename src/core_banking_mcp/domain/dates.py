"""Parseo estricto de fechas ISO compartido por los value objects."""

from __future__ import annotations

import re
from datetime import date

from core_banking_mcp.domain.errors import InvalidInputError

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_iso_date(field: str, value: str | None) -> date:
    """Convierte `AAAA-MM-DD` en fecha; rechaza otros formatos y fechas inexistentes."""
    if value is None or _ISO_DATE.fullmatch(value) is None:
        raise InvalidInputError(field, "debe tener formato AAAA-MM-DD")
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        raise InvalidInputError(field, "no es una fecha existente en el calendario") from None
