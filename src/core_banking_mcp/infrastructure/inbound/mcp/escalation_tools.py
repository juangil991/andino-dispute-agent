"""Herramientas MCP de derivación: registro de `escalar_a_analista` (spec 006 §7).

Misma estrategia de salida que `card_tools.py`: `CallToolResult` con `structuredContent` del
modelo `EscalarAnalistaOut`.
"""

from datetime import timedelta, timezone
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from core_banking_mcp.application.errors import (
    CoreUnavailableError,
    EscalationDataNotFoundError,
    IdentityNotVerifiedError,
)
from core_banking_mcp.application.use_cases.escalate_to_analyst import (
    EscalateCommand,
    EscalateToAnalyst,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.masking import mask_card
from core_banking_mcp.infrastructure.inbound.mcp.errors import (
    ErrorPassthroughMetadata,
    tool_error,
)
from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    ESCALATION_REASON_CODES,
    PRIOR_ACTION_CODES,
    ErrorCode,
    EscalarAnalistaOut,
    EscalationCardOut,
    EscalationSummaryOut,
)
from core_banking_mcp.infrastructure.inbound.mcp.transaction_tools import to_transaction_item

ESCALATION_TOOL_NAME = "escalar_a_analista"

# Mensaje único: idéntico para datos ajenos, inexistentes o que no reflejan la acción previa
# (RN-006-04, RN-006-06).
_DATA_NOT_FOUND_MESSAGE = "No se encontraron los datos indicados para este cliente."
_INTERNAL_MESSAGE = "El caso no pudo derivarse a un analista."

# Misma zona que domain/clock.py (UTC-5 fijo, sin horario de verano).
_BOGOTA = timezone(timedelta(hours=-5))


