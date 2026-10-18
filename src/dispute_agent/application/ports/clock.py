"""Puerto del reloj (fecha de hoy en zona de Bogotá)."""

from datetime import date, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...
