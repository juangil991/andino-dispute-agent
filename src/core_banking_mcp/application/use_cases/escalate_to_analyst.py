"""Caso de uso: derivar un caso a un analista humano (RN-006-01…15)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from core_banking_mcp.application.errors import (
    CoreUnavailableError,
    EscalationDataNotFoundError,
    IdentityNotVerifiedError,
)
from core_banking_mcp.application.ports.audit_log import AuditEvent, AuditLogPort
from core_banking_mcp.application.ports.card_repository import CardRepository
from core_banking_mcp.application.ports.clock import Clock
from core_banking_mcp.application.ports.conversation_verification_store import (
    ConversationVerificationStore,
)
from core_banking_mcp.application.ports.dispute_repository import DisputeRepository
from core_banking_mcp.application.ports.escalation_repository import EscalationRepository
from core_banking_mcp.application.ports.transaction_repository import TransactionRepository
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.masking import mask_card, redact_card_numbers
from core_banking_mcp.domain.models.card_block import OwnedCard
from core_banking_mcp.domain.models.customer import CardStatus
from core_banking_mcp.domain.models.dispute import MAX_ID_LENGTH
from core_banking_mcp.domain.models.escalation import (
    MAX_NOTE_LENGTH,
    Escalation,
    EscalationReason,
    EscalationRequest,
    PriorAction,
)
from core_banking_mcp.domain.models.transaction import Transaction


@dataclass(frozen=True)
class EscalateCommand:
    conversation_id: str | None
    reason: str | None
    idempotency_key: str | None
    transaction_id: str | None
    card_id: str | None
    prior_actions: Sequence[str] | None
    dispute_id: str | None
    note: str | None


@dataclass(frozen=True)
class EscalationResult:
    escalation: Escalation
    transaction: Transaction | None
    card: OwnedCard | None
    outcome: Literal["escalated", "replayed"]


class EscalateToAnalyst:
    def __init__(
        self,
        transactions: TransactionRepository,
        cards: CardRepository,
        disputes: DisputeRepository,
        escalations: EscalationRepository,
        store: ConversationVerificationStore,
        audit_log: AuditLogPort,
        clock: Clock,
    ) -> None:
        self._transactions = transactions
        self._cards = cards
        self._disputes = disputes
        self._escalations = escalations
        self._store = store
        self._audit_log = audit_log
        self._clock = clock

    def execute(self, command: EscalateCommand) -> EscalationResult:
        try:
            request = EscalationRequest.create(
                command.conversation_id,
                command.reason,
                command.idempotency_key,
                command.transaction_id,
                command.card_id,
                command.prior_actions,
                command.dispute_id,
                command.note,
            )
        except InvalidInputError as error:
            rule = "RN-006-05" if _is_prior_actions_error(error) else "RN-006-10"
            self._record(
                command,
                _Resolved(),
                outcome="error",
                error_code="INVALID_INPUT",
                rule=rule,
                reason="Entrada inválida",
            )
            raise
        resolved = _Resolved()
        try:
            customer_id = self._store.get(request.conversation_id).verified_customer_id
            resolved.customer_id = customer_id
            resolved.identity_verified = customer_id is not None
            if request.has_customer_data and customer_id is None:
                raise IdentityNotVerifiedError("Identidad no verificada")
            existing = self._escalations.find_by_key(
                request.conversation_id, request.idempotency_key
            )
            if existing is not None:
                result = self._replay(existing, request, resolved)
            else:
                result = self._create(request, customer_id, resolved)
        except IdentityNotVerifiedError:
            self._record(
                command,
                resolved,
                outcome="error",
                error_code="IDENTITY_NOT_VERIFIED",
                rule="RN-006-03",
                reason="Datos del cliente sin verificación de identidad",
            )
            raise
        except InvalidInputError:
            self._record(
                command,
                resolved,
                outcome="error",
                error_code="INVALID_INPUT",
                rule="RN-006-09",
                reason="Clave de reintento ya usada con otros datos",
            )
            raise
        except EscalationDataNotFoundError:
            self._record(
                command,
                resolved,
                outcome="error",
                error_code="NOT_FOUND",
                rule="RN-006-06" if resolved.checking_prior_actions else "RN-006-04",
                reason="Los datos indicados no existen o no son del cliente verificado"
                if not resolved.checking_prior_actions
                else "Las acciones previas no se reflejan en el core",
            )
            raise
        except Exception as error:
            self._record(
                command,
                resolved,
                outcome="error",
                error_code="INTERNAL",
                rule="RN-006-15",
                reason="Falla inesperada del core bancario",
            )
            raise CoreUnavailableError("Core bancario no disponible") from error
        if result.outcome == "escalated":
            rule, reason = "RN-006-08", "Derivación registrada"
        else:
            rule, reason = (
                "RN-006-09",
                "Repetición de la solicitud; se devuelve la derivación existente",
            )
        self._record(
            command,
            resolved,
            outcome=result.outcome,
            rule=rule,
            reason=reason,
            escalation_id=result.escalation.escalation_id,
        )
        return result

    def _replay(
        self, existing: Escalation, request: EscalationRequest, resolved: "_Resolved"
    ) -> EscalationResult:
        if not existing.same_request(request):
            raise InvalidInputError("idempotency_key", "clave ya usada con otros datos")
        customer_id = existing.customer_id
        transaction: Transaction | None = None
        card: OwnedCard | None = None
        if customer_id is not None and existing.transaction_id is not None:
            transaction = self._transactions.find_customer_transaction(
                customer_id, existing.transaction_id
            )
            if transaction is None:
                raise RuntimeError("transacción guardada no encontrada al rehidratar")
        if customer_id is not None and existing.card_id is not None:
            card = self._cards.find_customer_card(customer_id, existing.card_id)
            if card is None:
                raise RuntimeError("tarjeta guardada no encontrada al rehidratar")
            resolved.card = card
        return EscalationResult(existing, transaction, card, "replayed")

    def _create(
        self, request: EscalationRequest, customer_id: str | None, resolved: "_Resolved"
    ) -> EscalationResult:
        transaction: Transaction | None = None
        card: OwnedCard | None = None
        if customer_id is not None:
            transaction, card = self._resolve_customer_data(request, customer_id, resolved)
            resolved.checking_prior_actions = True
            self._check_prior_actions(request, card)
        escalation = self._escalations.add(
            request.conversation_id,
            request.idempotency_key,
            request.reason,
            self._clock.now(),
            customer_id is not None,
            customer_id,
            request.transaction_id,
            request.card_id,
            request.prior_actions,
            request.dispute_id,
            request.note,
        )
        return EscalationResult(escalation, transaction, card, "escalated")

    def _resolve_customer_data(
        self, request: EscalationRequest, customer_id: str, resolved: "_Resolved"
    ) -> tuple[Transaction | None, OwnedCard | None]:
        transaction: Transaction | None = None
        card: OwnedCard | None = None
        if request.transaction_id is not None:
            transaction = self._transactions.find_customer_transaction(
                customer_id, request.transaction_id
            )
            if transaction is None:
                raise EscalationDataNotFoundError("Datos no encontrados")
        if request.card_id is not None:
            card = self._cards.find_customer_card(customer_id, request.card_id)
            if card is None:
                raise EscalationDataNotFoundError("Datos no encontrados")
            resolved.card = card
        if transaction is not None and card is not None and transaction.card_id != card.card_id:
            raise EscalationDataNotFoundError("Datos no encontrados")
        return transaction, card

    def _check_prior_actions(self, request: EscalationRequest, card: OwnedCard | None) -> None:
        if PriorAction.DISPUTE_OPENED in request.prior_actions:
            assert request.dispute_id is not None
            dispute = self._disputes.find_by_id(request.dispute_id)
            if dispute is None or dispute.transaction_id != request.transaction_id:
                raise EscalationDataNotFoundError("Datos no encontrados")
        if PriorAction.CARD_BLOCKED in request.prior_actions and (
            card is None or card.status is not CardStatus.BLOCKED
        ):
            raise EscalationDataNotFoundError("Datos no encontrados")

    def _record(
        self,
        command: EscalateCommand,
        resolved: "_Resolved",
        *,
        outcome: str,
        rule: str,
        reason: str,
        error_code: str | None = None,
        escalation_id: str | None = None,
    ) -> None:
        self._audit_log.record(
            AuditEvent(
                conversation_id=command.conversation_id
                if command.conversation_id is not None
                else "",
                timestamp=self._clock.now(),
                tool="escalar_a_analista",
                input=None,
                outcome=outcome,
                count=None,
                customer_ids=(),
                error_code=error_code,
                rule=rule,
                reason=reason,
                customer_id=resolved.customer_id,
                masked_card=mask_card(resolved.card.last4) if resolved.card is not None else None,
                idempotency_key=_audited_id(command.idempotency_key),
                transaction_id=_audited_id(command.transaction_id),
                card_id=_audited_id(command.card_id),
                dispute_id=_audited_id(command.dispute_id),
                escalation_reason=_audited_reason(command.reason),
                escalation_id=escalation_id,
                note=_audited_note(command.note),
                prior_actions=_audited_prior_actions(command.prior_actions),
                identity_verified=resolved.identity_verified,
            )
        )


@dataclass
class _Resolved:
    """Datos que ya se conocen cuando la invocación termina."""

    customer_id: str | None = None
    identity_verified: bool | None = None
    card: OwnedCard | None = None
    checking_prior_actions: bool = False


def _is_prior_actions_error(error: InvalidInputError) -> bool:
    """Indica si el rechazo es por las acciones previas (RN-006-05)."""
    return error.field == "prior_actions" or (
        error.field == "dispute_id" and "DISPUTE_OPENED" in error.reason
    )


def _audited_id(value: str | None) -> str | None:
    """Texto libre válido según RN-006-10, con el PAN redactado; `None` si no es válido."""
    if value is None:
        return None
    text = value.strip()
    if not text or len(text) > MAX_ID_LENGTH:
        return None
    return redact_card_numbers(text)


def _audited_note(value: str | None) -> str | None:
    """Nota válida según RN-006-07, con el PAN redactado; `None` si no llegó o no es válida."""
    if value is None:
        return None
    text = value.strip()
    if not text or len(text) > MAX_NOTE_LENGTH:
        return None
    return redact_card_numbers(text)


def _audited_reason(value: str | None) -> str | None:
    """Motivo solo si es un código del catálogo (RN-006-02)."""
    try:
        return EscalationReason(value).value
    except ValueError:
        return None


def _audited_prior_actions(values: Sequence[str] | None) -> tuple[str, ...]:
    """Acciones previas solo si todas son códigos del catálogo y no se repiten (RN-006-05)."""
    try:
        parsed = {PriorAction(value) for value in values or ()}
    except ValueError:
        return ()
    if len(parsed) != len(tuple(values or ())):
        return ()
    return tuple(action.value for action in PriorAction if action in parsed)
