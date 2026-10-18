"""Herramientas MCP de disputas: registro de `iniciar_disputa` (spec 004 §7).

Misma estrategia de salida que `transaction_tools.py`: `CallToolResult` con `structuredContent`
del modelo `IniciarDisputaOut`. Los errores se devuelven como sobre `{code, message, retryable}`
(`tool_error`) con mensajes fijos, sin el valor recibido (solo el `dispute_id` existente).
"""

from datetime import timedelta, timezone
from typing import Annotated, Literal, cast

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from core_banking_mcp.application.errors import (
    CoreUnavailableError,
    DisputeAlreadyOpenError,
    IdentityNotVerifiedError,
    TransactionNotDisputableError,
    TransactionNotFoundError,
)
from core_banking_mcp.application.use_cases.open_dispute import (
    OpenDispute,
    OpenDisputeCommand,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.infrastructure.inbound.mcp.errors import (
    ErrorPassthroughMetadata,
    tool_error,
)
from core_banking_mcp.infrastructure.inbound.mcp.schemas import ErrorCode, IniciarDisputaOut
from core_banking_mcp.infrastructure.inbound.mcp.transaction_tools import to_transaction_item

DISPUTE_TOOL_NAME = "iniciar_disputa"

# Mensaje único: idéntico para transacción ajena e inexistente (RN-004-04).
_TRANSACTION_NOT_FOUND_MESSAGE = "No se encontró la transacción indicada para este cliente."

# Misma zona que domain/clock.py (UTC-5 fijo, sin horario de verano).
_BOGOTA = timezone(timedelta(hours=-5))


def register_dispute_tools(mcp: FastMCP, open_dispute: OpenDispute) -> None:
    """Registra las herramientas de disputas en el servidor FastMCP."""

    @mcp.tool(name=DISPUTE_TOOL_NAME)
    def iniciar_disputa(
        conversation_id: Annotated[
            str | None,
            Field(description="Identificador de correlación de la conversación. Obligatorio."),
        ] = None,
        transaction_id: Annotated[
            str | None,
            Field(
                description=(
                    "transaction_id devuelto por consultar_transacciones; 1-64 caracteres. "
                    "Obligatorio."
                )
            ),
        ] = None,
        reason: Annotated[
            str | None,
            Field(
                description=(
                    "Motivo de la disputa: UNRECOGNIZED_CHARGE (no reconoce el cargo), "
                    "DUPLICATE_CHARGE (cobro duplicado), INCORRECT_AMOUNT (monto incorrecto), "
                    "NOT_RECEIVED (producto o servicio no recibido) u OTHER (otro). Obligatorio."
                ),
                json_schema_extra={
                    "enum": [
                        "UNRECOGNIZED_CHARGE",
                        "DUPLICATE_CHARGE",
                        "INCORRECT_AMOUNT",
                        "NOT_RECEIVED",
                        "OTHER",
                    ]
                },
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
    ) -> Annotated[CallToolResult, IniciarDisputaOut]:
        """Abre una disputa sobre una transacción confirmada del cliente verificado.

        Úsala solo después de que `verificar_identidad` haya respondido `verified=true` en la
        conversación (el servidor lo valida) y con un `transaction_id` devuelto por
        `consultar_transacciones`. Traduce lo que dice el cliente a uno de los códigos de
        motivo y genera una `idempotency_key` nueva por cada disputa que quieras abrir; reutilízala
        solo para reintentar esa misma solicitud. No decide si la disputa procede, no bloquea
        tarjetas ni escala. Registra una disputa `OPEN` y la clave de reintento de forma atómica,
        y un registro de auditoría. Es idempotente por (conversation_id, idempotency_key): repetir
        la misma solicitud devuelve la misma disputa sin duplicarla.
        """
        try:
            result = open_dispute.execute(
                OpenDisputeCommand(
                    conversation_id=conversation_id,
                    transaction_id=transaction_id,
                    reason=reason,
                    idempotency_key=idempotency_key,
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
        except TransactionNotFoundError:
            return tool_error(ErrorCode.NOT_FOUND, _TRANSACTION_NOT_FOUND_MESSAGE, retryable=False)
        except TransactionNotDisputableError:
            return tool_error(
                ErrorCode.TRANSACTION_NOT_DISPUTABLE,
                "Solo se pueden disputar transacciones confirmadas.",
                retryable=False,
            )
        except DisputeAlreadyOpenError as error:
            return tool_error(
                ErrorCode.DISPUTE_ALREADY_OPEN,
                f"La transacción ya tiene una disputa abierta: {error.dispute_id}.",
                retryable=False,
            )
        except CoreUnavailableError:
            return tool_error(
                ErrorCode.INTERNAL,
                "El sistema de disputas no está disponible.",
                retryable=False,
            )
        except Exception:
            return tool_error(
                ErrorCode.INTERNAL,
                "Ocurrió un error interno al abrir la disputa.",
                retryable=False,
            )
        dispute = result.dispute
        output = IniciarDisputaOut(
            dispute_id=dispute.dispute_id,
            status=cast(Literal["OPEN"], dispute.status.value),
            opened_at=dispute.opened_at.astimezone(_BOGOTA).isoformat(),
            reason=dispute.reason.value,
            transaction=to_transaction_item(result.transaction),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=output.model_dump_json())],
            structuredContent=output.model_dump(mode="json"),
        )

    registered = mcp._tool_manager.get_tool(DISPUTE_TOOL_NAME)
    assert registered is not None
    registered.fn_metadata = ErrorPassthroughMetadata(**dict(registered.fn_metadata))
