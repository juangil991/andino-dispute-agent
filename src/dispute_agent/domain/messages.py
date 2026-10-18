"""Textos fijos en español de spec §5 y §7.3 (RN-007-25)."""

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

CONVERSATION_CLOSED_MESSAGE = (
    "Tu caso ya fue derivado a un analista. Una persona continuará la atención."
)
HUMAN_REQUEST_NOTE = "Cliente solicitó atención humana"
