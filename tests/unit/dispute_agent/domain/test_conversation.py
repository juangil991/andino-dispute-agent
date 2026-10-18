"""Tests de Conversation (estado de la conversación, plan §4)."""

from datetime import UTC, datetime
from decimal import Decimal

from dispute_agent.domain.models.conversation import (
    Conversation,
    ConversationStatus,
    KnownCard,
)
from dispute_agent.domain.models.decision import AgentAction, Decision, DisputeDecision
from dispute_agent.domain.models.transaction import DisputedTransaction, TransactionStatus


def _tx(transaction_id: str = "T-1") -> DisputedTransaction:
    return DisputedTransaction(
        transaction_id=transaction_id,
        card_id="CARD-1",
        masked_card="**** 1111",
        occurred_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        merchant="Comercio Ficticio",
        amount=Decimal("85000.00"),
        currency="COP",
        merchant_country="CO",
        status=TransactionStatus.CONFIRMED,
    )


def _decision(decision: Decision) -> DisputeDecision:
    open_dispute = frozenset({AgentAction.OPEN_DISPUTE})
    actions = open_dispute if decision is Decision.RESOLVE else frozenset[AgentAction]()
    return DisputeDecision(
        decision=decision,
        rule="DP-TEST",
        escalation_reason=None,
        allowed_actions=actions,
        customer_reason="motivo",
        next_steps="pasos",
    )


def _conv() -> Conversation:
    return Conversation(conversation_id="conv-1")


def test_conversation_closed_never_reopens() -> None:
    """Una conversación ESCALATED no vuelve a ACTIVE (RN-007-24)."""
    conv = _conv()
    conv.close()
    conv.mark_verified("C-0001")
    conv.record_search(matches=0, refinement_required=False)
    conv.record_decision("T-1", _decision(Decision.RESOLVE))
    assert conv.status is ConversationStatus.ESCALATED


# Soporte de tests: cierre de la conversación · Art. 3
def test_conversation_close_sets_escalated() -> None:
    conv = _conv()
    assert conv.status is ConversationStatus.ACTIVE
    conv.close()
    assert conv.status is ConversationStatus.ESCALATED


# Soporte de tests: contador de búsquedas fallidas (RN-007-05) · Art. 3
def test_conversation_record_search_counts_only_empty_without_refinement() -> None:
    conv = _conv()
    conv.record_search(matches=3, refinement_required=True)
    conv.record_search(matches=1, refinement_required=False)
    conv.record_search(matches=0, refinement_required=True)
    assert conv.failed_searches == 0
    conv.record_search(matches=0, refinement_required=False)
    conv.record_search(matches=0, refinement_required=False)
    assert conv.failed_searches == 2


# Soporte de tests: marca de verificación · Art. 3
def test_conversation_mark_verified_sets_customer() -> None:
    conv = _conv()
    assert conv.verified_customer_id is None
    conv.mark_verified("C-0001")
    assert conv.verified_customer_id == "C-0001"


# Soporte de tests: guarda de escrituras (RN-007-11) · Art. 3
def test_conversation_allows_write_only_with_open_dispute_decision() -> None:
    conv = _conv()
    tx = _tx()
    assert conv.allows_write_for(tx) is False
    conv.record_decision(tx.transaction_id, _decision(Decision.REJECT))
    assert conv.allows_write_for(tx) is False
    conv.record_decision(tx.transaction_id, _decision(Decision.RESOLVE))
    assert conv.allows_write_for(tx) is True
    assert conv.allows_write_for(_tx("T-2")) is False


# Soporte de tests: búsqueda de tarjeta por last4 · Art. 3
def test_conversation_card_by_last4_returns_one_none_or_many() -> None:
    conv = _conv()
    a = KnownCard(card_id="CARD-1", last4="1111")
    b = KnownCard(card_id="CARD-2", last4="2222")
    c = KnownCard(card_id="CARD-3", last4="2222")
    conv.known_cards = (a, b, c)
    assert conv.card_by_last4("1111") == (a,)
    assert conv.card_by_last4("9999") == ()
    assert conv.card_by_last4("2222") == (b, c)


# Soporte de tests: marca de petición de dígitos (RN-007-15) · Art. 3
def test_conversation_card_digits_requested_defaults_false_and_can_be_set() -> None:
    conv = _conv()
    assert conv.card_digits_requested is False
    conv.card_digits_requested = True
    assert conv.card_digits_requested is True


# Soporte de tests: transacciones vistas · Art. 3
def test_conversation_remember_transactions_keys_by_transaction_id() -> None:
    conv = _conv()
    t1, t2 = _tx("T-1"), _tx("T-2")
    conv.remember_transactions([t1, t2])
    assert conv.seen_transactions == {"T-1": t1, "T-2": t2}
