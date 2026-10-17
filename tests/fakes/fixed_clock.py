"""Reloj fijo para tests deterministas."""

from datetime import UTC, datetime


class FixedClock:
    def __init__(self, instant: datetime | None = None) -> None:
        self._instant = instant or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._instant
