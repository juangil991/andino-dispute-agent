"""Herramientas MCP de tarjetas: registro de `bloquear_tarjeta` (spec 005 §7).

Misma estrategia de salida que `dispute_tools.py`: `CallToolResult` con `structuredContent` del
modelo `BloquearTarjetaOut`.
"""

from datetime import timedelta, timezone
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from core_banking_mcp.application.errors import (
    CardNotBlockableError,
    CardNotFoundError,
    CoreUnavailableError,
    IdentityNotVerifiedError,
)
from core_banking_mcp.application.use_cases.block_card import BlockCard, BlockCardCommand
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.masking import mask_card
from core_banking_mcp.infrastructure.inbound.mcp.errors import (
    ErrorPassthroughMetadata,
    tool_error,
)
from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    BLOCK_REASON_CODES,
    BloquearTarjetaOut,
    ErrorCode,
)

CARD_TOOL_NAME = "bloquear_tarjeta"

# Mensaje único: idéntico para tarjeta ajena e inexistente (RN-005-04).
_CARD_NOT_FOUND_MESSAGE = "No se encontró la tarjeta indicada para este cliente."

# Misma zona que domain/clock.py (UTC-5 fijo, sin horario de verano).
_BOGOTA = timezone(timedelta(hours=-5))


def register_card_tools(mcp: FastMCP, block_card: BlockCard) -> None:
    """Registra las herramientas de tarjetas en el servidor FastMCP."""

    @mcp.tool(name=CARD_TOOL_NAME)
    def bloquear_tarjeta(
        conversation_id: Annotated[
            str | None,
            Field(description="Identificador de correlación de la conversación. Obligatorio."),
        ] = None,
        card_id: Annotated[
            str | None,
            Field(
                description=(
                    "card_id devuelto por consultar_transacciones; 1-64 caracteres. Obligatorio."
                )
            ),
        ] = None,
        reason: Annotated[
            str | None,
            Field(
                description=(
                    "Motivo del bloqueo: FRAUD_SUSPECTED (sospecha de fraude) o LOST_OR_STOLEN "
                    "(tarjeta perdida o robada). Obligatorio."
                ),
                json_schema_extra={"enum": list(BLOCK_REASON_CODES)},
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
    ) -> Annotated[CallToolResult, BloquearTarjetaOut]:
        """Bloquea una tarjeta del cliente verificado para que deje de poder usarse.

        Úsala solo después de que `verificar_identidad` haya respondido `verified=true` en la
        conversación (el servidor lo valida) y con un `card_id` devuelto por
        `consultar_transacciones`. Traduce lo que dice el cliente a uno de los códigos de motivo
        y genera una `idempotency_key` nueva por cada bloqueo que quieras hacer; reutilízala solo
        para reintentar esa misma solicitud. No decide si hay fraude, no abre disputas, no
        escala y no desbloquea. Según la respuesta: `already_blocked=true` indica que la tarjeta
        ya estaba bloqueada, infórmalo al cliente; `CARD_NOT_BLOCKABLE` indica que una tarjeta
        cancelada no se puede bloquear; `NOT_FOUND` pide revisar con el cliente de qué tarjeta
        se trata; `INTERNAL` no se reintenta y se deriva a un analista. Efectos: pasa la tarjeta
        de `ACTIVE` a `BLOCKED` y registra el bloqueo y la clave de reintento de forma atómica,
        y un registro de auditoría. Es idempotente por (conversation_id, idempotency_key):
        repetir la misma solicitud devuelve el mismo bloqueo sin duplicarlo.
        """
        try:
            result = block_card.execute(
                BlockCardCommand(
                    conversation_id=conversation_id,
                    card_id=card_id,
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
        except CardNotFoundError:
            return tool_error(ErrorCode.NOT_FOUND, _CARD_NOT_FOUND_MESSAGE, retryable=False)
        except CardNotBlockableError:
            return tool_error(
                ErrorCode.CARD_NOT_BLOCKABLE,
                "Una tarjeta cancelada no se puede bloquear.",
                retryable=False,
            )
        except CoreUnavailableError:
            return tool_error(
                ErrorCode.INTERNAL,
                "El sistema de tarjetas no está disponible.",
                retryable=False,
            )
        except Exception:
            return tool_error(
                ErrorCode.INTERNAL,
                "Ocurrió un error interno al bloquear la tarjeta.",
                retryable=False,
            )
        block = result.block
        output = BloquearTarjetaOut(
            card_id=result.card.card_id,
            masked_card=mask_card(result.card.last4),
            status="BLOCKED",
            blocked_at=None if block is None else block.blocked_at.astimezone(_BOGOTA).isoformat(),
            reason=None if block is None else block.reason.value,
            already_blocked=result.outcome == "already_blocked",
        )
        return CallToolResult(
            content=[TextContent(type="text", text=output.model_dump_json())],
            structuredContent=output.model_dump(mode="json"),
        )

    registered = mcp._tool_manager.get_tool(CARD_TOOL_NAME)
    assert registered is not None
    registered.fn_metadata = ErrorPassthroughMetadata(**dict(registered.fn_metadata))
