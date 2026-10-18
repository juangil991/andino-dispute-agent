"""Reloj fijo del agente (zona de Bogotá)."""

from datetime import date, datetime, timedelta, timezone

_BOGOTA = timezone(timedelta(hours=-5))


class FixedAgentClock:
    def __init__(self, instant: datetime | None = None) -> None:
        self._instant = instant or datetime(2026, 3, 22, 10, 0, tzinfo=_BOGOTA)

    def now(self) -> datetime:
        return self._instant

    def today(self) -> date:
        return self._instant.astimezone(_BOGOTA).date()
