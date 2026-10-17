"""Caso de uso: verificación de identidad (RN-002-01…16)."""

from dataclasses import dataclass

from core_banking_mcp.application.errors import CoreUnavailableError
from core_banking_mcp.application.ports.audit_log import AuditEvent, AuditLogPort
from core_banking_mcp.application.ports.clock import Clock
from core_banking_mcp.application.ports.conversation_verification_store import (
    ConversationVerificationStore,
)
from core_banking_mcp.application.ports.customer_repository import CustomerRepository
from core_banking_mcp.domain.clock import today_in_bogota
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.identity_verification import (
    VerificationDecision,
    VerificationOutcome,
    evaluate_verification,
)
from core_banking_mcp.domain.models.identity import (
    IdentityRecord,
    VerificationRequest,
    VerificationState,
)


@dataclass(frozen=True)
class VerifyIdentityCommand:
    conversation_id: str | None
    customer_id: str | None
    birth_date: str | None
    document_issue_date: str | None


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    attempts_remaining: int
    escalation_required: bool


TOOL_NAME = "verificar_identidad"


def _describe(previous: VerificationState, decision: VerificationDecision) -> tuple[str, str, str]:
    """Resultado, regla y motivo (sin fechas) que se auditan."""
    match decision.outcome:
        case VerificationOutcome.VERIFIED:
            return "verified", "RN-002-02", "Ambas fechas coinciden con las registradas"
        case VerificationOutcome.ALREADY_VERIFIED:
            return "already_verified", "RN-002-11", "Conversación ya verificada para el cliente"
        case VerificationOutcome.OTHER_CUSTOMER:
            return "other_customer", "RN-002-10", "Conversación verificada para otro cliente"
        case VerificationOutcome.FAILED:
            return "failed", "RN-002-03", "Verificación no exitosa"
        case VerificationOutcome.LOCKED:
            if previous.is_locked:
                return "locked", "RN-002-05", "Conversación ya bloqueada por intentos fallidos"
            return "locked", "RN-002-04", "Tercer intento fallido: conversación bloqueada"


def _needs_identity(state: VerificationState) -> bool:
    """Solo se comparan fechas si la conversación no está verificada ni bloqueada."""
    return state.verified_customer_id is None and not state.is_locked


class VerifyIdentity:
    def __init__(
        self,
        repository: CustomerRepository,
        store: ConversationVerificationStore,
        audit_log: AuditLogPort,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._store = store
        self._audit_log = audit_log
        self._clock = clock

    def execute(self, command: VerifyIdentityCommand) -> VerificationResult:
        today = today_in_bogota(self._clock.now())
        try:
            request = VerificationRequest.create(
                command.conversation_id,
                command.customer_id,
                command.birth_date,
                command.document_issue_date,
                today,
            )
        except InvalidInputError:
            self._record(
                command.conversation_id,
                command.customer_id,
                "error",
                "RN-002-07",
                "Datos de entrada inválidos",
                error_code="INVALID_INPUT",
            )
            raise
        try:
            state = self._store.get(request.conversation_id)
            identity: IdentityRecord | None = None
            if _needs_identity(state):
                identity = self._repository.find_identity(request.customer_id)
            decision = evaluate_verification(state, request, identity)
            self._store.save(request.conversation_id, decision.state)
        except Exception as error:
            self._record(
                request.conversation_id,
                request.customer_id,
                "error",
                "RN-002-16",
                "Falla inesperada del core bancario",
                error_code="INTERNAL",
            )
            raise CoreUnavailableError("Core bancario no disponible") from error
        outcome, rule, reason = _describe(state, decision)
        self._record(
            request.conversation_id,
            request.customer_id,
            outcome,
            rule,
            reason,
            intento=decision.state.failed_attempts
            if decision.outcome is VerificationOutcome.FAILED
            else None,
        )
        return VerificationResult(
            decision.verified,
            decision.state.attempts_remaining,
            decision.escalation_required,
        )

    def _record(
        self,
        conversation_id: str | None,
        customer_id: str | None,
        outcome: str,
        rule: str,
        reason: str,
        error_code: str | None = None,
        intento: int | None = None,
    ) -> None:
        self._audit_log.record(
            AuditEvent(
                conversation_id=conversation_id if conversation_id is not None else "",
                timestamp=self._clock.now(),
                tool=TOOL_NAME,
                input=None,
                outcome=outcome,
                count=None,
                customer_ids=(),
                error_code=error_code,
                rule=rule,
                reason=reason,
                customer_id=customer_id,
                intento=intento,
            )
        )
