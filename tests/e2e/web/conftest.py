"""Arnés de pruebas de navegador: servidor ASGI real en un hilo (spec 008)."""

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from tests.fakes.chat_stream_script import ChatStreamScript
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock

from dispute_agent.config import AgentSettings
from dispute_agent.main import create_app

_HERE = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Marca `browser` y ejecuta las pruebas de navegador al final de la sesión.

    El Playwright síncrono de sesión deja un event loop corriendo en el hilo principal hasta el
    cierre de la sesión; ejecutarlo al final evita romper a pytest-asyncio en el resto de tests.
    """
    browser_items = []
    for item in items:
        if _HERE in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.browser)
            browser_items.append(item)
    rest = [item for item in items if item not in browser_items]
    items[:] = rest + browser_items


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def _stream_script_session() -> ChatStreamScript:
    app = create_app(
        AgentSettings(_env_file=None),  # type: ignore[call-arg]
        banking=FakeBankingTools(),
        llm=FakeLLM([]),
        clock=FixedAgentClock(),
    )
    return ChatStreamScript(app)


@pytest.fixture
def chat_stream_script(_stream_script_session: ChatStreamScript) -> Iterator[ChatStreamScript]:
    """Guion de /api/chat/stream del servidor en vivo, limpio por prueba."""
    _stream_script_session.reset()
    yield _stream_script_session
    _stream_script_session.reset()


@pytest.fixture(scope="session")
def live_server_url(_stream_script_session: ChatStreamScript) -> Iterator[str]:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(_stream_script_session, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("El servidor de la página no arrancó")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict[str, object]) -> dict[str, object]:
    """Falla con instrucciones claras (sin skip) si Chromium no está instalado."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).exists():
            pytest.fail(
                "Chromium no está instalado: ejecuta `uv run playwright install chromium`",
                pytrace=False,
            )
    return browser_type_launch_args
