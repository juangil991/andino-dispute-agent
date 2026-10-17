"""Caso de uso: consultar las transacciones de una tarjeta (RN-003-01…16)."""

from dataclasses import dataclass

from core_banking_mcp.application.errors import (
    CardNotFoundError,
    CoreUnavailableError,
    IdentityNotVerifiedError,
)
from core_banking_mcp.application.ports.audit_log import AuditEvent, AuditLogPort
from core_banking_mcp.application.ports.clock import Clock
from core_banking_mcp.application.ports.conversation_verification_store import (
    ConversationVerificationStore,
)
from core_banking_mcp.application.ports.transaction_repository import TransactionRepository
from core_banking_mcp.domain.clock import today_in_bogota
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.masking import mask_card
from core_banking_mcp.domain.models.transaction import (
    MAX_TRANSACTIONS,
    TransactionListResult,
    TransactionQuery,
    validate_last4,
)


@dataclass(frozen=True)
class ListCardTransactionsCommand:
    conversation_id: str | None
    card_last4: str | None
    date_from: str | None
    date_to: str | None


class ListCardTransactions:
    def __init__(
        self,
        repository: TransactionRepository,
        store: ConversationVerificationStore,
        audit_log: AuditLogPort,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._store = store
        self._audit_log = audit_log
        self._clock = clock

    def execute(self, command: ListCardTransactionsCommand) -> TransactionListResult:
        try:
            query = TransactionQuery.create(
                command.conversation_id,
                command.card_last4,
                command.date_from,
                command.date_to,
                today_in_bogota(self._clock.now()),
            )
        except InvalidInputError as error:
            self._record(
                command,
                outcome="error",
                error_code="INVALID_INPUT",
                rule="RN-003-06",
                reason="Entrada inválida",
            )
            raise error
        customer_id: str | None = None
        try:
            customer_id = self._store.get(query.conversation_id).verified_customer_id
            if customer_id is None:
                raise IdentityNotVerifiedError("Identidad no verificada")
            cards = self._repository.find_customer_cards(customer_id, query.card_last4)
            if not cards:
                raise CardNotFoundError("Tarjeta no encontrada")
            start, end = query.date_range.utc_bounds()
            matches = self._repository.find_transactions(
                [card.card_id for card in cards], start, end, MAX_TRANSACTIONS + 1
            )
        except IdentityNotVerifiedError:
            self._record(
                command,
                outcome="error",
                error_code="IDENTITY_NOT_VERIFIED",
                rule="RN-003-02",
                reason="Conversación sin verificación de identidad",
            )
            raise
        except CardNotFoundError:
            self._record(
                command,
                outcome="error",
                customer_id=customer_id,
                error_code="NOT_FOUND",
                rule="RN-003-04",
                reason="El cliente verificado no tiene la tarjeta indicada",
            )
            raise
        except Exception as error:
            self._record(
                command,
                outcome="error",
                customer_id=customer_id,
                error_code="INTERNAL",
                rule="RN-003-16",
                reason="Falla inesperada del core bancario",
            )
            raise CoreUnavailableError("Core bancario no disponible") from error
        result = TransactionListResult.from_matches(matches)
        if result.refinement_required:
            self._record(
                command,
                outcome="refinement_required",
                customer_id=customer_id,
                count=0,
                rule="RN-003-10",
                reason="Más de 50 coincidencias; se pide acotar el rango",
            )
        else:
            self._record(
                command,
                outcome="found",
                customer_id=customer_id,
                count=len(result.transactions),
                transaction_ids=tuple(t.transaction_id for t in result.transactions),
                rule="RN-003-05",
                reason="Consulta resuelta",
            )
        return result

    def _record(
        self,
        command: ListCardTransactionsCommand,
        *,
        outcome: str,
        rule: str,
        reason: str,
        customer_id: str | None = None,
        count: int | None = None,
        transaction_ids: tuple[str, ...] = (),
        error_code: str | None = None,
    ) -> None:
        card_last4 = command.card_last4
        try:
            if card_last4 is None:
                raise InvalidInputError("card_last4", "debe tener exactamente 4 dígitos")
            validate_last4("card_last4", card_last4)
            masked_card: str | None = mask_card(card_last4)
        except InvalidInputError:
            masked_card = None
        self._audit_log.record(
            AuditEvent(
                conversation_id=command.conversation_id
                if command.conversation_id is not None
                else "",
                timestamp=self._clock.now(),
                tool="consultar_transacciones",
                input=None,
                outcome=outcome,
                count=count,
                customer_ids=(),
                error_code=error_code,
                rule=rule,
                reason=reason,
                customer_id=customer_id,
                masked_card=masked_card,
                date_from=command.date_from,
                date_to=command.date_to,
                transaction_ids=transaction_ids,
            )
        )
