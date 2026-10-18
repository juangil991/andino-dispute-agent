"""Estado mutable de una conversación con el cliente (plan §4)."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from dispute_agent.domain.models.decision import AgentAction, DisputeDecision
from dispute_agent.domain.models.transaction import DisputedTransaction


class ConversationStatus(Enum):
    """Estado de la conversación; ESCALATED es terminal (RN-007-24)."""

    ACTIVE = "ACTIVE"
    ESCALATED = "ESCALATED"


@dataclass(frozen=True)
class KnownCard:
    """Tarjeta del cliente localizado (solo identificador y últimos 4 dígitos)."""

    card_id: str
    last4: str


@dataclass
class Conversation:
    """Estado de la conversación: verificación, búsquedas, decisiones e historial."""

    conversation_id: str
    status: ConversationStatus = ConversationStatus.ACTIVE
    located_customer_id: str | None = None
    verified_customer_id: str | None = None
    known_cards: tuple[KnownCard, ...] = ()
    failed_searches: int = 0
    seen_transactions: dict[str, DisputedTransaction] = field(default_factory=dict)
    decisions: dict[str, DisputeDecision] = field(default_factory=dict)
    blocked_cards: set[str] = field(default_factory=set)
    escalated_keys: set[str] = field(default_factory=set)
    provided_documents: set[str] = field(default_factory=set)
    card_digits_requested: bool = False
    history: list[object] = field(default_factory=list)

    def mark_verified(self, customer_id: str) -> None:
        self.verified_customer_id = customer_id

    def record_search(self, matches: int, refinement_required: bool) -> None:
        """Cuenta solo las búsquedas sin coincidencias y sin refinamiento (RN-007-05)."""
        if matches == 0 and not refinement_required:
            self.failed_searches += 1

    def remember_transactions(self, transactions: Iterable[DisputedTransaction]) -> None:
        for tx in transactions:
            self.seen_transactions[tx.transaction_id] = tx

    def record_decision(self, transaction_id: str, decision: DisputeDecision) -> None:
        self.decisions[transaction_id] = decision

    def close(self) -> None:
        self.status = ConversationStatus.ESCALATED

    def allows_write_for(self, tx: DisputedTransaction) -> bool:
        """Verdadero solo si la decisión de la transacción permite OPEN_DISPUTE (RN-007-11)."""
        decision = self.decisions.get(tx.transaction_id)
        return decision is not None and AgentAction.OPEN_DISPUTE in decision.allowed_actions

    def card_by_last4(self, last4: str) -> tuple[KnownCard, ...]:
        """Devuelve las tarjetas conocidas con esos últimos 4 dígitos (ninguna, una o varias)."""
        return tuple(card for card in self.known_cards if card.last4 == last4)
