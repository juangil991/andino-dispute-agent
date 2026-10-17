"""Pruebas del parseo estricto de fechas ISO compartido."""

from datetime import date

import pytest

from core_banking_mcp.domain.dates import parse_iso_date
from core_banking_mcp.domain.errors import InvalidInputError


# Regla: RN-003-06 — `date_from` y `date_to` obligatorias, en formato `AAAA-MM-DD` y existentes en el calendario; toda violación ⇒ `INVALID_INPUT`, sin transacciones.  # noqa: E501
# AC-003-09 · Art. 3
@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "01/09/2026",
        "2026-09-31",
        "20260901",
        "2026-W36-2",
        " 2026-09-01",
        "٢٠٢٦-٠٩-٠١",
    ],
    ids=[
        "none",
        "empty",
        "slash-format",
        "nonexistent-date",
        "no-separators",
        "iso-week",
        "leading-space",
        "non-ascii-digits",
    ],
)
def test_ac_003_09_parse_iso_date_rejects_invalid_format_and_nonexistent_dates(
    value: str | None,
) -> None:
    """AC-003-09: fecha inexistente o con formato distinto de AAAA-MM-DD es INVALID_INPUT."""
    with pytest.raises(InvalidInputError) as exc_info:
        parse_iso_date("date_from", value)

    assert exc_info.value.field == "date_from"


# Soporte de tests: camino feliz del parseo de fechas ISO · Art. 3
def test_parse_iso_date_returns_date_for_valid_input() -> None:
    assert parse_iso_date("date_to", "2026-09-01") == date(2026, 9, 1)
