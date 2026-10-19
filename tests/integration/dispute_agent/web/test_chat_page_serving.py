"""Tests del servicio de la página de chat por la app `dispute_agent`.

Spec 008: AC-008-25.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock

from dispute_agent.application.ports.banking_tools import (
    CardRef,
    CustomerMatch,
    CustomerSearch,
    VerificationResult,
)
from dispute_agent.application.ports.llm import LLMResponse, ToolCall
from dispute_agent.config import AgentSettings
from dispute_agent.main import create_app

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)


# Regla: RN-008-02 — El agente sirve la página en `GET /`, con sus recursos estáticos
# (HTML, CSS, JS), desde la misma aplicación `dispute_agent`.
# AC-008-25 · Art. 4
def test_ac_008_25_chat_page__get_root_and_static__served_by_agent_app() -> None:
    """AC-008-25: GET / y /static/* los sirve la app; POST /api/chat sigue respondiendo."""
    # La cliente queda verificada en el propio turno (RN-007-39).
    banking = (
        FakeBankingTools()
        .respond(
            "search_customer",
            CustomerSearch((CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 4321"),)),), False),
        )
        .respond("verify_identity", VerificationResult(True, 3, False))
    )
    verify = LLMResponse(
        tool_calls=(
            ToolCall("v1", "buscar_cliente", {"document": "D-1001"}),
            ToolCall(
                "v2",
                "verificar_identidad",
                {"birth_date": "1990-01-01", "document_issue_date": "2010-01-01"},
            ),
        )
    )
    app = create_app(
        AgentSettings(_env_file=None),  # type: ignore[call-arg]
        banking=banking,
        llm=FakeLLM([verify, LLMResponse(text="Hola")]),
        clock=FixedAgentClock(_NOW),
    )
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert "/static/chat.js" in page.text
        assert "/static/styles.css" in page.text

        assert client.get("/static/chat.js").status_code == 200
        assert client.get("/static/styles.css").status_code == 200

        chat = client.post("/api/chat", json={"message": "hola"})
        assert chat.status_code == 200
        assert chat.json()["reply"] == "Hola"
