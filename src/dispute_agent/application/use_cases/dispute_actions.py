"""DisputeActions: decide con DisputePolicy y ejecuta las acciones permitidas por transacción."""

import hashlib

from dispute_agent.application.failure_detail import describe_failure
from dispute_agent.application.ports.audit_log import AgentAuditEvent, AuditEventType, AuditLogPort
from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolsPort,
    BankingToolUnavailableError,
)
from dispute_agent.application.ports.clock import Clock
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.domain import messages
from dispute_agent.domain.models.conversation import Conversation
from dispute_agent.domain.models.decision import (
    AgentAction,
    Decision,
    DisputeDecision,
    EscalationReason,
    PriorAction,
)
from dispute_agent.domain.models.outcome import Outcome, OutcomeKind
from dispute_agent.domain.models.transaction import DisputedTransaction
from dispute_agent.domain.policies.dispute_policy import DisputePolicy

_DISPUTE_ALREADY_OPEN = "DISPUTE_ALREADY_OPEN"
_FAILURE_RULE = "RN-007-21"
_ALREADY_OPEN_RULE = "RN-007-12"
_UNAVAILABLE_CODE = "UNAVAILABLE"


def _dispute_key(transaction_id: str, reason: str) -> str:
    content = f"{transaction_id}\x1f{reason}"
    return "dispute-" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


