"""Modelos espejo de las salidas de las herramientas del core (specs 001-006 §7, spec 007 §7.1-7.2).

El agente no importa `core_banking_mcp` (Art. 6): estos modelos validan la respuesta con
`extra="forbid"` y la convierten a los DTOs del puerto.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict

from dispute_agent.application.ports.banking_tools import (
    BankingToolUnavailableError,
    CardBlocked,
    CardRef,
    CustomerMatch,
    CustomerSearch,
    DisputeOpened,
    EscalationRegistered,
    TransactionPage,
    VerificationResult,
)
from dispute_agent.domain.errors import InvalidTransactionDataError
from dispute_agent.domain.models.transaction import DisputedTransaction, TransactionStatus


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolErrorEnvelope(_Strict):
    code: str
    message: str
    retryable: bool


class CustomerCardModel(_Strict):
    card_id: str
    masked_card: str


class CustomerMatchModel(_Strict):
    customer_id: str
    full_name: str
    masked_document: str
    masked_cards: list[str]
    cards: list[CustomerCardModel]


class BuscarClienteModel(_Strict):
    customers: list[CustomerMatchModel]
    refinement_required: bool

    def to_dto(self) -> CustomerSearch:
        return CustomerSearch(
            customers=tuple(
                CustomerMatch(
                    customer_id=c.customer_id,
                    cards=tuple(CardRef(x.card_id, x.masked_card) for x in c.cards),
                )
                for c in self.customers
            ),
            refinement_required=self.refinement_required,
        )


class VerificarIdentidadModel(_Strict):
    verified: bool
    attempts_remaining: int
    escalation_required: bool

    def to_dto(self) -> VerificationResult:
        return VerificationResult(
            verified=self.verified,
            attempts_remaining=self.attempts_remaining,
            escalation_required=self.escalation_required,
        )


class TransactionItemModel(_Strict):
    transaction_id: str
    occurred_at: str
    merchant: str
    amount: str
    currency: str
    status: Literal["CONFIRMED", "PENDING", "REVERSED"]
    card_id: str
    masked_card: str
    merchant_country: str

    def to_domain(self) -> DisputedTransaction:
        try:
            return DisputedTransaction(
                transaction_id=self.transaction_id,
                card_id=self.card_id,
                masked_card=self.masked_card,
                occurred_at=datetime.fromisoformat(self.occurred_at),
                merchant=self.merchant,
                amount=Decimal(self.amount),
                currency=self.currency,
                merchant_country=self.merchant_country,
                status=TransactionStatus(self.status),
            )
        except (InvalidTransactionDataError, InvalidOperation, ValueError) as exc:
            raise BankingToolUnavailableError("transacción inválida en la respuesta") from exc


class ConsultarTransaccionesModel(_Strict):
    transactions: list[TransactionItemModel]
    refinement_required: bool

    def to_dto(self) -> TransactionPage:
        return TransactionPage(
            transactions=tuple(t.to_domain() for t in self.transactions),
            refinement_required=self.refinement_required,
        )


def _parse_instant(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise BankingToolUnavailableError("instante inválido en la respuesta") from exc


class IniciarDisputaModel(_Strict):
    dispute_id: str
    status: Literal["OPEN"]
    opened_at: str
    reason: Literal[
        "UNRECOGNIZED_CHARGE", "DUPLICATE_CHARGE", "INCORRECT_AMOUNT", "NOT_RECEIVED", "OTHER"
    ]
    transaction: TransactionItemModel

    def to_dto(self) -> DisputeOpened:
        return DisputeOpened(
            dispute_id=self.dispute_id,
            status=self.status,
            opened_at=_parse_instant(self.opened_at),
            reason=self.reason,
            transaction=self.transaction.to_domain(),
        )


class BloquearTarjetaModel(_Strict):
    card_id: str
    masked_card: str
    status: Literal["BLOCKED"]
    blocked_at: str | None
    reason: Literal["FRAUD_SUSPECTED", "LOST_OR_STOLEN"] | None
    already_blocked: bool

    def to_dto(self) -> CardBlocked:
        return CardBlocked(
            card_id=self.card_id,
            masked_card=self.masked_card,
            status=self.status,
            blocked_at=None if self.blocked_at is None else _parse_instant(self.blocked_at),
            reason=self.reason,
            already_blocked=self.already_blocked,
        )


class EscalationCardModel(_Strict):
    card_id: str
    masked_card: str


class EscalationSummaryModel(_Strict):
    conversation_id: str
    identity_verified: bool
    customer_id: str | None
    transaction: TransactionItemModel | None
    card: EscalationCardModel | None
    prior_actions: list[Literal["DISPUTE_OPENED", "CARD_BLOCKED"]]
    dispute_id: str | None
    note: str | None


class EscalarAnalistaModel(_Strict):
    escalation_id: str
    status: Literal["PENDING"]
    escalated_at: str
    reason: Literal[
        "FRAUD_SUSPECTED",
        "AMOUNT_OVER_THRESHOLD",
        "INSUFFICIENT_OR_CONTRADICTORY_INFO",
        "INCONCLUSIVE_RULES",
        "UNRECOVERABLE_SYSTEM_FAILURE",
        "IDENTITY_VERIFICATION_FAILED",
        "OTHER",
    ]
    summary: EscalationSummaryModel

    def to_dto(self) -> EscalationRegistered:
        return EscalationRegistered(
            escalation_id=self.escalation_id,
            status=self.status,
            escalated_at=_parse_instant(self.escalated_at),
            reason=self.reason,
        )
