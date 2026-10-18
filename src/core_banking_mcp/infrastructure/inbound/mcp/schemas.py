"""Esquemas MCP de las herramientas y sobre de error (specs 001-003 §7, mcp-tools.md)."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ErrorCode(StrEnum):
    """Catálogo cerrado de códigos de error de las herramientas MCP."""

    INVALID_INPUT = "INVALID_INPUT"
    IDENTITY_NOT_VERIFIED = "IDENTITY_NOT_VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    TRANSACTION_NOT_DISPUTABLE = "TRANSACTION_NOT_DISPUTABLE"
    DISPUTE_ALREADY_OPEN = "DISPUTE_ALREADY_OPEN"
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


class ConsultarTransaccionesIn(BaseModel):
    """Entrada de `consultar_transacciones`."""

    conversation_id: str = Field(description="Identificador de correlación; no vacío.")
    card_last4: str = Field(
        description="Últimos 4 dígitos de la tarjeta (exactamente 4 dígitos 0-9)."
    )
    date_from: str = Field(
        description="Fecha inicial AAAA-MM-DD, incluida; existente y no posterior a date_to."
    )
    date_to: str = Field(
        description=(
            "Fecha final AAAA-MM-DD, incluida; existente, no posterior a hoy (Bogotá) "
            "y a lo sumo 89 días después de date_from."
        )
    )


class TransactionItemOut(BaseModel):
    """Transacción de una tarjeta del cliente verificado."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(description="Identificador opaco de la transacción en el core.")
    occurred_at: str = Field(
        description="Fecha y hora ISO 8601 con zona (p. ej. 2026-09-20T14:32:00-05:00)."
    )
    merchant: str = Field(description="Nombre del comercio.")
    amount: str = Field(
        description='Monto original, positivo, con exactamente 2 decimales (p. ej. "125000.00").'
    )
    currency: str = Field(description="Código ISO 4217 de 3 letras (p. ej. COP, USD).")
    status: Literal["CONFIRMED", "PENDING", "REVERSED"] = Field(
        description="Estado de la transacción: CONFIRMED, PENDING o REVERSED."
    )
    card_id: str = Field(
        description="Identificador opaco de la tarjeta en el core; distingue tarjetas homónimas."
    )
    masked_card: str = Field(description="Tarjeta enmascarada: '**** ' y sus 4 últimos dígitos.")


class ConsultarTransaccionesOut(BaseModel):
    """Salida de `consultar_transacciones`."""

    model_config = ConfigDict(extra="forbid")

    transactions: list[TransactionItemOut] = Field(
        max_length=50,
        description=(
            "0 a 50 transacciones, de la más reciente a la más antigua; vacía si no hay "
            "en el rango o si hay más de 50."
        ),
    )
    refinement_required: bool = Field(
        description="True solo si hubo más de 50 transacciones en el rango (lista vacía)."
    )


_DISPUTE_REASONS: list[JsonValue] = [
    "UNRECOGNIZED_CHARGE",
    "DUPLICATE_CHARGE",
    "INCORRECT_AMOUNT",
    "NOT_RECEIVED",
    "OTHER",
]


class IniciarDisputaIn(BaseModel):
    """Entrada de `iniciar_disputa`."""

    conversation_id: str = Field(description="Identificador de correlación; no vacío.")
    transaction_id: str = Field(
        description="transaction_id devuelto por consultar_transacciones; 1-64 caracteres."
    )
    reason: str = Field(
        description=(
            "Motivo de la disputa: UNRECOGNIZED_CHARGE, DUPLICATE_CHARGE, INCORRECT_AMOUNT, "
            "NOT_RECEIVED u OTHER."
        ),
        json_schema_extra={"enum": _DISPUTE_REASONS},
    )
    idempotency_key: str = Field(
        description=(
            "Clave de reintento generada por el consumidor; 1-64 caracteres; única por "
            "conversación. Reutilizarla solo para reintentar la misma solicitud."
        )
    )


class IniciarDisputaOut(BaseModel):
    """Salida de `iniciar_disputa`."""

    model_config = ConfigDict(extra="forbid")

    dispute_id: str = Field(
        description="Identificador opaco de la disputa, no derivado del número de la tarjeta."
    )
    status: Literal["OPEN"] = Field(description="Estado de la disputa: OPEN.")
    opened_at: str = Field(
        description="Instante de apertura ISO 8601 con zona (p. ej. 2026-10-17T10:00:00-05:00)."
    )
    reason: Literal[
        "UNRECOGNIZED_CHARGE", "DUPLICATE_CHARGE", "INCORRECT_AMOUNT", "NOT_RECEIVED", "OTHER"
    ] = Field(description="Código del motivo de la disputa.")
    transaction: TransactionItemOut = Field(description="La transacción disputada.")
