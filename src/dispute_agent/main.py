"""Composición de `dispute_agent`: configuración, adaptadores, caso de uso y API HTTP."""

import sys
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from dispute_agent.application.ports.banking_tools import BankingToolsPort
from dispute_agent.application.ports.clock import Clock
from dispute_agent.application.ports.llm import ChatMessage, LLMPort, LLMResponse, ToolSpec
from dispute_agent.application.redacting_audit_log import RedactingAuditLog
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.application.use_cases.handle_customer_message import HandleCustomerMessage
from dispute_agent.config import AgentSettings
from dispute_agent.domain.policies.dispute_policy import DisputePolicy
from dispute_agent.infrastructure.inbound.web.api.chat_router import build_chat_router
from dispute_agent.infrastructure.outbound.audit.json_audit_log import JsonAuditLog
from dispute_agent.infrastructure.outbound.clock.system_clock import SystemClock
from dispute_agent.infrastructure.outbound.ids.uuid_generator import Uuid4Generator
from dispute_agent.infrastructure.outbound.llm.anthropic_llm_adapter import AnthropicLLMAdapter
from dispute_agent.infrastructure.outbound.mcp.mcp_stdio_banking_adapter import (
    McpStdioBankingAdapter,
)
from dispute_agent.infrastructure.outbound.persistence.in_memory_conversation_repository import (
    InMemoryConversationRepository,
)


class _LazyAnthropicLLM:
    """Crea el adaptador de Anthropic en la primera llamada (la app arranca sin clave)."""

    def __init__(self, settings: AgentSettings) -> None:
        self._settings = settings
        self._adapter: AnthropicLLMAdapter | None = None

    async def complete(
        self,
        system: str,
        messages: tuple[ChatMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> LLMResponse:
        if self._adapter is None:
            self._adapter = AnthropicLLMAdapter(
                api_key=self._settings.anthropic_api_key.get_secret_value(),
                model=self._settings.anthropic_model,
            )
        return await self._adapter.complete(system, messages, tools)


def create_app(
    settings: AgentSettings | None = None,
    banking: BankingToolsPort | None = None,
    llm: LLMPort | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    settings = settings or AgentSettings()
    owned_banking: McpStdioBankingAdapter | None = None
    if banking is None:
        owned_banking = McpStdioBankingAdapter(
            command=sys.executable,
            args=["-m", "core_banking_mcp.server"],
            env={
                "CORE_DATABASE_URL": settings.core_database_url,
                "CORE_SEED_ON_START": str(settings.core_seed_on_start),
            },
            call_timeout_seconds=settings.mcp_call_timeout_seconds,
        )
        banking = owned_banking
    llm = llm if llm is not None else _LazyAnthropicLLM(settings)
    clock = clock if clock is not None else SystemClock()
    repo = InMemoryConversationRepository()

    def documents_for(conversation_id: str) -> Iterable[str]:
        conv = repo.get(conversation_id)
        return () if conv is None else tuple(conv.provided_documents)

    audit = RedactingAuditLog(JsonAuditLog(), documents_for=documents_for)
    escalation = EscalationService(banking, audit, clock)
    dispute_actions = DisputeActions(
        DisputePolicy(settings.usd_cop_rate), banking, escalation, audit, clock
    )
    fraud_actions = FraudActions(banking, dispute_actions, escalation, audit, clock)
    handle_message = HandleCustomerMessage(
        llm,
        banking,
        repo,
        dispute_actions,
        fraud_actions,
        escalation,
        audit,
        clock,
        Uuid4Generator(),
        settings.llm_max_iterations,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if owned_banking is None:
            yield
            return
        await owned_banking.open()
        try:
            yield
        finally:
            await owned_banking.close()

    app = FastAPI(title="dispute_agent", lifespan=lifespan)
    app.include_router(build_chat_router(handle_message))
    return app


def main() -> None:
    uvicorn.run("dispute_agent.main:create_app", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
