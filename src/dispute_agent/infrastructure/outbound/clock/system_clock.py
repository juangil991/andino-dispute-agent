"""Reloj del sistema en zona de Bogotá (UTC-5)."""

from datetime import date, datetime, timedelta, timezone

_BOGOTA = timezone(timedelta(hours=-5), "America/Bogota")


class SystemClock:
    """Implementa `Clock`."""

    def now(self) -> datetime:
        return datetime.now(_BOGOTA)

    def today(self) -> date:
        return self.now().date()
