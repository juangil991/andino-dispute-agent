"""Caso de uso: búsqueda de clientes (RN-001-01/06/07/10/11)."""

from dataclasses import dataclass

from core_banking_mcp.application.errors import CoreUnavailableError
from core_banking_mcp.application.ports.audit_log import AuditEvent, AuditInput, AuditLogPort
from core_banking_mcp.application.ports.clock import Clock
from core_banking_mcp.application.ports.customer_repository import CustomerRepository
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.masking import mask_document
from core_banking_mcp.domain.models.search import (
    MAX_RESULTS,
    CustomerSearchResult,
    SearchCriteria,
)


@dataclass(frozen=True)
class SearchCustomersCommand:
    conversation_id: str | None
    document: str | None
    full_name: str | None
    card_last4: str | None


class SearchCustomers:
    def __init__(
        self,
        repository: CustomerRepository,
        audit_log: AuditLogPort,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._audit_log = audit_log
        self._clock = clock

    def execute(self, command: SearchCustomersCommand) -> CustomerSearchResult:
        try:
            if not command.conversation_id:
                raise InvalidInputError("conversation_id", "es obligatorio")
            criteria = SearchCriteria.create(
                command.document, command.full_name, command.card_last4
            )
        except InvalidInputError as error:
            self._record(
                command,
                outcome="error",
                error_code="INVALID_INPUT",
                rule="RN-001-05",
                reason="Entrada inválida",
            )
            raise error
        try:
            matches = self._repository.find_matching(criteria, MAX_RESULTS + 1)
        except Exception as error:
            self._record(
                command,
                outcome="error",
                error_code="INTERNAL",
                rule="RN-001-13",
                reason="Falla inesperada del core bancario",
            )
            raise CoreUnavailableError("Core bancario no disponible") from error
        result = CustomerSearchResult.from_matches(matches)
        if result.refinement_required:
            self._record(
                command,
                outcome="refinement_required",
                count=0,
                rule="RN-001-07",
                reason="Más de 5 coincidencias; se pide refinar",
            )
        else:
            self._record(
                command,
                outcome="found",
                count=len(result.customers),
                customer_ids=tuple(c.customer_id for c in result.customers),
                rule="RN-001-01",
                reason="Búsqueda resuelta",
            )
        return result

    def _record(
        self,
        command: SearchCustomersCommand,
        *,
        outcome: str,
        rule: str,
        reason: str,
        count: int | None = None,
        customer_ids: tuple[str, ...] = (),
        error_code: str | None = None,
    ) -> None:
        document = mask_document(command.document.strip()) if command.document is not None else None
        self._audit_log.record(
            AuditEvent(
                conversation_id=command.conversation_id,
                timestamp=self._clock.now(),
                tool="buscar_cliente",
                input=AuditInput(document, command.full_name, command.card_last4),
                outcome=outcome,
                count=count,
                customer_ids=customer_ids,
                error_code=error_code,
                rule=rule,
                reason=reason,
            )
        )
