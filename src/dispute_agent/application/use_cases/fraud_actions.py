"""FraudActions: bloqueo de la tarjeta afectada y derivación por fraude (RN-007-14…17)."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from dispute_agent.application.ports.audit_log import AgentAuditEvent, AuditEventType, AuditLogPort
from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolsPort,
    BankingToolUnavailableError,
)
from dispute_agent.application.ports.clock import Clock
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.domain import messages
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus
from dispute_agent.domain.models.decision import EscalationReason, PriorAction
from dispute_agent.domain.models.outcome import Outcome, OutcomeKind
from dispute_agent.domain.models.transaction import DisputedTransaction

_FRAUD_REASON = "FRAUD_SUSPECTED"
_BLOCK_TOOL = "bloquear_tarjeta"
_BLOCK_RULE = "RN-007-14"
_CARD_RULE = "RN-007-15"
_NOT_BLOCKABLE_RULE = "RN-007-16"
_UNVERIFIED_RULE = "RN-007-17"
_FAILURE_RULE = "RN-007-21"
_CARD_NOT_BLOCKABLE = "CARD_NOT_BLOCKABLE"
_UNAVAILABLE_CODE = "UNAVAILABLE"


@dataclass(frozen=True)
class FraudReportResult:
    """Resultado de reportar fraude; `needs_card_digits` pide los últimos 4 dígitos."""

    outcomes: tuple[Outcome, ...]
    needs_card_digits: bool = False


def _block_key(card_id: str) -> str:
    content = f"{card_id}\x1f{_FRAUD_REASON}"
    return "block-" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


class FraudActions:
    """Bloquea la tarjeta afectada y deriva por fraude, decidiendo cada transacción señalada."""

    def __init__(
        self,
        banking: BankingToolsPort,
        dispute_actions: DisputeActions,
        escalation: EscalationService,
        audit: AuditLogPort,
        clock: Clock,
    ) -> None:
        self._banking = banking
        self._dispute_actions = dispute_actions
        self._escalation = escalation
        self._audit_log = audit
        self._clock = clock

    async def report(
        self,
        conv: Conversation,
        card_last4: str | None,
        transaction_ids: Sequence[str] | None,
        human_note: str | None = None,
    ) -> FraudReportResult:
        if conv.verified_customer_id is None:
            return await self._unverified(conv, human_note)

        transactions = self._known_transactions(conv, transaction_ids)
        if transactions:
            card_ids = list(dict.fromkeys(tx.card_id for tx in transactions))
        else:
            resolved = self._resolve_card(conv, card_last4)
            if isinstance(resolved, FraudReportResult):
                return resolved
            card_ids = [resolved] if resolved is not None else []
            if not card_ids:
                return await self._escalate_without_block(conv, human_note)

        outcomes: list[Outcome] = []
        blocked: dict[str, bool] = {}
        for card_id in card_ids:
            masked = next((tx.masked_card for tx in transactions if tx.card_id == card_id), None)
            failed = await self._block(conv, card_id, masked, outcomes, blocked)
            if failed:
                return FraudReportResult(tuple(outcomes))

        if transactions:
            for tx in transactions:
                if conv.status is ConversationStatus.ESCALATED:
                    break
                outcomes.extend(
                    await self._dispute_actions.evaluate(
                        conv, tx.transaction_id, fraud=True, prior_block=blocked[tx.card_id]
                    )
                )
            return FraudReportResult(tuple(outcomes))

        card_id = card_ids[0]
        prior = (PriorAction.CARD_BLOCKED,) if blocked[card_id] else ()
        outcomes.append(
            await self._escalation.escalate(
                conv,
                reason=EscalationReason.FRAUD_SUSPECTED,
                rule=_BLOCK_RULE,
                note=human_note,
                card_id=card_id,
                prior_actions=prior,
            )
        )
        return FraudReportResult(tuple(outcomes))

    @staticmethod
    def _known_transactions(
        conv: Conversation, transaction_ids: Sequence[str] | None
    ) -> list[DisputedTransaction]:
        found: dict[str, DisputedTransaction] = {}
        for tx_id in transaction_ids or ():
            tx = conv.seen_transactions.get(tx_id)
            if tx is not None:
                found[tx_id] = tx
        return list(found.values())

    @staticmethod
    def _resolve_card(
        conv: Conversation, card_last4: str | None
    ) -> "str | None | FraudReportResult":
        """Devuelve el card_id, None si no hay forma de determinarlo, o la petición de dígitos."""
        if card_last4:
            matches = conv.card_by_last4(card_last4)
            if len(matches) == 1:
                return matches[0].card_id
            if len(matches) > 1:
                return None
        elif len(conv.known_cards) == 1:
            return conv.known_cards[0].card_id
        elif not conv.known_cards:
            return None
        if not conv.card_digits_requested:
            conv.card_digits_requested = True
            return FraudReportResult((), needs_card_digits=True)
        return None

    async def _block(
        self,
        conv: Conversation,
        card_id: str,
        masked_card: str | None,
        outcomes: list[Outcome],
        blocked: dict[str, bool],
    ) -> bool:
        """Bloquea una vez la tarjeta; devuelve True si falló y se derivó (RN-007-21)."""
        if card_id in conv.blocked_cards:
            blocked[card_id] = True
            return False
        try:
            result = await self._banking.block_card(
                conv.conversation_id, card_id, _FRAUD_REASON, _block_key(card_id)
            )
        except BankingToolError as error:
            self._audit_call(conv, card_id, error.code)
            if error.code != _CARD_NOT_BLOCKABLE:
                await self._fail(conv, card_id, error.code, outcomes)
                return True
            blocked[card_id] = False
            outcomes.append(
                self._outcome(OutcomeKind.CARD_NOT_BLOCKABLE, _NOT_BLOCKABLE_RULE, masked_card)
            )
            return False
        except BankingToolUnavailableError:
            self._audit_call(conv, card_id, _UNAVAILABLE_CODE)
            await self._fail(conv, card_id, _UNAVAILABLE_CODE, outcomes)
            return True

        self._audit_call(conv, card_id, "ALREADY_BLOCKED" if result.already_blocked else "BLOCKED")
        conv.blocked_cards.add(card_id)
        blocked[card_id] = True
        if result.already_blocked:
            outcomes.append(
                self._outcome(OutcomeKind.CARD_ALREADY_BLOCKED, _NOT_BLOCKABLE_RULE, masked_card)
            )
        else:
            outcomes.append(self._outcome(OutcomeKind.CARD_BLOCKED, _BLOCK_RULE, masked_card))
        return False

    async def _fail(
        self, conv: Conversation, card_id: str, code: str, outcomes: list[Outcome]
    ) -> None:
        """RN-007-21: falla de bloquear_tarjeta; deriva sin CARD_BLOCKED y cierra."""
        outcomes.append(
            await self._escalation.escalate(
                conv,
                reason=EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE,
                rule=_FAILURE_RULE,
                note=f"{_FAILURE_RULE}: falla irrecuperable en {_BLOCK_TOOL} ({code})",
                card_id=card_id,
            )
        )
        self._close(conv, _FAILURE_RULE, f"falla irrecuperable en {_BLOCK_TOOL} ({code})")

    async def _unverified(self, conv: Conversation, human_note: str | None) -> FraudReportResult:
        """RN-007-17: sin identidad verificada no se bloquea; deriva limitado y cierra."""
        note = f"{_UNVERIFIED_RULE}: fraude declarado sin identidad verificada"
        if human_note:
            note = f"{note}. {human_note}"
        outcome = await self._escalation.escalate(
            conv,
            reason=EscalationReason.FRAUD_SUSPECTED,
            rule=_UNVERIFIED_RULE,
            note=note,
        )
        self._close(conv, _UNVERIFIED_RULE, "fraude declarado sin identidad verificada")
        return FraudReportResult((outcome,))

    async def _escalate_without_block(
        self, conv: Conversation, human_note: str | None
    ) -> FraudReportResult:
        """RN-007-15: no se pudo determinar una única tarjeta; deriva sin bloquear."""
        outcome = await self._escalation.escalate(
            conv,
            reason=EscalationReason.FRAUD_SUSPECTED,
            rule=_CARD_RULE,
            note=human_note,
        )
        return FraudReportResult((outcome,))

    def _close(self, conv: Conversation, rule: str, reason: str) -> None:
        conv.close()
        self._audit(
            conv,
            "conversation_closed",
            input={"tool": _BLOCK_TOOL},
            output={"status": conv.status.value},
            rule=rule,
            reason=reason,
        )

    def _audit_call(self, conv: Conversation, card_id: str, result: str) -> None:
        self._audit(
            conv,
            "tool_call",
            input={"card_id": card_id, "reason": _FRAUD_REASON},
            output={"result": result},
            rule=_BLOCK_RULE,
            reason=result,
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
    ) -> None:
        """Punto único de emisión de eventos de auditoría de esta clase."""
        self._audit_log.record(
            AgentAuditEvent(
                conversation_id=conv.conversation_id,
                at=self._clock.now(),
                event_type=event_type,
                tool=_BLOCK_TOOL,
                input=input,
                output=output,
                rule=rule,
                reason=reason,
            )
        )

    @staticmethod
    def _outcome(kind: OutcomeKind, rule: str, masked_card: str | None) -> Outcome:
        return Outcome(
            kind=kind,
            rule=rule,
            reason=messages.OUTCOME_REASONS[kind],
            next_steps=messages.OUTCOME_NEXT_STEPS[kind],
            masked_card=masked_card,
        )
