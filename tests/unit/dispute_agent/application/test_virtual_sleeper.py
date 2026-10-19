"""Tests del `VirtualSleeper` (tiempo virtual determinista para esperas asíncronas)."""

import asyncio
import time

from tests.fakes.virtual_sleeper import VirtualSleeper


# Regla: soporte de pruebas — el reloj virtual resuelve esperas concurrentes por vencimiento.
# Soporte de tests · Art. 3
async def test_virtual_sleeper__concurrent_sleeps__resolve_in_deadline_order() -> None:
    """Esperas de 29 s y 30 s se resuelven por vencimiento sin espera real."""
    sleeper = VirtualSleeper()
    resolved: list[tuple[float, float]] = []

    async def wait(seconds: float) -> None:
        await sleeper.sleep(seconds)
        resolved.append((seconds, sleeper.now))

    started = time.monotonic()
    await asyncio.gather(wait(30), wait(29))
    elapsed = time.monotonic() - started

    assert resolved == [(29, 29.0), (30, 30.0)]
    assert sleeper.now == 30.0
    assert elapsed < 1.0


# Regla: soporte de pruebas — una espera cancelada no avanza el reloj virtual.
# Soporte de tests · Art. 3
async def test_virtual_sleeper__cancelled_sleep__does_not_advance_time() -> None:
    """Una espera cancelada no avanza el tiempo virtual."""
    sleeper = VirtualSleeper()
    cancelled = asyncio.create_task(sleeper.sleep(100))
    await asyncio.sleep(0)
    cancelled.cancel()

    await sleeper.sleep(5)

    assert cancelled.cancelled()
    assert sleeper.now == 5.0
