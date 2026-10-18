"""DisputePolicy: motor de reglas determinista de spec §5 (Art. 5)."""

from datetime import date, timedelta, timezone
from decimal import Decimal

from dispute_agent.domain import messages
from dispute_agent.domain.models.decision import (
    AgentAction,
    Decision,
    DisputeDecision,
    EscalationReason,
)
from dispute_agent.domain.models.transaction import DisputedTransaction, TransactionStatus

AMOUNT_THRESHOLD_COP = Decimal(500000)
MAX_FOREIGN_AGE_DAYS = 90
_DOMESTIC_COUNTRY = "CO"
_BOGOTA = timezone(timedelta(hours=-5))


def _decision(
    rule: str,
    decision: Decision,
    reason: EscalationReason | None,
    actions: frozenset[AgentAction],
) -> DisputeDecision:
    return DisputeDecision(
        decision=decision,
        rule=rule,
        escalation_reason=reason,
        allowed_actions=actions,
        customer_reason=messages.DP_REASONS[rule],
        next_steps=messages.DP_NEXT_STEPS[rule],
    )


class DisputePolicy:
    """Decide por transacción según la tabla DP-007-01…07; solo usa datos estructurados."""

    def __init__(self, usd_cop_rate: Decimal) -> None:
        self._usd_cop_rate = usd_cop_rate

    def equivalent_cop(self, tx: DisputedTransaction) -> Decimal | None:
        """Monto equivalente en COP; None si la moneda no es COP ni USD (RN-007-09)."""
        if tx.currency == "COP":
            return tx.amount
        if tx.currency == "USD":
            return tx.amount * self._usd_cop_rate
        return None

    def age_days(self, tx: DisputedTransaction, today: date) -> int:
        """Antigüedad en días con la fecha local de Bogotá de `occurred_at` (RN-007-07)."""
        return (today - tx.occurred_at.astimezone(_BOGOTA).date()).days

    def decide(
        self, tx: DisputedTransaction, today: date, fraud_declared: bool = False
    ) -> DisputeDecision:
        """Aplica la primera fila de la tabla de §5 cuyas condiciones se cumplen."""
        base = self._base_decision(tx, today)
        if not fraud_declared:
            return base
        actions = {AgentAction.BLOCK_CARD, AgentAction.ESCALATE}
        if base.decision is Decision.RESOLVE:
            actions.add(AgentAction.OPEN_DISPUTE)
            rule = "DP-007-06"
        else:
            rule = "DP-007-07"
        return _decision(
            rule, Decision.ESCALATE, EscalationReason.FRAUD_SUSPECTED, frozenset(actions)
        )

    def _base_decision(self, tx: DisputedTransaction, today: date) -> DisputeDecision:
        escalate = frozenset({AgentAction.ESCALATE})
        if tx.status is not TransactionStatus.CONFIRMED:
            return _decision("DP-007-01", Decision.REJECT, None, frozenset())
        equivalent = self.equivalent_cop(tx)
        if equivalent is None:
            return _decision(
                "DP-007-02", Decision.ESCALATE, EscalationReason.INCONCLUSIVE_RULES, escalate
            )
        if equivalent > AMOUNT_THRESHOLD_COP:
            return _decision(
                "DP-007-03", Decision.ESCALATE, EscalationReason.AMOUNT_OVER_THRESHOLD, escalate
            )
        if (
            tx.merchant_country != _DOMESTIC_COUNTRY
            and self.age_days(tx, today) > MAX_FOREIGN_AGE_DAYS
        ):
            return _decision(
                "DP-007-04", Decision.ESCALATE, EscalationReason.INCONCLUSIVE_RULES, escalate
            )
        return _decision("DP-007-05", Decision.RESOLVE, None, frozenset({AgentAction.OPEN_DISPUTE}))
