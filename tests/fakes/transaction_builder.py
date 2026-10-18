"""Builder de transacciones ficticias y deterministas."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from core_banking_mcp.domain.models.transaction import Transaction, TransactionStatus


@dataclass
class TransactionBuilder:
    transaction_id: str = "T-0001"
    card_id: str = "K-0001"
    card_last4: str = "1234"
    occurred_at: datetime = field(default_factory=lambda: datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    merchant: str = "Comercio Ficticio"
    amount: Decimal = field(default_factory=lambda: Decimal("100.00"))
    currency: str = "COP"
    status: TransactionStatus = TransactionStatus.CONFIRMED
    merchant_country: str = "CO"

    def with_id(self, transaction_id: str) -> "TransactionBuilder":
        self.transaction_id = transaction_id
        return self

    def with_card(self, card_id: str, last4: str) -> "TransactionBuilder":
        self.card_id = card_id
        self.card_last4 = last4
        return self

    def with_occurred_at(self, occurred_at: datetime) -> "TransactionBuilder":
        self.occurred_at = occurred_at
        return self

    def with_status(self, status: TransactionStatus) -> "TransactionBuilder":
        self.status = status
        return self

    def with_amount(self, amount: Decimal) -> "TransactionBuilder":
        self.amount = amount
        return self

    def with_currency(self, currency: str) -> "TransactionBuilder":
        self.currency = currency
        return self

    def with_merchant_country(self, merchant_country: str) -> "TransactionBuilder":
        self.merchant_country = merchant_country
        return self

    def build(self) -> Transaction:
        return Transaction(
            transaction_id=self.transaction_id,
            card_id=self.card_id,
            card_last4=self.card_last4,
            occurred_at=self.occurred_at,
            merchant=self.merchant,
            amount=self.amount,
            currency=self.currency,
            status=self.status,
            merchant_country=self.merchant_country,
        )
