"""Tests de BogotaDateRange y TransactionQuery (validación de la consulta)."""

from datetime import UTC, date, datetime

import pytest

from core_banking_mcp.domain.clock import today_in_bogota
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.transaction import (
    MAX_RANGE_DAYS,
    BogotaDateRange,
    TransactionQuery,
)

_TODAY = date(2026, 10, 17)


def _create(
    conversation_id: str | None = "conv-1",
    card_last4: str | None = "4321",
    date_from: str | None = "2026-09-01",
    date_to: str | None = "2026-09-30",
    today: date = _TODAY,
) -> TransactionQuery:
    return TransactionQuery.create(conversation_id, card_last4, date_from, date_to, today)


# Regla: RN-003-06 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_last4` obligatorio, exactamente 4 dígitos `0-9`, sin espacios; `date_from` y `date_to` obligatorias, en formato `AAAA-MM-DD` y existentes en el calendario; `date_from` no posterior a `date_to`; `date_to` no posterior a hoy; el rango no supera **90 días contando ambos extremos** (`date_to − date_from + 1 ≤ 90`). No hay límite hacia el pasado para `date_from`. Toda violación ⇒ `INVALID_INPUT`, sin transacciones.  # noqa: E501
# AC-003-09 · Art. 3
@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"date_from": ""}, "date_from"),
        ({"date_to": ""}, "date_to"),
        ({"date_from": None}, "date_from"),
        ({"date_to": None}, "date_to"),
        ({"date_to": "2026-09-31"}, "date_to"),
        ({"date_from": "01/09/2026"}, "date_from"),
        ({"date_from": "2026-09-30", "date_to": "2026-09-01"}, "date_range"),
        ({"date_from": "2026-10-01", "date_to": "2026-10-18"}, "date_to"),
        ({"card_last4": None}, "card_last4"),
        ({"card_last4": "432"}, "card_last4"),
        ({"card_last4": "54321"}, "card_last4"),
        ({"card_last4": "43a1"}, "card_last4"),
        ({"conversation_id": "   "}, "conversation_id"),
    ],
    ids=[
        "date_from_empty",
        "date_to_empty",
        "date_from_null",
        "date_to_null",
        "date_to_nonexistent",
        "date_from_bad_format",
        "from_after_to",
        "to_after_today",
        "card_null",
        "card_3_digits",
        "card_5_digits",
        "card_letters",
        "conversation_blank",
    ],
)
def test_ac_003_09_invalid_query_is_rejected(overrides: dict[str, str | None], field: str) -> None:
    """AC-003-09: cada fila de datos inválidos lanza InvalidInputError."""
    with pytest.raises(InvalidInputError) as error:
        _create(**overrides)  # type: ignore[arg-type]

    assert error.value.field == field


# Regla: RN-003-06 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_last4` obligatorio, exactamente 4 dígitos `0-9`, sin espacios; `date_from` y `date_to` obligatorias, en formato `AAAA-MM-DD` y existentes en el calendario; `date_from` no posterior a `date_to`; `date_to` no posterior a hoy; el rango no supera **90 días contando ambos extremos** (`date_to − date_from + 1 ≤ 90`). No hay límite hacia el pasado para `date_from`. Toda violación ⇒ `INVALID_INPUT`, sin transacciones.  # noqa: E501
# AC-003-07 · Art. 3
@pytest.mark.parametrize(
    ("date_from", "date_to", "valid"),
    [
        ("2026-09-10", "2026-09-10", True),
        ("2026-06-01", "2026-08-28", True),
        ("2026-06-01", "2026-08-29", True),
        ("2026-06-01", "2026-08-30", False),
        ("2019-01-01", "2019-01-31", True),
    ],
    ids=["1_day", "89_days", "90_days", "91_days", "past_without_limit"],
)
def test_ac_003_07_range_limit_counts_both_ends(date_from: str, date_to: str, valid: bool) -> None:
    """AC-003-07: el rango admite hasta 90 días contando ambos extremos."""
    assert MAX_RANGE_DAYS == 90
    if valid:
        query = _create(date_from=date_from, date_to=date_to)
        assert query.date_range.date_from == date.fromisoformat(date_from)
        assert query.date_range.date_to == date.fromisoformat(date_to)
    else:
        with pytest.raises(InvalidInputError):
            _create(date_from=date_from, date_to=date_to)


