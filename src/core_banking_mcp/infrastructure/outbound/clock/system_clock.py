"""Adaptador de salida: reloj del sistema."""

from datetime import UTC, datetime


class SystemClock:
    """Implementa el puerto `Clock` con la hora real en UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)
