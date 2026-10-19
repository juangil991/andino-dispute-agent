"""Sleeper de tiempo virtual: resuelve las esperas por vencimiento sin esperar de verdad."""

import asyncio
import heapq

_IDLE_YIELDS = 10


class VirtualSleeper:
    """Cuando las demás tareas están bloqueadas, adelanta `now` a la espera más próxima."""

    def __init__(self) -> None:
        self.now: float = 0.0
        self._pending: list[tuple[float, int, asyncio.Future[None]]] = []
        self._counter = 0
        self._driver: asyncio.Task[None] | None = None

    async def sleep(self, seconds: float) -> None:
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._counter += 1
        heapq.heappush(self._pending, (self.now + seconds, self._counter, future))
        if self._driver is None or self._driver.done():
            self._driver = asyncio.get_running_loop().create_task(self._drive())
        await future

    async def _drive(self) -> None:
        while True:
            for _ in range(_IDLE_YIELDS):
                await asyncio.sleep(0)
            while self._pending and self._pending[0][2].done():
                heapq.heappop(self._pending)
            if not self._pending:
                return
            deadline, _, future = heapq.heappop(self._pending)
            self.now = max(self.now, deadline)
            future.set_result(None)
