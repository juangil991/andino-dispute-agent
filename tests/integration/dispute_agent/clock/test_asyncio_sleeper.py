import asyncio

import pytest

from dispute_agent.application.ports.sleeper import Sleeper
from dispute_agent.infrastructure.outbound.clock.asyncio_sleeper import AsyncioSleeper


# Regla: RN-009-09 — la inactividad del LLM se mide con una espera real y cancelable.
# AC-009-10 · Art. 10 (ante la duda, escalar)
async def test_asyncio_sleeper__short_sleep__waits_and_is_cancellable() -> None:
    """AC-009-10: AsyncioSleeper espera de verdad y propaga CancelledError al cancelarse."""
    sleeper: Sleeper = AsyncioSleeper()

    await sleeper.sleep(0.01)

    pending = asyncio.ensure_future(sleeper.sleep(10))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
