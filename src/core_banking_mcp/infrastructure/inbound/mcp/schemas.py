"""Esquemas MCP de `buscar_cliente` y sobre de error (spec 001 §7, mcp-tools.md)."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(StrEnum):
    """Catálogo cerrado de códigos de error de `buscar_cliente`."""

    INVALID_INPUT = "INVALID_INPUT"
    INTERNAL = "INTERNAL"


class ToolErrorOut(BaseModel):
    """Sobre de error estructurado de las herramientas MCP."""

    code: ErrorCode = Field(description="Código de error del catálogo cerrado.")
    message: str = Field(description="Mensaje seguro, sin trazas, SQL ni detalles internos.")
    retryable: bool = Field(description="Si es false, la conversación debe escalarse.")


class BuscarClienteIn(BaseModel):
    """Entrada de `buscar_cliente`."""

    conversation_id: str = Field(description="Identificador de correlación; no vacío.")
    document: str | None = Field(
        default=None, description="Documento del cliente; 1-32 caracteres tras recortar."
    )
    full_name: str | None = Field(
        default=None, description="Nombre completo; 1-100 caracteres tras recortar."
    )
    card_last4: str | None = Field(
        default=None, description="Últimos 4 dígitos de una tarjeta (exactamente 4 dígitos 0-9)."
    )


class CustomerMatchOut(BaseModel):
    """Coincidencia de cliente con datos mínimos y enmascarados."""

    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(description="Identificador opaco del cliente en el core.")
    full_name: str = Field(description="Nombre completo tal como está registrado.")
    masked_document: str = Field(description="Documento enmascarado, p. ej. ****01.")
    masked_cards: list[str] = Field(
        description="Tarjetas del cliente en cualquier estado, enmascaradas (**** 4321)."
    )


class BuscarClienteOut(BaseModel):
    """Salida de `buscar_cliente`."""

    customers: list[CustomerMatchOut] = Field(
        description="0 a 5 clientes ordenados por customer_id; vacía si no hay o hay más de 5."
    )
    refinement_required: bool = Field(
        description="True solo si hubo más de 5 coincidencias (customers vacía)."
    )


class VerificarIdentidadIn(BaseModel):
    """Entrada de `verificar_identidad`."""

    conversation_id: str = Field(description="Identificador de correlación; no vacío.")
    customer_id: str = Field(
        description="customer_id devuelto por buscar_cliente; 1-32 caracteres tras recortar."
    )
    birth_date: str = Field(
        description="Fecha de nacimiento AAAA-MM-DD; existente y no posterior a hoy."
    )
    document_issue_date: str = Field(
        description=(
            "Fecha de expedición del documento AAAA-MM-DD; existente, no posterior a hoy "
            "y no anterior a birth_date."
        )
    )


class VerificarIdentidadOut(BaseModel):
    """Salida de `verificar_identidad`."""

    model_config = ConfigDict(extra="forbid")

    verified: bool = Field(
        description="True si la conversación queda (o ya estaba) verificada para ese customer_id."
    )
    attempts_remaining: int = Field(
        ge=0, le=3, description="Intentos que le quedan a la conversación (3 - fallos acumulados)."
    )
    escalation_required: bool = Field(
        description="True si la conversación está bloqueada y debe derivarse a un analista."
    )
