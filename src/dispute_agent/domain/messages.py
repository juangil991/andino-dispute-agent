"""Textos fijos en español de spec §5 y §7.3 (RN-007-25)."""

from dispute_agent.domain.identification import IdentificationReply
from dispute_agent.domain.models.outcome import OutcomeKind

_ESCALATED_NEXT_STEPS_TX = "Un analista revisará tu caso y te contactará."
_FRAUD_NEXT_STEPS = "Un analista revisará el caso de fraude y te contactará."

DP_REASONS: dict[str, str] = {
    "DP-007-01": (
        "Solo se pueden disputar transacciones confirmadas; "
        "esta transacción está pendiente o fue reversada."
    ),
    "DP-007-02": "No podemos evaluar automáticamente un cobro en esta moneda.",
    "DP-007-03": "El monto supera el límite para abrir disputas automáticamente.",
    "DP-007-04": (
        "Los cobros de comercios del exterior con más de 90 días "
        "no se pueden resolver automáticamente."
    ),
    "DP-007-05": "El cobro cumple las condiciones para abrir la disputa de inmediato.",
    "DP-007-06": (
        "Por la sospecha de fraude bloqueamos tu tarjeta y abrimos la disputa de este cobro."
    ),
    "DP-007-07": (
        "Por la sospecha de fraude bloqueamos tu tarjeta; este cobro lo revisará un analista."
    ),
}

DP_NEXT_STEPS: dict[str, str] = {
    "DP-007-01": "Si la transacción se confirma y sigues sin reconocerla, vuelve a escribirnos.",
    "DP-007-02": _ESCALATED_NEXT_STEPS_TX,
    "DP-007-03": _ESCALATED_NEXT_STEPS_TX,
    "DP-007-04": _ESCALATED_NEXT_STEPS_TX,
    "DP-007-05": "Tu disputa quedó abierta; el banco la gestionará y te informará el resultado.",
    "DP-007-06": _FRAUD_NEXT_STEPS,
    "DP-007-07": _FRAUD_NEXT_STEPS,
}

ESCALATED_NO_TX_REASON = "Tu caso requiere la revisión de una persona."
ESCALATED_NO_TX_NEXT_STEPS = "Una persona continuará la atención."

# Textos de §7.3 para los tipos sin texto de §5 (DISPUTE_OPENED, NOT_DISPUTABLE y
# ESCALATED por transacción usan DP_REASONS / DP_NEXT_STEPS).
OUTCOME_REASONS: dict[OutcomeKind, str] = {
    OutcomeKind.CARD_BLOCKED: "Bloqueamos tu tarjeta por la sospecha de fraude que reportaste.",
    OutcomeKind.CARD_ALREADY_BLOCKED: "Tu tarjeta ya estaba bloqueada.",
    OutcomeKind.CARD_NOT_BLOCKABLE: (
        "Tu tarjeta está cancelada, por lo que no es necesario bloquearla."
    ),
    OutcomeKind.DISPUTE_ALREADY_OPEN: "Ya existe una disputa abierta sobre esta transacción.",
    OutcomeKind.NO_TRANSACTIONS_FOUND: "No encontramos transacciones en el periodo indicado.",
    OutcomeKind.REFINEMENT_REQUIRED: "Hay demasiadas transacciones en el periodo indicado.",
    OutcomeKind.ESCALATED: ESCALATED_NO_TX_REASON,
    OutcomeKind.ITERATION_LIMIT: "No pudimos completar tu solicitud automáticamente.",
    OutcomeKind.LLM_FAILURE: "Tuvimos un problema al procesar tu solicitud.",
    OutcomeKind.ESCALATION_FAILED: "No pudimos derivar tu caso a un analista en este momento.",
}

OUTCOME_NEXT_STEPS: dict[OutcomeKind, str] = {
    OutcomeKind.CARD_BLOCKED: _FRAUD_NEXT_STEPS,
    OutcomeKind.CARD_ALREADY_BLOCKED: _FRAUD_NEXT_STEPS,
    OutcomeKind.CARD_NOT_BLOCKABLE: _FRAUD_NEXT_STEPS,
    OutcomeKind.DISPUTE_ALREADY_OPEN: (
        "La disputa existente sigue su curso; no es necesario abrir otra."
    ),
    OutcomeKind.NO_TRANSACTIONS_FOUND: "Indícanos otro periodo para buscar el cobro.",
    OutcomeKind.REFINEMENT_REQUIRED: "Indícanos un periodo más corto para buscar el cobro.",
    OutcomeKind.ESCALATED: ESCALATED_NO_TX_NEXT_STEPS,
    OutcomeKind.ITERATION_LIMIT: ESCALATED_NO_TX_NEXT_STEPS,
    OutcomeKind.LLM_FAILURE: ESCALATED_NO_TX_NEXT_STEPS,
    OutcomeKind.ESCALATION_FAILED: "Por favor, vuelve a contactar al banco más tarde.",
}

