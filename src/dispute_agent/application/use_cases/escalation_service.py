"""Servicio de derivación a analista: solicitudes, claves de idempotencia y fallas."""

import hashlib
from dataclasses import dataclass

from dispute_agent.application.ports.audit_log import AgentAuditEvent, AuditLogPort
from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolsPort,
    EscalationRegistered,
)
from dispute_agent.application.ports.clock import Clock
from dispute_agent.domain import messages
from dispute_agent.domain.models.conversation import Conversation
from dispute_agent.domain.models.decision import EscalationReason, PriorAction
from dispute_agent.domain.models.outcome import Outcome, OutcomeKind
from dispute_agent.domain.models.transaction import DisputedTransaction

_FAILURE_RULE = "RN-007-22"
_IDENTITY_NOT_VERIFIED = "IDENTITY_NOT_VERIFIED"
_PRIOR_ORDER = {action: index for index, action in enumerate(PriorAction)}


@dataclass(frozen=True)
class _Request:
    reason: EscalationReason
    rule: str
    note: str
    transaction_id: str | None
    card_id: str | None
    prior_actions: tuple[PriorAction, ...]
    dispute_id: str | None

    def limited(self) -> "_Request":
        """Resumen sin datos del cliente (RN-006-08, RN-007-22)."""
        return _Request(self.reason, self.rule, self.note, None, None, (), None)

    def key(self) -> str:
        content = "\x1f".join(
            (
                self.reason.value,
                self.rule,
                self.transaction_id or "",
                self.card_id or "",
                ",".join(action.value for action in self.prior_actions),
                self.dispute_id or "",
                self.note,
            )
        )
        return "esc-" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


class EscalationService:
    """Construye y envía la derivación; no cierra la conversación."""

    def __init__(self, banking: BankingToolsPort, audit: AuditLogPort, clock: Clock) -> None:
        self._banking = banking
        self._audit_log = audit
        self._clock = clock

    async def escalate(
        self,
        conv: Conversation,
        reason: EscalationReason,
        rule: str,
        note: str | None = None,
        transaction: DisputedTransaction | None = None,
        card_id: str | None = None,
        prior_actions: tuple[PriorAction, ...] = (),
        dispute_id: str | None = None,
    ) -> Outcome:
        if rule in messages.DP_REASONS:
            customer_reason = messages.DP_REASONS[rule]
            next_steps = messages.DP_NEXT_STEPS[rule]
        else:
            customer_reason = messages.ESCALATED_NO_TX_REASON
            next_steps = messages.ESCALATED_NO_TX_NEXT_STEPS
        final_note = note if note is not None else f"{rule}: {customer_reason}"

        if conv.verified_customer_id is not None:
            request = _Request(
                reason=reason,
                rule=rule,
                note=final_note,
                transaction_id=transaction.transaction_id if transaction else None,
                card_id=card_id or (transaction.card_id if transaction else None),
                prior_actions=tuple(sorted(set(prior_actions), key=_PRIOR_ORDER.__getitem__)),
                dispute_id=dispute_id,
            )
        else:
            request = _Request(reason, rule, final_note, None, None, (), None)

        try:
            try:
                registered = await self._send(conv, request)
            except BankingToolError as error:
                if error.code != _IDENTITY_NOT_VERIFIED:
                    raise
                request = request.limited()
                registered = await self._send(conv, request)
        except Exception as error:  # noqa: BLE001 - toda falla se traduce en ESCALATION_FAILED
            self._audit(
                conv,
                request,
                {"result": "ESCALATION_FAILED", "error": type(error).__name__},
                f"{reason.value}; falla {type(error).__name__}",
            )
            return Outcome(
                kind=OutcomeKind.ESCALATION_FAILED,
                rule=_FAILURE_RULE,
                reason=messages.OUTCOME_REASONS[OutcomeKind.ESCALATION_FAILED],
                next_steps=messages.OUTCOME_NEXT_STEPS[OutcomeKind.ESCALATION_FAILED],
            )

        conv.escalated_keys.add(request.key())
        self._audit(
            conv,
            request,
            {"result": "ESCALATED", "escalation_id": registered.escalation_id},
            reason.value,
        )
        return Outcome(
            kind=OutcomeKind.ESCALATED,
            rule=rule,
            reason=customer_reason,
            next_steps=next_steps,
            transaction_id=request.transaction_id,
            masked_card=transaction.masked_card if transaction else None,
            reference=registered.escalation_id,
        )

    async def _send(self, conv: Conversation, request: _Request) -> EscalationRegistered:
        return await self._banking.escalate(
            conv.conversation_id,
            request.reason,
            request.key(),
            transaction_id=request.transaction_id,
            card_id=request.card_id,
            prior_actions=request.prior_actions,
            dispute_id=request.dispute_id,
            note=request.note,
        )

    def _audit(
        self,
        conv: Conversation,
        request: _Request,
        output: dict[str, object],
        reason: str,
    ) -> None:
        """Emite el evento `escalation` con la solicitud como entrada."""
        self._audit_log.record(
            AgentAuditEvent(
                conversation_id=conv.conversation_id,
                at=self._clock.now(),
                event_type="escalation",
                tool="escalate",
                input={
                    "reason": request.reason.value,
                    "transaction_id": request.transaction_id,
                    "card_id": request.card_id,
                    "prior_actions": [action.value for action in request.prior_actions],
                    "dispute_id": request.dispute_id,
                },
                output=output,
                rule=request.rule,
                reason=reason,
            )
        )
