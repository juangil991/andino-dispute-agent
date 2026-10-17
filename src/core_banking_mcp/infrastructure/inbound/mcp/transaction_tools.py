"""Herramientas MCP de transacciones: registro de `consultar_transacciones` (spec 003 §7).

Misma estrategia de salida que `identity_tools.py`: `CallToolResult` con `structuredContent`
del modelo `ConsultarTransaccionesOut`. Los errores se devuelven como sobre
`{code, message, retryable}` (`tool_error`) con mensajes fijos, sin el valor recibido.
"""

from datetime import timedelta, timezone
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from core_banking_mcp.application.errors import (
    CardNotFoundError,
    CoreUnavailableError,
    IdentityNotVerifiedError,
)
from core_banking_mcp.application.use_cases.list_card_transactions import (
    ListCardTransactions,
    ListCardTransactionsCommand,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.masking import mask_card
from core_banking_mcp.domain.models.transaction import Transaction
from core_banking_mcp.infrastructure.inbound.mcp.errors import (
    ErrorPassthroughMetadata,
    tool_error,
)
from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    ConsultarTransaccionesOut,
    ErrorCode,
    TransactionItemOut,
)

TRANSACTIONS_TOOL_NAME = "consultar_transacciones"

# Mensaje único: idéntico para tarjeta ajena e inexistente (RN-003-04).
_CARD_NOT_FOUND_MESSAGE = "No se encontró una tarjeta del cliente con esos últimos 4 dígitos."

# Misma zona que domain/clock.py (UTC-5 fijo, sin horario de verano).
_BOGOTA = timezone(timedelta(hours=-5))


def _to_item(transaction: Transaction) -> TransactionItemOut:
    return TransactionItemOut(
        transaction_id=transaction.transaction_id,
        occurred_at=transaction.occurred_at.astimezone(_BOGOTA).isoformat(),
        merchant=transaction.merchant,
        amount=f"{transaction.amount:.2f}",
        currency=transaction.currency,
        status=transaction.status.value,
        card_id=transaction.card_id,
        masked_card=mask_card(transaction.card_last4),
    )


def register_transaction_tools(mcp: FastMCP, list_card_transactions: ListCardTransactions) -> None:
    """Registra las herramientas de transacciones en el servidor FastMCP."""

    @mcp.tool(name=TRANSACTIONS_TOOL_NAME)
    def consultar_transacciones(
        conversation_id: Annotated[
            str | None,
            Field(description="Identificador de correlación de la conversación. Obligatorio."),
        ] = None,
        card_last4: Annotated[
            str | None,
            Field(description="Últimos 4 dígitos de la tarjeta (exactamente 4 dígitos 0-9)."),
        ] = None,
        date_from: Annotated[
            str | None,
            Field(
                description=(
                    "Fecha inicial AAAA-MM-DD, incluida; existente y no posterior a date_to. "
                    "Obligatoria."
                )
            ),
        ] = None,
        date_to: Annotated[
            str | None,
            Field(
                description=(
                    "Fecha final AAAA-MM-DD, incluida; existente, no posterior a hoy (Bogotá) "
                    "y a lo sumo 89 días después de date_from. Obligatoria."
                )
            ),
        ] = None,
    ) -> Annotated[CallToolResult, ConsultarTransaccionesOut]:
        """Lista las transacciones de una tarjeta del cliente verificado en un rango de fechas.

        Úsala solo después de que `verificar_identidad` haya respondido `verified=true` en la
        conversación; el servidor lo valida. Pide al cliente los últimos 4 dígitos de la tarjeta
        y el periodo (hasta 90 días). No sirve para localizar clientes ni para verificar
        identidad. Si responde `refinement_required=true` (más de 50 transacciones, lista
        vacía), pide un rango más corto; si responde `NOT_FOUND`, pide al cliente que revise los
        dígitos de la tarjeta; si responde `INTERNAL`, no reintentes y deriva a un analista.
        Es de solo lectura e idempotente: su único efecto es un registro de auditoría.
        """
        try:
            result = list_card_transactions.execute(
                ListCardTransactionsCommand(
                    conversation_id=conversation_id,
                    card_last4=card_last4,
                    date_from=date_from,
                    date_to=date_to,
                )
            )
        except InvalidInputError as error:
            return tool_error(
                ErrorCode.INVALID_INPUT,
                f"Los datos de la consulta no son válidos (campo: {error.field}).",
                retryable=False,
            )
        except IdentityNotVerifiedError:
            return tool_error(
                ErrorCode.IDENTITY_NOT_VERIFIED,
                "La identidad del cliente no está verificada en esta conversación.",
                retryable=False,
            )
        except CardNotFoundError:
            return tool_error(ErrorCode.NOT_FOUND, _CARD_NOT_FOUND_MESSAGE, retryable=False)
        except CoreUnavailableError:
            return tool_error(
                ErrorCode.INTERNAL,
                "El sistema de consulta de transacciones no está disponible.",
                retryable=False,
            )
        except Exception:
            return tool_error(
                ErrorCode.INTERNAL,
                "Ocurrió un error interno al consultar las transacciones.",
                retryable=False,
            )
        output = ConsultarTransaccionesOut(
            transactions=[_to_item(transaction) for transaction in result.transactions],
            refinement_required=result.refinement_required,
        )
        return CallToolResult(
            content=[TextContent(type="text", text=output.model_dump_json())],
            structuredContent=output.model_dump(mode="json"),
        )

    registered = mcp._tool_manager.get_tool(TRANSACTIONS_TOOL_NAME)
    assert registered is not None
    registered.fn_metadata = ErrorPassthroughMetadata(**dict(registered.fn_metadata))
