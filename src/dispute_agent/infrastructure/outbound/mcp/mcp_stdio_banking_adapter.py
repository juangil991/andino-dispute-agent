"""Adaptador MCP por stdio hacia el core: validación, tiempo límite y reintento (mcp-client.md)."""

import asyncio
import json
import re
from contextlib import AsyncExitStack
from datetime import date
from typing import Any, TypeVar

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ValidationError

from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolUnavailableError,
    CardBlocked,
    CustomerSearch,
    DisputeOpened,
    EscalationRegistered,
    TransactionPage,
    VerificationResult,
)
from dispute_agent.domain.models.decision import EscalationReason, PriorAction
from dispute_agent.infrastructure.outbound.mcp.response_models import (
    BloquearTarjetaModel,
    BuscarClienteModel,
    ConsultarTransaccionesModel,
    EscalarAnalistaModel,
    IniciarDisputaModel,
    ToolErrorEnvelope,
    VerificarIdentidadModel,
)

M = TypeVar("M", bound=BaseModel)

_MAX_ATTEMPTS = 2  # una llamada y, como máximo, un reintento si retryable=true
_ALREADY_OPEN_ID = re.compile(r":\s*(\S+?)\.?\s*$")


class McpStdioBankingAdapter:
    """Implementa `BankingToolsPort` sobre un servidor MCP lanzado como subproceso stdio.

    `open()` y `close()` deben ejecutarse en la misma tarea asyncio (cancel scopes de anyio).
    """

    def __init__(
        self,
        command: str,
        args: list[str],
        env: dict[str, str] | None,
        call_timeout_seconds: float,
        startup_timeout_seconds: float = 30.0,
    ) -> None:
        self._params = StdioServerParameters(command=command, args=args, env=env)
        self._timeout = call_timeout_seconds
        self._startup_timeout = startup_timeout_seconds
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    @staticmethod
    async def _aclose(stack: AsyncExitStack) -> None:
        try:
            await stack.aclose()
        except BaseExceptionGroup as group:
            # Carrera del cliente MCP al cerrar: una respuesta tardía llega con el flujo ya
            # cerrado. Es inocua; cualquier otro error se propaga.
            _, rest = group.split(anyio.BrokenResourceError)
            if rest is not None:
                raise rest from None

    async def open(self) -> None:
        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(self._params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(session.initialize(), self._startup_timeout)
        except BaseException as exc:
            await self._aclose(stack)
            if isinstance(exc, Exception):
                raise BankingToolUnavailableError("no se pudo iniciar el cliente MCP") from exc
            raise
        self._stack = stack
        self._session = session

    async def close(self) -> None:
        stack, self._stack, self._session = self._stack, None, None
        if stack is not None:
            await self._aclose(stack)

    async def __aenter__(self) -> "McpStdioBankingAdapter":
        await self.open()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    # --- llamada genérica -------------------------------------------------------------------

    async def _call(self, tool: str, arguments: dict[str, Any], model: type[M]) -> M:
        session = self._session
        if session is None:
            raise BankingToolUnavailableError("el cliente MCP no está abierto")
        last_error: BankingToolError | None = None
        for _ in range(_MAX_ATTEMPTS):
            try:
                result = await asyncio.wait_for(
                    session.call_tool(tool, arguments),
                    self._timeout,
                )
            except Exception as exc:  # tiempo límite o fallo de transporte
                raise BankingToolUnavailableError(f"{tool}: sin respuesta del core") from exc
            if not result.isError:
                return self._validate(tool, result, model)
            last_error = self._to_tool_error(tool, result)
            if not last_error.retryable:
                break
        assert last_error is not None
        raise last_error

    @staticmethod
    def _payload(result: CallToolResult) -> object:
        if result.structuredContent is not None:
            return result.structuredContent
        for block in result.content:
            if isinstance(block, TextContent):
                try:
                    return json.loads(block.text)
                except ValueError:
                    return None
        return None

    def _validate(self, tool: str, result: CallToolResult, model: type[M]) -> M:
        try:
            return model.model_validate(self._payload(result))
        except ValidationError as exc:
            raise BankingToolUnavailableError(
                f"{tool}: respuesta que no cumple el esquema"
            ) from exc

    def _to_tool_error(self, tool: str, result: CallToolResult) -> BankingToolError:
        try:
            envelope = ToolErrorEnvelope.model_validate(self._payload(result))
        except ValidationError as exc:
            raise BankingToolUnavailableError(f"{tool}: error sin el sobre esperado") from exc
        existing: str | None = None
        if envelope.code == "DISPUTE_ALREADY_OPEN":
            match = _ALREADY_OPEN_ID.search(envelope.message)
            existing = match.group(1) if match else None
        return BankingToolError(
            envelope.code, envelope.message, envelope.retryable, existing_dispute_id=existing
        )

    # --- BankingToolsPort -------------------------------------------------------------------

    async def search_customer(
        self,
        conversation_id: str,
        document: str | None = None,
        full_name: str | None = None,
        card_last4: str | None = None,
    ) -> CustomerSearch:
        args: dict[str, Any] = {"conversation_id": conversation_id}
        for key, value in (
            ("document", document),
            ("full_name", full_name),
            ("card_last4", card_last4),
        ):
            if value is not None:
                args[key] = value
        return (await self._call("buscar_cliente", args, BuscarClienteModel)).to_dto()

    async def verify_identity(
        self,
        conversation_id: str,
        customer_id: str,
        birth_date: date,
        document_issue_date: date,
    ) -> VerificationResult:
        args = {
            "conversation_id": conversation_id,
            "customer_id": customer_id,
            "birth_date": birth_date.isoformat(),
            "document_issue_date": document_issue_date.isoformat(),
        }
        return (await self._call("verificar_identidad", args, VerificarIdentidadModel)).to_dto()

    async def list_transactions(
        self,
        conversation_id: str,
        card_last4: str,
        date_from: date,
        date_to: date,
    ) -> TransactionPage:
        args = {
            "conversation_id": conversation_id,
            "card_last4": card_last4,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        }
        return (
            await self._call("consultar_transacciones", args, ConsultarTransaccionesModel)
        ).to_dto()

    async def open_dispute(
        self,
        conversation_id: str,
        transaction_id: str,
        reason: str,
        idempotency_key: str,
    ) -> DisputeOpened:
        args = {
            "conversation_id": conversation_id,
            "transaction_id": transaction_id,
            "reason": reason,
            "idempotency_key": idempotency_key,
        }
        return (await self._call("iniciar_disputa", args, IniciarDisputaModel)).to_dto()

    async def block_card(
        self,
        conversation_id: str,
        card_id: str,
        reason: str,
        idempotency_key: str,
    ) -> CardBlocked:
        args = {
            "conversation_id": conversation_id,
            "card_id": card_id,
            "reason": reason,
            "idempotency_key": idempotency_key,
        }
        return (await self._call("bloquear_tarjeta", args, BloquearTarjetaModel)).to_dto()

    async def escalate(
        self,
        conversation_id: str,
        reason: EscalationReason,
        idempotency_key: str,
        transaction_id: str | None = None,
        card_id: str | None = None,
        prior_actions: tuple[PriorAction, ...] = (),
        dispute_id: str | None = None,
        note: str | None = None,
    ) -> EscalationRegistered:
        args: dict[str, Any] = {
            "conversation_id": conversation_id,
            "reason": reason.value,
            "idempotency_key": idempotency_key,
        }
        if transaction_id is not None:
            args["transaction_id"] = transaction_id
        if card_id is not None:
            args["card_id"] = card_id
        if prior_actions:
            args["prior_actions"] = [a.value for a in prior_actions]
        if dispute_id is not None:
            args["dispute_id"] = dispute_id
        if note is not None:
            args["note"] = note
        return (await self._call("escalar_a_analista", args, EscalarAnalistaModel)).to_dto()
