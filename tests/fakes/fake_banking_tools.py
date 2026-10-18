"""Herramientas de banca falsas: respuestas o errores programados por herramienta."""

from datetime import date
from typing import Any, cast

from dispute_agent.application.ports.banking_tools import (
    CardBlocked,
    CustomerSearch,
    DisputeOpened,
    EscalationRegistered,
    TransactionPage,
    VerificationResult,
)
from dispute_agent.domain.models.decision import EscalationReason, PriorAction


class FakeBankingTools:
    def __init__(self) -> None:
        self._programmed: dict[str, list[object]] = {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def respond(self, tool: str, *outcomes: object) -> "FakeBankingTools":
        """Programa respuestas o excepciones; se consumen en orden y la última se repite."""
        self._programmed[tool] = list(outcomes)
        return self

    def _call(self, tool: str, arguments: dict[str, object]) -> Any:
        self.calls.append((tool, arguments))
        queue = self._programmed.get(tool)
        if not queue:
            raise AssertionError(f"FakeBankingTools: sin respuesta programada para {tool}")
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def search_customer(
        self,
        conversation_id: str,
        document: str | None = None,
        full_name: str | None = None,
        card_last4: str | None = None,
    ) -> CustomerSearch:
        return cast(
            CustomerSearch,
            self._call(
                "search_customer",
                {
                    "conversation_id": conversation_id,
                    "document": document,
                    "full_name": full_name,
                    "card_last4": card_last4,
                },
            ),
        )

    async def verify_identity(
        self,
        conversation_id: str,
        customer_id: str,
        birth_date: date,
        document_issue_date: date,
    ) -> VerificationResult:
        return cast(
            VerificationResult,
            self._call(
                "verify_identity",
                {
                    "conversation_id": conversation_id,
                    "customer_id": customer_id,
                    "birth_date": birth_date,
                    "document_issue_date": document_issue_date,
                },
            ),
        )

    async def list_transactions(
        self,
        conversation_id: str,
        card_last4: str,
        date_from: date,
        date_to: date,
    ) -> TransactionPage:
        return cast(
            TransactionPage,
            self._call(
                "list_transactions",
                {
                    "conversation_id": conversation_id,
                    "card_last4": card_last4,
                    "date_from": date_from,
                    "date_to": date_to,
                },
            ),
        )

    async def open_dispute(
        self,
        conversation_id: str,
        transaction_id: str,
        reason: str,
        idempotency_key: str,
    ) -> DisputeOpened:
        return cast(
            DisputeOpened,
            self._call(
                "open_dispute",
                {
                    "conversation_id": conversation_id,
                    "transaction_id": transaction_id,
                    "reason": reason,
                    "idempotency_key": idempotency_key,
                },
            ),
        )

    async def block_card(
        self,
        conversation_id: str,
        card_id: str,
        reason: str,
        idempotency_key: str,
    ) -> CardBlocked:
        return cast(
            CardBlocked,
            self._call(
                "block_card",
                {
                    "conversation_id": conversation_id,
                    "card_id": card_id,
                    "reason": reason,
                    "idempotency_key": idempotency_key,
                },
            ),
        )

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
        return cast(
            EscalationRegistered,
            self._call(
                "escalate",
                {
                    "conversation_id": conversation_id,
                    "reason": reason,
                    "idempotency_key": idempotency_key,
                    "transaction_id": transaction_id,
                    "card_id": card_id,
                    "prior_actions": prior_actions,
                    "dispute_id": dispute_id,
                    "note": note,
                },
            ),
        )
