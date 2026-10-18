"""Puerto hacia las herramientas MCP de core banking (DTOs sin PII del cliente)."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from dispute_agent.domain.models.decision import EscalationReason, PriorAction
from dispute_agent.domain.models.transaction import DisputedTransaction


class BankingToolError(Exception):
    """Error de negocio devuelto por una herramienta del core."""

    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool,
        existing_dispute_id: str | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable
        self.existing_dispute_id = existing_dispute_id


class BankingToolUnavailableError(Exception):
    """El core no responde o devolvió una respuesta inválida tras los reintentos."""


@dataclass(frozen=True)
class CardRef:
    card_id: str
    masked_card: str


@dataclass(frozen=True)
class CustomerMatch:
    customer_id: str
    cards: tuple[CardRef, ...]


@dataclass(frozen=True)
class CustomerSearch:
    customers: tuple[CustomerMatch, ...]
    refinement_required: bool


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    attempts_remaining: int
    escalation_required: bool


@dataclass(frozen=True)
class TransactionPage:
    transactions: tuple[DisputedTransaction, ...]
    refinement_required: bool


@dataclass(frozen=True)
class DisputeOpened:
    dispute_id: str
    status: str
    opened_at: datetime
    reason: str
    transaction: DisputedTransaction


@dataclass(frozen=True)
class CardBlocked:
    card_id: str
    masked_card: str
    status: str
    blocked_at: datetime | None
    reason: str | None
    already_blocked: bool


@dataclass(frozen=True)
class EscalationRegistered:
    escalation_id: str
    status: str
    escalated_at: datetime
    reason: str


class BankingToolsPort(Protocol):
    async def search_customer(
        self,
        conversation_id: str,
        document: str | None = None,
        full_name: str | None = None,
        card_last4: str | None = None,
    ) -> CustomerSearch: ...

    async def verify_identity(
        self,
        conversation_id: str,
        customer_id: str,
        birth_date: date,
        document_issue_date: date,
    ) -> VerificationResult: ...

    async def list_transactions(
        self,
        conversation_id: str,
        card_last4: str,
        date_from: date,
        date_to: date,
    ) -> TransactionPage: ...

    async def open_dispute(
        self,
        conversation_id: str,
        transaction_id: str,
        reason: str,
        idempotency_key: str,
    ) -> DisputeOpened: ...

    async def block_card(
        self,
        conversation_id: str,
        card_id: str,
        reason: str,
        idempotency_key: str,
    ) -> CardBlocked: ...

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
    ) -> EscalationRegistered: ...
