"""Puerto de espera asíncrona (inactividad de la redacción en streaming)."""

from typing import Protocol


class Sleeper(Protocol):
    async def sleep(self, seconds: float) -> None: ...