# Regla: RN-003-06 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_last4` obligatorio, exactamente 4 dígitos `0-9`, sin espacios; `date_from` y `date_to` obligatorias, en formato `AAAA-MM-DD` y existentes en el calendario; `date_from` no posterior a `date_to`; `date_to` no posterior a hoy; el rango no supera **90 días contando ambos extremos** (`date_to − date_from + 1 ≤ 90`). No hay límite hacia el pasado para `date_from`. Toda violación ⇒ `INVALID_INPUT`, sin transacciones.  # noqa: E501
# Regla: RN-003-07 — "Hoy" es la fecha del reloj inyectado en la zona horaria `America/Bogota` (UTC−05:00), igual que RN-002-08.  # noqa: E501
# AC-003-10 · Art. 3
@pytest.mark.parametrize(
    ("now", "date_to", "valid"),
    [
        (datetime(2026, 10, 17, 15, 0, tzinfo=UTC), "2026-10-17", True),
        (datetime(2026, 10, 18, 3, 0, tzinfo=UTC), "2026-10-17", True),
        (datetime(2026, 10, 18, 3, 0, tzinfo=UTC), "2026-10-18", False),
        (datetime(2026, 10, 18, 5, 0, tzinfo=UTC), "2026-10-18", True),
    ],
    ids=["utc_15h_today", "utc_03h_today", "utc_03h_still_17", "utc_05h_already_18"],
)
def test_ac_003_10_query_date_to_limit_uses_today_in_bogota(
    now: datetime, date_to: str, valid: bool
) -> None:
    """AC-003-10: `date_to` no puede superar la fecha de hoy en Bogotá."""
    today = today_in_bogota(now)
    if valid:
        assert _create(date_from="2026-10-01", date_to=date_to, today=today) is not None
    else:
        with pytest.raises(InvalidInputError):
            _create(date_from="2026-10-01", date_to=date_to, today=today)


# Regla: RN-003-05 — Cada transacción tiene un instante `occurred_at` (fecha y hora con zona). Entra en el rango si su **fecha local en `America/Bogota`** está entre `date_from` y `date_to`, ambos incluidos.  # noqa: E501
# AC-003-02 · Art. 3
@pytest.mark.parametrize(
    ("instant", "inside"),
    [
        (datetime.fromisoformat("2026-09-01T00:00:00-05:00"), True),
        (datetime.fromisoformat("2026-09-30T23:59:59-05:00"), True),
        (datetime.fromisoformat("2026-08-31T23:59:59-05:00"), False),
        (datetime.fromisoformat("2026-10-01T00:00:00-05:00"), False),
        (datetime(2026, 10, 1, 3, 30, tzinfo=UTC), True),
        (datetime(2026, 9, 1, 4, 30, tzinfo=UTC), False),
    ],
    ids=[
        "first_day_start",
        "last_day_end",
        "day_before_end",
        "day_after_start",
        "utc_oct_1_is_sep_30_local",
        "utc_sep_1_is_aug_31_local",
    ],
)
def test_ac_003_02_utc_bounds_follow_bogota_days(instant: datetime, inside: bool) -> None:
    """AC-003-02: los límites UTC `[inicio, fin)` siguen los días de Bogotá."""
    start, end = BogotaDateRange(date(2026, 9, 1), date(2026, 9, 30)).utc_bounds()

    assert start == datetime(2026, 9, 1, 5, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 1, 5, 0, tzinfo=UTC)
    assert (start <= instant < end) is inside


# Soporte de tests: conversation_id se recorta y card_last4 no · Art. 3
def test_conversation_id_is_trimmed_and_card_last4_is_not() -> None:
    """RN-003-06: `conversation_id` se recorta; `card_last4` con espacio es inválido."""
    assert _create(conversation_id="  conv-1 ").conversation_id == "conv-1"
    assert _create(card_last4="4321").card_last4 == "4321"
    with pytest.raises(InvalidInputError):
        _create(card_last4=" 4321")


# Soporte de tests: una fecha de campo inválida se informa antes que el rango · Art. 3
def test_invalid_date_field_is_reported_before_range() -> None:
    """RN-003-06: con `date_from` inválida y `date_to` válida se informa el campo."""
    with pytest.raises(InvalidInputError) as error:
        _create(date_from="2026-02-30", date_to="2026-01-01")

    assert error.value.field == "date_from"
