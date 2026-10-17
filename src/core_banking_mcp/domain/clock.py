"""Conversión de instantes a la fecha local de America/Bogota (RN-002-08)."""

from datetime import date, datetime, timedelta, timezone

_BOGOTA = timezone(timedelta(hours=-5))


def today_in_bogota(now: datetime) -> date:
    """Devuelve la fecha de `now` en America/Bogota (UTC-5, sin horario de verano)."""
    return now.astimezone(_BOGOTA).date()