class DisputeActions:
    """Aplica la decisión de la política a una transacción y ejecuta sus acciones."""

    def __init__(
        self,
        policy: DisputePolicy,
        banking: BankingToolsPort,
        escalation: EscalationService,
        audit: AuditLogPort,
        clock: Clock,
    ) -> None:
        self._policy = policy
        self._banking = banking
        self._escalation = escalation
        self._audit_log = audit
        self._clock = clock

    async def evaluate(
        self,
        conv: Conversation,
        tx_id: str,
        reason: str = "UNRECOGNIZED_CHARGE",
        fraud: bool = False,
        prior_block: bool = False,
    ) -> list[Outcome]:
        tx = conv.seen_transactions.get(tx_id)
        if tx is None:
            raise ValueError(f"transacción no listada en la conversación: {tx_id}")

        decision = self._policy.decide(tx, self._clock.today(), fraud)
        conv.record_decision(tx_id, decision)
        self._audit(
            conv,
            "decision",
            input={"transaction_id": tx.transaction_id, "fraud": fraud},
            output={"decision": decision.decision.value},
            rule=decision.rule,
            reason=decision.customer_reason,
        )

        if decision.decision is Decision.REJECT:
            return [self._outcome(OutcomeKind.NOT_DISPUTABLE, decision, tx)]

        if AgentAction.OPEN_DISPUTE in decision.allowed_actions:
            return await self._open_then_continue(conv, tx, decision, reason, prior_block)

        return [await self._escalate(conv, tx, decision, prior_block)]

    async def _open_then_continue(
        self,
        conv: Conversation,
        tx: DisputedTransaction,
        decision: DisputeDecision,
        reason: str,
        prior_block: bool,
    ) -> list[Outcome]:
        resolves = decision.decision is Decision.RESOLVE
        outcomes: list[Outcome] = []
        dispute_id: str | None
        try:
            opened = await self._banking.open_dispute(
                conv.conversation_id,
                tx.transaction_id,
                reason,
                _dispute_key(tx.transaction_id, reason),
            )
        except BankingToolError as error:
            failed: dict[str, object] = {"error": error.code}
            if error.field is not None:
                failed["field"] = error.field
            self._audit_open(conv, tx, decision, reason, failed)
            if error.code != _DISPUTE_ALREADY_OPEN:
                return await self._fail(
                    conv, tx, "iniciar_disputa", error.code, prior_block, error.field
                )
            dispute_id = error.existing_dispute_id
            outcomes.append(
                Outcome(
                    kind=OutcomeKind.DISPUTE_ALREADY_OPEN,
                    rule=_ALREADY_OPEN_RULE,
                    reason=messages.OUTCOME_REASONS[OutcomeKind.DISPUTE_ALREADY_OPEN],
                    next_steps=messages.OUTCOME_NEXT_STEPS[OutcomeKind.DISPUTE_ALREADY_OPEN],
                    transaction_id=tx.transaction_id,
                    masked_card=tx.masked_card,
                    reference=dispute_id,
                )
            )
        except BankingToolUnavailableError:
            self._audit_open(conv, tx, decision, reason, {"error": _UNAVAILABLE_CODE})
            return await self._fail(conv, tx, "iniciar_disputa", _UNAVAILABLE_CODE, prior_block)
        else:
            dispute_id = opened.dispute_id
            self._audit_open(conv, tx, decision, reason, {"dispute_id": dispute_id})
            outcomes.append(
                self._outcome(OutcomeKind.DISPUTE_OPENED, decision, tx, reference=dispute_id)
            )

        if resolves:
            return outcomes

        # Tanto una disputa recién abierta como una ya existente (RN-007-12) constan como
        # DISPUTE_OPENED con su dispute_id (spec 007 §5; RN-006-05).
        prior = (PriorAction.CARD_BLOCKED,) if prior_block else ()
        prior = (*prior, PriorAction.DISPUTE_OPENED)
        outcomes.append(
            await self._escalate(conv, tx, decision, prior_block, prior, dispute_id=dispute_id)
        )
        return outcomes

    async def _escalate(
        self,
        conv: Conversation,
        tx: DisputedTransaction,
        decision: DisputeDecision,
        prior_block: bool,
        prior_actions: tuple[PriorAction, ...] | None = None,
        dispute_id: str | None = None,
    ) -> Outcome:
        if prior_actions is None:
            prior_actions = (PriorAction.CARD_BLOCKED,) if prior_block else ()
        assert decision.escalation_reason is not None
        return await self._escalation.escalate(
            conv,
            reason=decision.escalation_reason,
            rule=decision.rule,
            transaction=tx,
            prior_actions=prior_actions,
            dispute_id=dispute_id,
        )

    async def _fail(
        self,
        conv: Conversation,
        tx: DisputedTransaction,
        tool: str,
        code: str,
        prior_block: bool,
        field: str | None = None,
    ) -> list[Outcome]:
        """RN-007-21: falla de iniciar_disputa; deriva sin DISPUTE_OPENED y cierra."""
        detail = describe_failure(tool, code, field)
        outcome = await self._escalation.escalate(
            conv,
            reason=EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE,
            rule=_FAILURE_RULE,
            note=f"{_FAILURE_RULE}: {detail}",
            transaction=tx,
            prior_actions=(PriorAction.CARD_BLOCKED,) if prior_block else (),
        )
        conv.close()
        self._audit(
            conv,
            "conversation_closed",
            tool=tool,
            input={"tool": tool, "code": code},
            output={"status": conv.status.value},
            rule=_FAILURE_RULE,
            reason=detail,
        )
        return [outcome]

    @staticmethod
    def _outcome(
        kind: OutcomeKind,
        decision: DisputeDecision,
        tx: DisputedTransaction,
        reference: str | None = None,
    ) -> Outcome:
        return Outcome(
            kind=kind,
            rule=decision.rule,
            reason=decision.customer_reason,
            next_steps=decision.next_steps,
            transaction_id=tx.transaction_id,
            masked_card=tx.masked_card,
            reference=reference,
        )

    def _audit_open(
        self,
        conv: Conversation,
        tx: DisputedTransaction,
        decision: DisputeDecision,
        reason: str,
        output: dict[str, object],
    ) -> None:
        """Evento `tool_call` de iniciar_disputa (RN-007-28)."""
        result = "error" if "error" in output else "ok"
        is_failure = "error" in output and output["error"] != _DISPUTE_ALREADY_OPEN
        self._audit(
            conv,
            "tool_call",
            tool="iniciar_disputa",
            input={"transaction_id": tx.transaction_id, "reason": reason},
            output=output,
            # RN-010-08: la falla irrecuperable consta con RN-007-21; DISPUTE_ALREADY_OPEN
            # no es una falla de sistema y conserva la regla de la decisión.
            rule=_FAILURE_RULE if is_failure else decision.rule,
            reason=f"iniciar_disputa {result} para {tx.transaction_id}",
        )

    def _audit(
        self,
        conv: Conversation,
        event_type: AuditEventType,
        *,
        input: dict[str, object],
        output: dict[str, object],
        rule: str,
        reason: str,
        tool: str | None = None,
    ) -> None:
        """Punto único de emisión de eventos de auditoría de esta clase."""
        self._audit_log.record(
            AgentAuditEvent(
                conversation_id=conv.conversation_id,
                at=self._clock.now(),
                event_type=event_type,
                tool=tool,
                input=input,
                output=output,
                rule=rule,
                reason=reason,
            )
        )