IDENTIFICATION_REPLIES: dict[IdentificationReply, str] = {
    IdentificationReply.REMINDER_LOCATE: (
        "Antes de ayudarte necesito identificarte. Indícame tu número de documento, "
        "tu nombre completo o los últimos 4 dígitos de tu tarjeta."
    ),
    IdentificationReply.REMINDER_VERIFY: (
        "Antes de ayudarte necesito confirmar tu identidad. Indícame tu fecha de "
        "nacimiento y la fecha de expedición de tu documento."
    ),
    IdentificationReply.ASK_DATES: (
        "Gracias. Para confirmar tu identidad, indícame tu fecha de nacimiento y la "
        "fecha de expedición de tu documento."
    ),
    IdentificationReply.ASK_MORE_DATA: (
        "Necesito un dato adicional para identificarte. Indícame tu número de "
        "documento o los últimos 4 dígitos de tu tarjeta."
    ),
    IdentificationReply.NOT_FOUND: (
        "No pudimos identificarte con esos datos. Revísalos e intenta con otro dato: "
        "tu número de documento, tu nombre completo o los últimos 4 dígitos de tu "
        "tarjeta."
    ),
    IdentificationReply.WRONG_DATES_2: (
        "Los datos no coinciden con los registrados. Te quedan 2 intentos. Indícame "
        "de nuevo tu fecha de nacimiento y la fecha de expedición de tu documento."
    ),
    IdentificationReply.WRONG_DATES_1: (
        "Los datos no coinciden con los registrados. Te queda 1 intento. Indícame "
        "de nuevo tu fecha de nacimiento y la fecha de expedición de tu documento."
    ),
    IdentificationReply.INVALID_DATES: (
        "Las fechas no son válidas. Indícame tu fecha de nacimiento y la fecha de "
        "expedición de tu documento con el formato AAAA-MM-DD."
    ),
    IdentificationReply.INVALID_SEARCH: (
        "Esos datos no son válidos. Revísalos e indícame tu número de documento, "
        "tu nombre completo o los últimos 4 dígitos de tu tarjeta."
    ),
    IdentificationReply.CLOSED_ESCALATED: f"{ESCALATED_NO_TX_REASON} {ESCALATED_NO_TX_NEXT_STEPS}",
    IdentificationReply.CLOSED_ESCALATION_FAILED: (
        f"{OUTCOME_REASONS[OutcomeKind.ESCALATION_FAILED]} "
        f"{OUTCOME_NEXT_STEPS[OutcomeKind.ESCALATION_FAILED]}"
    ),
}


def invalid_input_message(tool: str, field: str | None) -> str:
    """Texto fijo de RN-010-02: sin texto del servidor ni valores enviados."""
    where = f" (campo: {field})" if field else ""
    return (
        f"Los datos enviados a {tool} no son válidos{where}. Corrígelos y vuelve a llamar "
        "a la herramienta; si no puedes formarlos con lo que dijo la cliente, pídeselos."
    )


def unknown_card_message(own_last4: tuple[str, ...]) -> str:
    """Texto fijo de spec 011 §7.1: solo los últimos 4 de las tarjetas de la clienta."""
    if len(own_last4) > 1:
        listed = f"{', '.join(own_last4[:-1])} y {own_last4[-1]}"
    else:
        listed = "".join(own_last4)
    return (
        f"Esa tarjeta no está entre las de la clienta (terminadas en {listed}). "
        "Usa una de ellas o pregúntale a la clienta cuál es; no repitas los mismos dígitos."
    )


NOT_FOUND_CARD_MESSAGE = (
    "No se encontró esa tarjeta. Pídele a la clienta que revise los últimos "
    "4 dígitos antes de volver a consultar."
)

CONVERSATION_CLOSED_MESSAGE = (
    "Tu caso ya fue derivado a un analista. Una persona continuará la atención."
)
HUMAN_REQUEST_NOTE = "Cliente solicitó atención humana"