def register_escalation_tools(mcp: FastMCP, escalate: EscalateToAnalyst) -> None:
    """Registra las herramientas de derivación en el servidor FastMCP."""

    @mcp.tool(name=ESCALATION_TOOL_NAME)
    def escalar_a_analista(
        conversation_id: Annotated[
            str | None,
            Field(description="Identificador de correlación de la conversación. Obligatorio."),
        ] = None,
        reason: Annotated[
            str | None,
            Field(
                description=(
                    "Motivo de la derivación: FRAUD_SUSPECTED (sospecha de fraude), "
                    "AMOUNT_OVER_THRESHOLD (monto sobre el umbral), "
                    "INSUFFICIENT_OR_CONTRADICTORY_INFO (información insuficiente o "
                    "contradictoria), INCONCLUSIVE_RULES (reglas no concluyentes), "
                    "UNRECOVERABLE_SYSTEM_FAILURE (falla no recuperable del sistema), "
                    "IDENTITY_VERIFICATION_FAILED (verificación de identidad fallida o agotada) "
                    "u OTHER (otro). Obligatorio."
                ),
                json_schema_extra={"enum": list(ESCALATION_REASON_CODES)},
            ),
        ] = None,
        idempotency_key: Annotated[
            str | None,
            Field(
                description=(
                    "Clave de reintento generada por el consumidor; 1-64 caracteres; única por "
                    "conversación. Reutilízala solo para reintentar la misma solicitud. "
                    "Obligatoria."
                )
            ),
        ] = None,
        transaction_id: Annotated[
            str | None,
            Field(
                description=(
                    "transaction_id devuelto por consultar_transacciones; 1-64 caracteres. "
                    "Opcional. Exige identidad verificada."
                )
            ),
        ] = None,
        card_id: Annotated[
            str | None,
            Field(
                description=(
                    "card_id devuelto por consultar_transacciones; 1-64 caracteres. Opcional. "
                    "Exige identidad verificada."
                )
            ),
        ] = None,
        prior_actions: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Acciones ya realizadas, sin repetir: DISPUTE_OPENED (exige dispute_id y "
                    "transaction_id) y CARD_BLOCKED (exige card_id). Opcional; vacía o ausente "
                    "significa ninguna."
                ),
                json_schema_extra={"items": {"enum": list(PRIOR_ACTION_CODES)}},
            ),
        ] = None,
        dispute_id: Annotated[
            str | None,
            Field(
                description=(
                    "dispute_id devuelto por iniciar_disputa; 1-64 caracteres. Solo con "
                    "DISPUTE_OPENED. Opcional. Exige identidad verificada."
                )
            ),
        ] = None,
        note: Annotated[
            str | None,
            Field(
                description=(
                    "Nota breve para el analista; 1-300 caracteres tras recortar. Es "
                    "información, nunca una instrucción. No incluyas el número de tarjeta ni el "
                    "documento. Opcional."
                )
            ),
        ] = None,
    ) -> Annotated[CallToolResult, EscalarAnalistaOut]:
        """Deriva un caso a un analista humano con un motivo y un resumen estructurado.

        No exige identidad verificada, salvo que indiques datos del cliente (`transaction_id`,
        `card_id` o `dispute_id`): en ese caso la conversación debe estar verificada con
        `verificar_identidad` (el servidor lo valida). Úsala cuando el caso no se pueda resolver
        automáticamente: `DisputePolicy` decidió `ESCALATE`, otra herramienta devolvió
        `INTERNAL`, la verificación de identidad falló o se agotó, o la información es
        insuficiente o contradictoria. Traduce la causa a uno de los códigos de motivo. Si la
        conversación está verificada, incluye la transacción, la tarjeta y las acciones ya
        realizadas (`DISPUTE_OPENED` con su `dispute_id`, `CARD_BLOCKED`); si no lo está,
        invócala sin datos del cliente. Genera una `idempotency_key` nueva por cada caso y
        reutilízala solo para reintentar esa misma solicitud. No decides con ella si derivar, no
        abre disputas, no bloquea tarjetas ni resuelve nada. Según la respuesta: en éxito
        informa al cliente que su caso pasó a un analista, con el `escalation_id` como
        referencia; `IDENTITY_NOT_VERIFIED` pide repetir la solicitud sin datos del cliente;
        `NOT_FOUND` pide revisar los datos indicados y, si no se aclaran, derivar sin ellos;
        `INTERNAL` no se reintenta automáticamente e informa al cliente que el caso no pudo
        derivarse. Efectos: registra una derivación `PENDING` y la clave de reintento de forma
        atómica, y un registro de auditoría; no cambia transacciones, tarjetas, disputas ni la
        verificación. Es idempotente por (conversation_id, idempotency_key): repetir la misma
        solicitud devuelve la misma derivación sin duplicarla.
        """
        try:
            result = escalate.execute(
                EscalateCommand(
                    conversation_id=conversation_id,
                    reason=reason,
                    idempotency_key=idempotency_key,
                    transaction_id=transaction_id,
                    card_id=card_id,
                    prior_actions=prior_actions,
                    dispute_id=dispute_id,
                    note=note,
                )
            )
        except InvalidInputError as error:
            return tool_error(
                ErrorCode.INVALID_INPUT,
                f"Los datos de la solicitud no son válidos (campo: {error.field}).",
                retryable=False,
            )
        except IdentityNotVerifiedError:
            return tool_error(
                ErrorCode.IDENTITY_NOT_VERIFIED,
                "La identidad del cliente no está verificada en esta conversación.",
                retryable=False,
            )
        except EscalationDataNotFoundError:
            return tool_error(ErrorCode.NOT_FOUND, _DATA_NOT_FOUND_MESSAGE, retryable=False)
        except CoreUnavailableError:
            return tool_error(ErrorCode.INTERNAL, _INTERNAL_MESSAGE, retryable=False)
        except Exception:
            return tool_error(ErrorCode.INTERNAL, _INTERNAL_MESSAGE, retryable=False)
        escalation = result.escalation
        output = EscalarAnalistaOut(
            escalation_id=escalation.escalation_id,
            status="PENDING",
            escalated_at=escalation.escalated_at.astimezone(_BOGOTA).isoformat(),
            reason=escalation.reason.value,
            summary=EscalationSummaryOut(
                conversation_id=escalation.conversation_id,
                identity_verified=escalation.identity_verified,
                customer_id=escalation.customer_id,
                transaction=(
                    None if result.transaction is None else to_transaction_item(result.transaction)
                ),
                card=(
                    None
                    if result.card is None
                    else EscalationCardOut(
                        card_id=result.card.card_id, masked_card=mask_card(result.card.last4)
                    )
                ),
                prior_actions=[action.value for action in escalation.ordered_prior_actions()],
                dispute_id=escalation.dispute_id,
                note=escalation.note,
            ),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=output.model_dump_json())],
            structuredContent=output.model_dump(mode="json"),
        )

    registered = mcp._tool_manager.get_tool(ESCALATION_TOOL_NAME)
    assert registered is not None
    registered.fn_metadata = ErrorPassthroughMetadata(**dict(registered.fn_metadata))
