"""Caso de uso: abrir una disputa sobre una transacción (RN-004-01…15)."""

from dataclasses import dataclass

from core_banking_mcp.application.errors import (
    CoreUnavailableError,
    DisputeAlreadyOpenError,
    IdentityNotVerifiedError,
    TransactionNotDisputableError,
    TransactionNotFoundError,
)
from core_banking_mcp.application.ports.audit_log import AuditEvent, AuditLogPort
from core_banking_mcp.application.ports.clock import Clock
from core_banking_mcp.application.ports.conversation_verification_store import (
    ConversationVerificationStore,
)
from core_banking_mcp.application.ports.dispute_repository import DisputeRepository
from core_banking_mcp.application.ports.transaction_repository import TransactionRepository
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.masking import redact_card_numbers
from core_banking_mcp.domain.models.dispute import (
    MAX_ID_LENGTH,
    Dispute,
    DisputeReason,
    DisputeRequest,
    DisputeStatus,
)
from core_banking_mcp.domain.models.transaction import Transaction, TransactionStatus


@dataclass(frozen=True)
class OpenDisputeCommand:
    conversation_id: str | None
    transaction_id: str | None
    reason: str | None
    idempotency_key: str | None


@dataclass(frozen=True)
class OpenDisputeResult:
    dispute: Dispute
    transaction: Transaction
    replayed: bool


class OpenDispute:
    def __init__(
        self,
        transactions: TransactionRepository,
        disputes: DisputeRepository,
        store: ConversationVerificationStore,
        audit_log: AuditLogPort,
        clock: Clock,
    ) -> None:
        self._transactions = transactions
        self._disputes = disputes
        self._store = store
        self._audit_log = audit_log
        self._clock = clock

    def execute(self, command: OpenDisputeCommand) -> OpenDisputeResult:
        try:
            request = DisputeRequest.create(
                command.conversation_id,
                command.transaction_id,
                command.reason,
                command.idempotency_key,
            )
        except InvalidInputError:
            self._record(
                command,
                outcome="error",
                error_code="INVALID_INPUT",
                rule="RN-004-09",
                reason="Entrada inválida",
            )
            raise
        customer_id: str | None = None
        try:
            customer_id = self._store.get(request.conversation_id).verified_customer_id
            if customer_id is None:
                raise IdentityNotVerifiedError("Identidad no verificada")
            result = self._open(request, customer_id)
        except IdentityNotVerifiedError:
            self._record(
                command,
                outcome="error",
                error_code="IDENTITY_NOT_VERIFIED",
                rule="RN-004-03",
                reason="Conversación sin verificación de identidad",
            )
            raise
        except InvalidInputError:
            self._record(
                command,
                outcome="error",
                customer_id=customer_id,
                error_code="INVALID_INPUT",
                rule="RN-004-08",
                reason="Clave de reintento ya usada con otra transacción u otro motivo",
            )
            raise
        except TransactionNotFoundError:
            self._record(
                command,
                outcome="error",
                customer_id=customer_id,
                error_code="NOT_FOUND",
                rule="RN-004-04",
                reason="La transacción no existe o no es del cliente verificado",
            )
            raise
        except TransactionNotDisputableError:
            self._record(
                command,
                outcome="error",
                customer_id=customer_id,
                error_code="TRANSACTION_NOT_DISPUTABLE",
                rule="RN-004-05",
                reason="Solo se puede disputar una transacción confirmada",
            )
            raise
        except DisputeAlreadyOpenError as error:
            self._record(
                command,
                outcome="error",
                customer_id=customer_id,
                error_code="DISPUTE_ALREADY_OPEN",
                dispute_id=error.dispute_id,
                rule="RN-004-07",
                reason="La transacción ya tiene una disputa abierta",
            )
            raise
        except Exception as error:
            self._record(
                command,
                outcome="error",
                customer_id=customer_id,
                error_code="INTERNAL",
                rule="RN-004-15",
                reason="Falla inesperada del core bancario",
            )
            raise CoreUnavailableError("Core bancario no disponible") from error
        if result.replayed:
            self._record(
                command,
                outcome="replayed",
                customer_id=customer_id,
                dispute_id=result.dispute.dispute_id,
                rule="RN-004-08",
                reason="Repetición de la solicitud; se devuelve la disputa existente",
            )
        else:
            self._record(
                command,
                outcome="opened",
                customer_id=customer_id,
                dispute_id=result.dispute.dispute_id,
                rule="RN-004-11",
                reason="Disputa abierta",
            )
        return result

    def _open(self, request: DisputeRequest, customer_id: str) -> OpenDisputeResult:
        existing = self._disputes.find_by_idempotency_key(
            request.conversation_id, request.idempotency_key
        )
        if existing is not None:
            return self._replay(existing, request, customer_id)
        transaction = self._find_transaction(customer_id, request.transaction_id)
        if transaction.status is not TransactionStatus.CONFIRMED:
            raise TransactionNotDisputableError("Transacción no disputable")
        open_dispute = self._disputes.find_open_by_transaction(request.transaction_id)
        if open_dispute is not None:
            raise DisputeAlreadyOpenError(open_dispute.dispute_id)
        dispute = self._disputes.add(
            request.conversation_id,
            request.idempotency_key,
            request.transaction_id,
            request.reason,
            DisputeStatus.OPEN,
            self._clock.now(),
        )
        return OpenDisputeResult(dispute, transaction, replayed=False)

    def _replay(
        self, existing: Dispute, request: DisputeRequest, customer_id: str
    ) -> OpenDisputeResult:
        if not existing.same_request(request.transaction_id, request.reason):
            raise InvalidInputError("idempotency_key", "clave ya usada con otros datos")
        transaction = self._find_transaction(customer_id, existing.transaction_id)
        return OpenDisputeResult(existing, transaction, replayed=True)

    def _find_transaction(self, customer_id: str, transaction_id: str) -> Transaction:
        transaction = self._transactions.find_customer_transaction(customer_id, transaction_id)
        if transaction is None:
            raise TransactionNotFoundError("Transacción no encontrada")
        return transaction

    def _record(
        self,
        command: OpenDisputeCommand,
        *,
        outcome: str,
        rule: str,
        reason: str,
        customer_id: str | None = None,
        error_code: str | None = None,
        dispute_id: str | None = None,
    ) -> None:
        self._audit_log.record(
            AuditEvent(
                conversation_id=command.conversation_id
                if command.conversation_id is not None
                else "",
                timestamp=self._clock.now(),
                tool="iniciar_disputa",
                input=None,
                outcome=outcome,
                count=None,
                customer_ids=(),
                error_code=error_code,
                rule=rule,
                reason=reason,
                customer_id=customer_id,
                transaction_id=_audited_id(command.transaction_id),
                dispute_reason=_audited_reason(command.reason),
                idempotency_key=_audited_id(command.idempotency_key),
                dispute_id=dispute_id,
            )
        )


def _audited_id(value: str | None) -> str | None:
    """Texto libre válido según RN-004-09, con el PAN redactado; `None` si no es válido."""
    if value is None:
        return None
    text = value.strip()
    if not text or len(text) > MAX_ID_LENGTH:
        return None
    return redact_card_numbers(text)


def _audited_reason(value: str | None) -> str | None:
    """Motivo solo si es un código del catálogo (RN-004-02)."""
    try:
        return DisputeReason(value).value
    except ValueError:
        return None
