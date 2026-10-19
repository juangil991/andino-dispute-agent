"""Guion de streaming de FakeLLM (soporte de tests de la spec 009)."""

import asyncio

import pytest
from tests.fakes.fake_llm import HANG, FakeLLM
from tests.fakes.virtual_sleeper import VirtualSleeper

from dispute_agent.application.ports.llm import (
    ChatMessage,
    LLMError,
    LLMStreamEnd,
    LLMTextDelta,
    ToolCall,
)

_MESSAGES = (ChatMessage(role="user", text="hola"),)


async def _collect(llm: FakeLLM) -> list[LLMTextDelta | LLMStreamEnd]:
    return [item async for item in llm.stream("sys", _MESSAGES)]


# Regla: soporte de pruebas — FakeLLM.stream entrega los trozos guionizados, luego el fin, con
# demoras medidas en un reloj virtual inyectado.
# Soporte de tests · Art. 3
def test_fake_llm_stream__scripted_chunks__yields_deltas_then_end_with_virtual_delays() -> None:
    """Trozos guionizados, luego fin, con tiempo virtual 3."""
    sleeper = VirtualSleeper()
    end = LLMStreamEnd("end_turn", ())
    llm = FakeLLM([], stream_script=[([(1, "Hola "), (2, "Ana.")], end)], sleeper=sleeper)

    items = asyncio.run(_collect(llm))

    assert items == [LLMTextDelta("Hola "), LLMTextDelta("Ana."), end]
    assert sleeper.now == 3
    assert llm.stream_requests[0].system == "sys"
    assert llm.stream_requests[0].messages == _MESSAGES


# Regla: soporte de pruebas — el fin del stream guionizado puede traer tool_calls y cualquier
# razón de parada.
# Soporte de tests · Art. 3
def test_fake_llm_stream__end_with_tool_calls_and_other_stop_reason__is_delivered() -> None:
    """El fin conserva tool_calls y stop_reason arbitrarios."""
    call = ToolCall("t1", "buscar_cliente", {})
    end = LLMStreamEnd("max_tokens", (call,))
    llm = FakeLLM([], stream_script=[([], end)], sleeper=VirtualSleeper())

    assert asyncio.run(_collect(llm)) == [end]


# Regla: soporte de pruebas — el fake lanza un LLMError guionizado tras los trozos ya emitidos.
# Soporte de tests · Art. 3
def test_fake_llm_stream__llm_error_end__raises_after_chunks() -> None:
    """LLMError se lanza tras los trozos."""
    llm = FakeLLM([], stream_script=[([(1, "Hola")], LLMError("boom"))], sleeper=VirtualSleeper())
    received: list[LLMTextDelta | LLMStreamEnd] = []

    async def run() -> None:
        async for item in llm.stream("sys", _MESSAGES):
            received.append(item)

    with pytest.raises(LLMError):
        asyncio.run(run())
    assert received == [LLMTextDelta("Hola")]


# Regla: soporte de pruebas — el fin HANG del fake no termina nunca tras los trozos.
# Soporte de tests · Art. 3
def test_fake_llm_stream__hang_end__never_finishes() -> None:
    """HANG no termina nunca tras los trozos."""
    llm = FakeLLM([], stream_script=[([(1, "Hola")], HANG)], sleeper=VirtualSleeper())

    async def run() -> None:
        await asyncio.wait_for(_collect(llm), timeout=0.2)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(run())


# Regla: soporte de pruebas — sin guion de streaming, el fake falla de forma explícita.
# Soporte de tests · Art. 3
def test_fake_llm_stream__script_exhausted__raises_assertion() -> None:
    """Sin guion de streaming se lanza AssertionError."""
    llm = FakeLLM([])

    with pytest.raises(AssertionError, match="guion de streaming agotado"):
        asyncio.run(_collect(llm))
