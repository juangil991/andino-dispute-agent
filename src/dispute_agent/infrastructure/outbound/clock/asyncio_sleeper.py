"""Espera asíncrona real basada en `asyncio.sleep`."""

import asyncio


class AsyncioSleeper:
    """Implementa `Sleeper`."""

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
