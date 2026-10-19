"""Herramientas de intención que ve el LLM y herramientas de escritura reservadas."""

from dispute_agent.application.ports.llm import ToolSpec

_DISPUTE_REASONS = [
    "UNRECOGNIZED_CHARGE",
    "DUPLICATE_CHARGE",
    "INCORRECT_AMOUNT",
    "NOT_RECEIVED",
    "OTHER",
]


def _object(properties: dict[str, object], required: list[str]) -> dict[str, object]:
    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


LLM_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="buscar_cliente",
        description=(
            "Busca al cliente para identificarlo. Úsala al inicio de la conversación con "
            "al menos uno de estos datos: documento, nombre completo o últimos 4 dígitos "
            "de la tarjeta."
        ),
        input_schema=_object(
            {
                "document": {"type": "string", "description": "Número de documento."},
                "full_name": {"type": "string", "description": "Nombre completo."},
                "card_last4": {
                    "type": "string",
                    "description": "Últimos 4 dígitos de la tarjeta.",
                },
            },
            [],
        ),
    ),
    ToolSpec(
        name="verificar_identidad",
        description=(
            "Verifica la identidad del cliente ya identificado con su fecha de nacimiento "
            "y la fecha de expedición de su documento. Úsala antes de hablar de "
            "transacciones."
        ),
        input_schema=_object(
            {
                "birth_date": {
                    "type": "string",
                    "description": "Fecha de nacimiento, formato AAAA-MM-DD.",
                },
                "document_issue_date": {
                    "type": "string",
                    "description": "Fecha de expedición del documento, formato AAAA-MM-DD.",
                },
            },
            ["birth_date", "document_issue_date"],
        ),
    ),
    ToolSpec(
        name="consultar_transacciones",
        description=(
            "Consulta las transacciones de una tarjeta del cliente verificado en un rango "
            "de fechas de máximo 90 días. Úsala para localizar el cargo en disputa."
        ),
        input_schema=_object(
            {
                "card_last4": {
                    "type": "string",
                    "pattern": "^[0-9]{4}$",
                    "description": "Últimos 4 dígitos de la tarjeta.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Fecha inicial, formato AAAA-MM-DD.",
                },
                "date_to": {
                    "type": "string",
                    "description": "Fecha final, formato AAAA-MM-DD (máximo 90 días).",
                },
            },
            ["card_last4", "date_from", "date_to"],
        ),
    ),
    ToolSpec(
        name="evaluar_disputa",
        description=(
            "Comunica que el cliente quiere disputar una transacción concreta. La "
            "aplicación evalúa si procede y ejecuta la acción; tú no decides."
        ),
        input_schema=_object(
            {
                "transaction_id": {
                    "type": "string",
                    "description": "Identificador de la transacción a disputar.",
                },
                "reason": {
                    "type": "string",
                    "enum": _DISPUTE_REASONS,
                    "default": "UNRECOGNIZED_CHARGE",
                    "description": "Motivo de la disputa.",
                },
            },
            ["transaction_id"],
        ),
    ),
    ToolSpec(
        name="reportar_fraude",
        description=(
            "Úsala solo si el cliente declara sospecha de fraude. Pedir que se bloquee la "
            "tarjeta sin declarar sospecha de fraude no es motivo para reportar_fraude. La "
            "aplicación decide y ejecuta las acciones de protección correspondientes."
        ),
        input_schema=_object(
            {
                "card_last4": {
                    "type": "string",
                    "description": "Últimos 4 dígitos de la tarjeta afectada.",
                },
                "transaction_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Transacciones sospechosas.",
                },
            },
            [],
        ),
    ),
    ToolSpec(
        name="solicitar_atencion_humana",
        description=(
            "Úsala solo si el cliente pide expresamente hablar con una persona, asesor o "
            "analista. No la uses por frustración o dudas."
        ),
        input_schema=_object({}, []),
    ),
)

WRITE_TOOLS: frozenset[str] = frozenset(
    {"iniciar_disputa", "bloquear_tarjeta", "escalar_a_analista"}
)
