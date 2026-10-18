"""Tests de `AgentSettings` y su cableado en `create_app`.

Spec 007: AC-007-04 (configuración) y valores por defecto del plan.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock

from dispute_agent.application.ports.banking_tools import (
    CardRef,
    CustomerMatch,
    CustomerSearch,
    EscalationRegistered,
    TransactionPage,
    VerificationResult,
)
from dispute_agent.application.ports.llm import LLMResponse, ToolCall
from dispute_agent.config import AgentSettings
from dispute_agent.domain import messages
from dispute_agent.main import create_app

_NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_TODAY = date(2026, 10, 17)
_ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "LLM_MAX_ITERATIONS",
    "USD_COP_RATE",
    "MCP_CALL_TIMEOUT_SECONDS",
    "CORE_DATABASE_URL",
    "CORE_SEED_ON_START",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _settings() -> AgentSettings:
    return AgentSettings(_env_file=None)  # type: ignore[call-arg]


def _call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def _tools(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(tool_calls=tuple(calls))


# Regla: RN-007-09 — **Monto equivalente en COP**: si `currency = "COP"`, el monto tal cual. Si
# `currency = "USD"`, `amount × tasa USD`, con la tasa configurable y por defecto **4.000 COP por
# USD**. Con cualquier otra moneda no hay equivalente (DP-007-02). El **umbral** es **500.000
# COP**: el monto equivalente debe ser **≤ 500.000** para resolver automáticamente.
# AC-007-04 · Art. 5
def test_ac_007_04_agent_settings__usd_rate_from_env__escalates_over_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-007-04: USD_COP_RATE=5000 y 100.01 USD nacional -> ESCALATE por DP-007-03."""
    monkeypatch.setenv("USD_COP_RATE", "5000")
    settings = _settings()
    assert settings.usd_cop_rate == Decimal(5000)

    tx = (
        DisputedTransactionBuilder()
        .transaction_id("TX-L1")
        .card("CARD-L1", "**** 4321")
        .amount("100.01", "USD")
        .days_ago(7, _TODAY)
        .national()
        .build()
    )
    banking = (
        FakeBankingTools()
        .respond(
            "search_customer",
            CustomerSearch((CustomerMatch("C-0001", (CardRef("CARD-L1", "**** 4321"),)),), False),
        )
        .respond("verify_identity", VerificationResult(True, 3, False))
        .respond("list_transactions", TransactionPage((tx,), False))
        .respond(
            "escalate",
            EscalationRegistered("E-0001", "PENDING", _NOW, "AMOUNT_OVER_THRESHOLD"),
        )
    )
    llm = FakeLLM(
        [
            _tools(_call("c1", "buscar_cliente", document="D-1001")),
            _tools(
                _call(
                    "c2",
                    "verificar_identidad",
                    birth_date="1990-01-01",
                    document_issue_date="2010-01-01",
                )
            ),
            _tools(
                _call(
                    "c3",
                    "consultar_transacciones",
                    card_last4="4321",
                    date_from="2026-09-01",
                    date_to="2026-10-17",
                )
            ),
            _tools(_call("c4", "evaluar_disputa", transaction_id="TX-L1")),
            LLMResponse(text="Tu caso fue derivado."),
        ]
    )
    app = create_app(settings, banking=banking, llm=llm, clock=FixedAgentClock(_NOW))
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "No reconozco el cobro TX-L1"})

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ACTIVE"
    assert [(o["kind"], o["rule"], o["transaction_id"]) for o in body["outcomes"]] == [
        ("ESCALATED", "DP-007-03", "TX-L1")
    ]
    assert body["outcomes"][0]["reason"] == messages.DP_REASONS["DP-007-03"]
    assert not [name for name, _ in banking.calls if name == "open_dispute"]


# Soporte de tests: valores por defecto de la configuración (plan §2) · Art. 3
def test_agent_settings__no_env__defaults_and_secret_key() -> None:
    settings = _settings()
    assert settings.anthropic_model == "claude-sonnet-5-5"
    assert settings.llm_max_iterations == 8
    assert settings.usd_cop_rate == Decimal(4000)
    assert settings.mcp_call_timeout_seconds == 10
    assert settings.core_database_url == "sqlite:///./data/core_banking.db"
    assert settings.core_seed_on_start is True
    assert settings.anthropic_api_key.get_secret_value() == ""


# Soporte de tests: ANTHROPIC_API_KEY es SecretStr y las variables CORE_* se leen del
# entorno · Art. 3
def test_agent_settings__env_set__values_loaded_and_key_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-ficticia-123")
    monkeypatch.setenv("CORE_DATABASE_URL", "sqlite:///./otra.db")
    monkeypatch.setenv("CORE_SEED_ON_START", "false")
    settings = _settings()
    assert settings.anthropic_api_key.get_secret_value() == "clave-ficticia-123"
    assert "clave-ficticia-123" not in repr(settings)
    assert settings.core_database_url == "sqlite:///./otra.db"
    assert settings.core_seed_on_start is False


# Soporte de tests: la app se crea sin clave ni `banking`/`llm` inyectados; el subproceso MCP
# no se abre hasta el lifespan · Art. 3
def test_create_app__without_key_or_injections__builds_app() -> None:
    app = create_app(_settings())
    assert "/api/chat" in app.openapi()["paths"]
