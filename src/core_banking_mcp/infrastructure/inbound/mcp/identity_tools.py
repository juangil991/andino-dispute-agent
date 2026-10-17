"""Herramientas MCP de identidad: registro de `verificar_identidad` (spec 002 §7).

Misma estrategia de salida que `tools.py`: `CallToolResult` con `structuredContent` del
modelo `VerificarIdentidadOut`; los resultados `verified=false` son respuestas exitosas.
Los errores se devuelven como sobre `{code, message, retryable}` (`tool_error`).
"""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from core_banking_mcp.application.errors import CoreUnavailableError
from core_banking_mcp.application.use_cases.verify_identity import (
    VerifyIdentity,
    VerifyIdentityCommand,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.infrastructure.inbound.mcp.errors import (
    ErrorPassthroughMetadata,
    tool_error,
)
from core_banking_mcp.infrastructure.inbound.mcp.schemas import ErrorCode, VerificarIdentidadOut

IDENTITY_TOOL_NAME = "verificar_identidad"


def register_identity_tools(mcp: FastMCP, verify_identity: VerifyIdentity) -> None:
    """Registra las herramientas de identidad en el servidor FastMCP."""

    @mcp.tool(name=IDENTITY_TOOL_NAME)
    def verificar_identidad(
        conversation_id: Annotated[
            str | None,
            Field(description="Identificador de correlación de la conversación. Obligatorio."),
        ] = None,
        customer_id: Annotated[
            str | None,
            Field(
                description="customer_id devuelto por buscar_cliente (1-32 caracteres). Obligatorio"
            ),
        ] = None,
        birth_date: Annotated[
            str | None,
            Field(
                description=(
                    "Fecha de nacimiento AAAA-MM-DD; existente y no posterior a hoy. Obligatoria."
                )
            ),
        ] = None,
        document_issue_date: Annotated[
            str | None,
            Field(
                description=(
                    "Fecha de expedición del documento AAAA-MM-DD; existente, no posterior a "
                    "hoy y no anterior a birth_date. Obligatoria."
                )
            ),
        ] = None,
    ) -> Annotated[CallToolResult, VerificarIdentidadOut]:
        """Verifica la identidad del cliente comparando su fecha de nacimiento y de expedición.

        Úsala después de ubicar al cliente con `buscar_cliente` y antes de cualquier consulta u
        operación sobre sus datos. La verificación es exitosa solo si ambas fechas coinciden con
        las registradas. Una verificación no exitosa responde `verified=false` sin indicar cuál
        dato falló; el tercer fallo de la conversación la bloquea y devuelve
        `escalation_required=true`: en ese caso no la reintentes y deriva a un analista. No la
        uses para consultar saldos, movimientos ni datos del cliente. Efectos: registra en
        memoria del servidor el cliente verificado o el intento fallido de la conversación, y un
        registro de auditoría. No es idempotente salvo cuando la conversación ya está
        verificada para el mismo cliente.
        """
        try:
            result = verify_identity.execute(
                VerifyIdentityCommand(
                    conversation_id=conversation_id,
                    customer_id=customer_id,
                    birth_date=birth_date,
                    document_issue_date=document_issue_date,
                )
            )
        except InvalidInputError as error:
            return tool_error(
                ErrorCode.INVALID_INPUT,
                f"Los datos de verificación no son válidos (campo: {error.field}).",
                retryable=False,
            )
        except CoreUnavailableError:
            return tool_error(
                ErrorCode.INTERNAL,
                "El sistema de verificación de identidad no está disponible.",
                retryable=False,
            )
        except Exception:
            return tool_error(
                ErrorCode.INTERNAL,
                "Ocurrió un error interno al verificar la identidad.",
                retryable=False,
            )
        output = VerificarIdentidadOut(
            verified=result.verified,
            attempts_remaining=result.attempts_remaining,
            escalation_required=result.escalation_required,
        )
        return CallToolResult(
            content=[TextContent(type="text", text=output.model_dump_json())],
            structuredContent=output.model_dump(mode="json"),
        )

    registered = mcp._tool_manager.get_tool(IDENTITY_TOOL_NAME)
    assert registered is not None
    registered.fn_metadata = ErrorPassthroughMetadata(**dict(registered.fn_metadata))
