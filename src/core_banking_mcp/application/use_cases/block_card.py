"""Caso de uso: bloquear una tarjeta del cliente verificado (RN-005-01…13)."""

from dataclasses import dataclass

from core_banking_mcp.application.errors import (
    CardNotBlockableError,
    CardNotFoundError,
    CoreUnavailableError,
    IdentityNotVerifiedError,
)
from core_banking_mcp.application.ports.audit_log import AuditEvent, AuditLogPort
from core_banking_mcp.application.ports.card_repository import CardRepository
from core_banking_mcp.application.ports.clock import Clock
from core_banking_mcp.application.ports.conversation_verification_store import (
    ConversationVerificationStore,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.masking import mask_card, redact_card_numbers
from core_banking_mcp.domain.models.card_block import (
    BlockReason,
    CardBlock,
    CardBlockRequest,
    OwnedCard,
)
from core_banking_mcp.domain.models.customer import CardStatus
from core_banking_mcp.domain.models.dispute import MAX_ID_LENGTH


@dataclass(frozen=True)
class BlockCardCommand:
    conversation_id: str | None
    card_id: str | None
    reason: str | None
    idempotency_key: str | None


@dataclass(frozen=True)
class BlockCardResult:
    card: OwnedCard
    block: CardBlock | None
    outcome: str  # "blocked" | "already_blocked" | "replayed"


class BlockCard:
    def __init__(
        self,
        cards: CardRepository,
        store: ConversationVerificationStore,
        audit_log: AuditLogPort,
        clock: Clock,
    ) -> None:
        self._cards = cards
        self._store = store
        self._audit_log = audit_log
        self._clock = clock

    def execute(self, command: BlockCardCommand) -> BlockCardResult:
        try:
            request = CardBlockRequest.create(
                command.conversation_id,
                command.card_id,
                command.reason,
                command.idempotency_key,
            )
        except InvalidInputError:
            self._record(
                command,
                outcome="error",
                error_code="INVALID_INPUT",
                rule="RN-005-08",
                reason="Entrada inválida",
            )
            raise
        resolved = _Resolved()
        try:
            resolved.customer_id = self._store.get(request.conversation_id).verified_customer_id
            if resolved.customer_id is None:
                raise IdentityNotVerifiedError("Identidad no verificada")
            result = self._block(request, resolved)
        except IdentityNotVerifiedError:
            self._record(
                command,
                outcome="error",
                error_code="IDENTITY_NOT_VERIFIED",
                rule="RN-005-03",
                reason="Conversación sin verificación de identidad",
            )
            raise
        except InvalidInputError:
            self._record_resolved(
                command,
                resolved,
                outcome="error",
                error_code="INVALID_INPUT",
                rule="RN-005-07",
                reason="Clave de reintento ya usada con otra tarjeta u otro motivo",
            )
            raise
        except CardNotFoundError:
            self._record_resolved(
                command,
                resolved,
                outcome="error",
                error_code="NOT_FOUND",
                rule="RN-005-04",
                reason="La tarjeta no existe o no es del cliente verificado",
            )
            raise
        except CardNotBlockableError:
            self._record_resolved(
                command,
                resolved,
                outcome="error",
                error_code="CARD_NOT_BLOCKABLE",
                rule="RN-005-05",
                reason="Una tarjeta cancelada no se puede bloquear",
            )
            raise
        except Exception as error:
            self._record_resolved(
                command,
                resolved,
                outcome="error",
                error_code="INTERNAL",
                rule="RN-005-13",
                reason="Falla inesperada del core bancario",
            )
            raise CoreUnavailableError("Core bancario no disponible") from error
        outcome_rules = {
            "blocked": ("RN-005-06", "Tarjeta bloqueada"),
            "replayed": (
                "RN-005-07",
                "Repetición de la solicitud; se devuelve el bloqueo existente",
            ),
            "already_blocked": ("RN-005-05", "La tarjeta ya estaba bloqueada"),
        }
        rule, reason = outcome_rules[result.outcome]
        self._record_resolved(command, resolved, outcome=result.outcome, rule=rule, reason=reason)
        return result

    def _block(self, request: CardBlockRequest, resolved: "_Resolved") -> BlockCardResult:
        customer_id = resolved.customer_id
        assert customer_id is not None
        existing = self._cards.find_block_by_key(request.conversation_id, request.idempotency_key)
        if existing is not None:
            if not existing.same_request(request.card_id, request.reason):
                raise InvalidInputError("idempotency_key", "clave ya usada con otros datos")
            card = self._find_card(customer_id, existing.card_id)
            resolved.card = card
            return BlockCardResult(card, existing, "replayed")
        card = self._find_card(customer_id, request.card_id)
        resolved.card = card
        if card.status is CardStatus.CANCELLED:
            raise CardNotBlockableError("Tarjeta no bloqueable")
        if card.status is CardStatus.BLOCKED:
            return BlockCardResult(
                card, self._cards.find_block_by_card(card.card_id), "already_blocked"
            )
        block = self._cards.block(
            request.conversation_id,
            request.idempotency_key,
            card.card_id,
            request.reason,
            self._clock.now(),
        )
        blocked = OwnedCard(card.card_id, card.last4, CardStatus.BLOCKED)
        return BlockCardResult(blocked, block, "blocked")

    def _find_card(self, customer_id: str, card_id: str) -> OwnedCard:
        card = self._cards.find_customer_card(customer_id, card_id)
        if card is None:
            raise CardNotFoundError("Tarjeta no encontrada")
        return card

    def _record_resolved(
        self,
        command: BlockCardCommand,
        resolved: "_Resolved",
        *,
        outcome: str,
        rule: str,
        reason: str,
        error_code: str | None = None,
    ) -> None:
        self._record(
            command,
            outcome=outcome,
            rule=rule,
            reason=reason,
            customer_id=resolved.customer_id,
            error_code=error_code,
            masked_card=mask_card(resolved.card.last4) if resolved.card is not None else None,
        )

    def _record(
        self,
        command: BlockCardCommand,
        *,
        outcome: str,
        rule: str,
        reason: str,
        customer_id: str | None = None,
        error_code: str | None = None,
        masked_card: str | None = None,
    ) -> None:
        self._audit_log.record(
            AuditEvent(
                conversation_id=command.conversation_id
                if command.conversation_id is not None
                else "",
                timestamp=self._clock.now(),
                tool="bloquear_tarjeta",
                input=None,
                outcome=outcome,
                count=None,
                customer_ids=(),
                error_code=error_code,
                rule=rule,
                reason=reason,
                customer_id=customer_id,
                masked_card=masked_card,
                idempotency_key=_audited_id(command.idempotency_key),
                card_id=_audited_id(command.card_id),
                block_reason=_audited_reason(command.reason),
            )
        )


@dataclass
class _Resolved:
    """Datos que ya se conocen cuando la invocación termina."""

    customer_id: str | None = None
    card: OwnedCard | None = None


def _audited_id(value: str | None) -> str | None:
    """Texto libre válido según RN-005-08, con el PAN redactado; `None` si no es válido."""
    if value is None:
        return None
    text = value.strip()
    if not text or len(text) > MAX_ID_LENGTH:
        return None
    return redact_card_numbers(text)


def _audited_reason(value: str | None) -> str | None:
    """Motivo solo si es un código del catálogo (RN-005-02)."""
    try:
        return BlockReason(value).value
    except ValueError:
        return None
