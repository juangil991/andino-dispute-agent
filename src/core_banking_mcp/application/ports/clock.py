"""Puerto de salida: reloj inyectable."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Instante actual (UTC)."""
        ...
