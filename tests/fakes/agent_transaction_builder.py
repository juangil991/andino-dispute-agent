"""Builder de DisputedTransaction ficticias y deterministas para dispute_agent."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from dispute_agent.domain.models.transaction import DisputedTransaction, TransactionStatus

_BOGOTA = timezone(timedelta(hours=-5))


class DisputedTransactionBuilder:
    def __init__(self) -> None:
        self._transaction_id = "T-0001"
        self._card_id = "K-0001"
        self._masked_card = "**** 1234"
        self._occurred_at = datetime(2026, 3, 15, 12, 0, tzinfo=_BOGOTA)
        self._merchant = "Comercio Ficticio"
        self._amount = Decimal("100.00")
        self._currency = "COP"
        self._merchant_country = "CO"
        self._status = TransactionStatus.CONFIRMED

    def transaction_id(self, transaction_id: str) -> "DisputedTransactionBuilder":
        self._transaction_id = transaction_id
        return self

    def card(self, card_id: str, masked_card: str) -> "DisputedTransactionBuilder":
        self._card_id = card_id
        self._masked_card = masked_card
        return self

    def merchant(self, merchant: str) -> "DisputedTransactionBuilder":
        self._merchant = merchant
        return self

    def national(self) -> "DisputedTransactionBuilder":
        self._merchant_country = "CO"
        return self

    def foreign(self) -> "DisputedTransactionBuilder":
        self._merchant_country = "US"
        return self

    def amount(self, amount: str, currency: str) -> "DisputedTransactionBuilder":
        self._amount = Decimal(amount)
        self._currency = currency
        return self

    def status(self, status: TransactionStatus) -> "DisputedTransactionBuilder":
        self._status = status
        return self

    def occurred_at(self, occurred_at: datetime) -> "DisputedTransactionBuilder":
        self._occurred_at = occurred_at
        return self

    def days_ago(self, days: int, today: date) -> "DisputedTransactionBuilder":
        self._occurred_at = datetime.combine(today - timedelta(days=days), time(12, 0), _BOGOTA)
        return self

    def build(self) -> DisputedTransaction:
        return DisputedTransaction(
            transaction_id=self._transaction_id,
            card_id=self._card_id,
            masked_card=self._masked_card,
            occurred_at=self._occurred_at,
            merchant=self._merchant,
            amount=self._amount,
            currency=self._currency,
            merchant_country=self._merchant_country,
            status=self._status,
        )
