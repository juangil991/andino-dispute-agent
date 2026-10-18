"""Tests de soporte de los fakes y builders del agente."""

import asyncio
from datetime import date

import pytest
from tests.fakes.agent_transaction_builder import DisputedTransactionBuilder
from tests.fakes.conversation_builder import ConversationBuilder
from tests.fakes.fake_agent_audit_log import FakeAgentAuditLog
from tests.fakes.fake_banking_tools import FakeBankingTools
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixed_agent_clock import FixedAgentClock
from tests.fakes.sequential_id_generator import SequentialIdGenerator

from dispute_agent.application.ports.audit_log import AgentAuditEvent, AuditLogPort
from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolsPort,
    CustomerSearch,
)
from dispute_agent.application.ports.clock import Clock
from dispute_agent.application.ports.id_generator import IdGenerator
from dispute_agent.application.ports.llm import (
    ChatMessage,
    LLMError,
    LLMPort,
    LLMResponse,
    ToolCall,
)
from dispute_agent.domain.models.conversation import ConversationStatus, KnownCard
from dispute_agent.domain.models.transaction import TransactionStatus


def test_fake_llm_replays_script_and_records_requests() -> None:
    # Soporte de tests: FakeLLM con guion y registro de peticiones · Art. 3
    call = ToolCall(id="c1", name="buscar_cliente", arguments={"a": 1})
    fake = FakeLLM([LLMResponse(text="hola"), LLMResponse(tool_calls=(call,)), LLMError()])
    llm: LLMPort = fake
    msgs = (ChatMessage(role="user", text="hi"),)

    async def run() -> None:
        first = await llm.complete("sys", msgs, ())
        second = await llm.complete("sys2", msgs, ())
        assert first.text == "hola"
        assert second.tool_calls == (call,)
        with pytest.raises(LLMError):
            await llm.complete("s", msgs, ())
        with pytest.raises(AssertionError):
            await llm.complete("s", msgs, ())

    asyncio.run(run())
    assert [r.system for r in fake.requests] == ["sys", "sys2", "s", "s"]
    assert fake.requests[0].messages == msgs


def test_fake_banking_tools_replays_errors_and_records_calls() -> None:
    # Soporte de tests: FakeBankingTools programable · Art. 3
    err = BankingToolError("NOT_FOUND", "x", retryable=False)
    tools = FakeBankingTools()
    tools.respond("search_customer", CustomerSearch((), False))
    tools.respond("verify_identity", err)
    port: BankingToolsPort = tools

    async def run() -> None:
        result = await port.search_customer("c1", document="1")
        assert result == CustomerSearch((), False)
        with pytest.raises(BankingToolError):
            await port.verify_identity("c1", "C-1", date(1990, 1, 1), date(2010, 1, 1))
        with pytest.raises(AssertionError):
            await port.block_card("c1", "K", "FRAUD_SUSPECTED", "k")

    asyncio.run(run())
    assert [name for name, _ in tools.calls[:2]] == ["search_customer", "verify_identity"]
    assert tools.calls[0][1]["document"] == "1"


def test_agent_builders_produce_valid_defaults() -> None:
    # Soporte de tests: builders con valores válidos · Art. 3
    today = date(2026, 3, 22)
    tx = (
        DisputedTransactionBuilder().national().amount("85000.00", "COP").days_ago(7, today).build()
    )
    assert tx.merchant_country == "CO"
    assert (today - tx.occurred_at.date()).days == 7
    foreign = (
        DisputedTransactionBuilder()
        .foreign()
        .status(TransactionStatus.PENDING)
        .card("K-9", "**** 9999")
        .merchant("X")
        .transaction_id("T-9")
        .build()
    )
    assert foreign.merchant_country == "US"
    assert foreign.status is TransactionStatus.PENDING

    cards = (KnownCard("K-0001", "1234"),)
    verified = ConversationBuilder().verified("C-0001", cards=cards).with_documents("d").build()
    assert verified.verified_customer_id == "C-0001"
    assert verified.known_cards == cards
    assert verified.provided_documents == {"d"}
    located = ConversationBuilder().located("C-0001", cards=cards).build()
    assert located.verified_customer_id is None
    assert ConversationBuilder().closed().build().status is ConversationStatus.ESCALATED


def test_fixed_clock_ids_and_audit_log_are_deterministic() -> None:
    # Soporte de tests: reloj, ids y auditoría deterministas · Art. 3
    clock: Clock = FixedAgentClock()
    assert clock.now() == clock.now()
    assert clock.today() == date(2026, 3, 22)
    ids: IdGenerator = SequentialIdGenerator()
    assert [ids.new_conversation_id(), ids.new_conversation_id()] == ["conv-0001", "conv-0002"]
    fake_log = FakeAgentAuditLog()
    log: AuditLogPort = fake_log
    event = AgentAuditEvent("c", clock.now(), "decision", rule="R")
    log.record(event)
    assert fake_log.events == [event]
