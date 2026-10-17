"""Repositorio de transacciones que siempre falla con una excepción que no es de dominio."""

from datetime import datetime

from core_banking_mcp.domain.models.transaction import CustomerCard, Transaction


class FailingTransactionRepository:
    def find_customer_cards(self, customer_id: str, last4: str) -> list[CustomerCard]:
        raise RuntimeError("fallo simulado del core (detalle interno secreto)")

    def find_transactions(
        self, card_ids: list[str], start: datetime, end: datetime, limit: int
    ) -> list[Transaction]:
        raise RuntimeError("fallo simulado del core (detalle interno secreto)")
