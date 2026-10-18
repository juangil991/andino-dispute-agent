"""Herramientas MCP del core bancario: registro de `buscar_cliente` (spec 001 §7).

Diseño de la salida: la herramienta devuelve siempre un `CallToolResult`. La anotación
`Annotated[CallToolResult, BuscarClienteOut]` hace que FastMCP publique `outputSchema` =
esquema de `BuscarClienteOut`; en éxito el `structuredContent` es ese modelo. FastMCP 1.30
validaría también los resultados de error contra ese esquema, así que se registra un
`FuncMetadata` que deja pasar intacto todo `CallToolResult` con `isError=True`
(sobre `{code, message, retryable}` de `tool_error`).
"""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from core_banking_mcp.application.errors import CoreUnavailableError
from core_banking_mcp.application.use_cases.search_customers import (
    SearchCustomers,
    SearchCustomersCommand,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.masking import mask_card, mask_document
from core_banking_mcp.domain.models.customer import Card, Customer
from core_banking_mcp.infrastructure.inbound.mcp.errors import (
    ErrorPassthroughMetadata,
    tool_error,
)
from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    BuscarClienteOut,
    CustomerCardOut,
    CustomerMatchOut,
    ErrorCode,
)

TOOL_NAME = "buscar_cliente"


def _to_card(card: Card) -> CustomerCardOut:
    # Toda tarjeta que lee el repositorio trae su identificador opaco.
    assert card.card_id is not None
    return CustomerCardOut(card_id=card.card_id, masked_card=mask_card(card.last4))


def _to_match(customer: Customer) -> CustomerMatchOut:
    return CustomerMatchOut(
        customer_id=customer.customer_id,
        full_name=customer.full_name,
        masked_document=mask_document(customer.document),
        masked_cards=[mask_card(card.last4) for card in customer.cards],
        cards=[_to_card(card) for card in customer.cards],
    )


def register_tools(mcp: FastMCP, search_customers: SearchCustomers) -> None:
    """Registra las herramientas del core bancario en el servidor FastMCP."""

    @mcp.tool(name=TOOL_NAME)
    def buscar_cliente(
        conversation_id: Annotated[
            str | None,
            Field(description="Identificador de correlación de la conversación. Obligatorio."),
        ] = None,
        document: Annotated[
            str | None,
            Field(
                description=(
                    "Documento del cliente (1-32 caracteres). Al menos uno de document, "
                    "full_name o card_last4 es obligatorio."
                )
            ),
        ] = None,
        full_name: Annotated[
            str | None,
            Field(
                description=(
                    "Nombre completo (1-100 caracteres). Al menos uno de document, "
                    "full_name o card_last4 es obligatorio."
                )
            ),
        ] = None,
        card_last4: Annotated[
            str | None,
            Field(
                description=(
                    "Últimos 4 dígitos de una tarjeta (exactamente 4 dígitos). Al menos uno "
                    "de document, full_name o card_last4 es obligatorio."
                )
            ),
        ] = None,
    ) -> Annotated[CallToolResult, BuscarClienteOut]:
        """Busca clientes del banco por documento, nombre completo o últimos 4 dígitos de tarjeta.

        Úsala al inicio de una conversación para ubicar al cliente que escribe y obtener su
        `customer_id`. Devuelve de 0 a 5 coincidencias con datos mínimos y enmascarados
        (documento y tarjetas). Si hay más de 5 coincidencias devuelve la lista vacía y
        `refinement_required=true`: pide al cliente otro criterio y vuelve a llamarla.
        Los criterios enviados se combinan con AND. No la uses para consultar saldos ni
        movimientos. No autentica ni verifica la identidad del cliente. Es de solo lectura
        e idempotente.
        """
        try:
            result = search_customers.execute(
                SearchCustomersCommand(
                    conversation_id=conversation_id,
                    document=document,
                    full_name=full_name,
                    card_last4=card_last4,
                )
            )
        except InvalidInputError as error:
            return tool_error(
                ErrorCode.INVALID_INPUT,
                f"Los datos de búsqueda no son válidos (campo: {error.field}).",
                retryable=False,
            )
        except CoreUnavailableError:
            return tool_error(
                ErrorCode.INTERNAL, "El sistema de clientes no está disponible.", retryable=False
            )
        except Exception:
            return tool_error(
                ErrorCode.INTERNAL, "Ocurrió un error interno al buscar clientes.", retryable=False
            )
        output = BuscarClienteOut(
            customers=[_to_match(c) for c in result.customers],
            refinement_required=result.refinement_required,
        )
        return CallToolResult(
            content=[TextContent(type="text", text=output.model_dump_json())],
            structuredContent=output.model_dump(mode="json"),
        )

    registered = mcp._tool_manager.get_tool(TOOL_NAME)
    assert registered is not None
    registered.fn_metadata = ErrorPassthroughMetadata(**dict(registered.fn_metadata))
