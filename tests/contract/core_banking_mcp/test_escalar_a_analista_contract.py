"""Contrato de `escalar_a_analista`: esquemas MCP y sobre de error (spec 006 §7)."""

from typing import Any

from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    ESCALATION_REASON_CODES,
    PRIOR_ACTION_CODES,
    ErrorCode,
    EscalarAnalistaOut,
    EscalationCardOut,
    EscalationSummaryOut,
    ToolErrorOut,
    TransactionItemOut,
)

_REASONS = {
    "FRAUD_SUSPECTED",
    "AMOUNT_OVER_THRESHOLD",
    "INSUFFICIENT_OR_CONTRADICTORY_INFO",
    "INCONCLUSIVE_RULES",
    "UNRECOVERABLE_SYSTEM_FAILURE",
    "IDENTITY_VERIFICATION_FAILED",
    "OTHER",
}

_PRIOR_ACTIONS = {"DISPUTE_OPENED", "CARD_BLOCKED"}

_ERROR_CODES = {
    "INVALID_INPUT",
    "IDENTITY_NOT_VERIFIED",
    "NOT_FOUND",
    "TRANSACTION_NOT_DISPUTABLE",
    "DISPUTE_ALREADY_OPEN",
    "CARD_NOT_BLOCKABLE",
    "INTERNAL",
}

_SUMMARY_FIELDS = {
    "conversation_id",
    "identity_verified",
    "customer_id",
    "transaction",
    "card",
    "prior_actions",
    "dispute_id",
    "note",
}


def _const_or_enum(prop: dict[str, Any]) -> set[str]:
    """Valores literales admitidos por una propiedad (const o enum, también en anyOf)."""
    options = prop.get("anyOf", [prop])
    values: set[str] = set()
    for opt in options:
        if "const" in opt:
            values.add(opt["const"])
        values.update(opt.get("enum", ()))
    return values


def _admits_null(prop: dict[str, Any]) -> bool:
    return {"type": "null"} in prop.get("anyOf", [])


def _refs(prop: dict[str, Any]) -> set[str]:
    return {opt["$ref"] for opt in prop.get("anyOf", [prop]) if "$ref" in opt}


# Regla: RN-006-12 — La respuesta exitosa contiene **solo** `escalation_id`, `status`,
#   `escalated_at`, `reason` y `summary`. `summary` contiene **solo** `conversation_id`,
#   `identity_verified`, `customer_id`, `transaction` (con exactamente los campos de
#   `TransactionItem` de la spec 003, RN-003-12, o `null`), `card` (con exactamente `card_id` y
#   `masked_card`, `**** ` seguido de los 4 últimos dígitos, RN-001-09, o `null`),
#   `prior_actions`, `dispute_id` y `note`.
# Regla: RN-006-13 — La respuesta nunca contiene el número completo de ninguna tarjeta, el
#   documento del cliente ni su nombre, ni datos de otros clientes.
# AC-006-18 · Art. 7 (datos mínimos)
def test_ac_006_18_escalar_a_analista__output_schema__has_exactly_spec_fields() -> None:
    """AC-006-18: salida, resumen y tarjeta cerrados con los campos exactos de la spec."""
    out = EscalarAnalistaOut.model_json_schema()
    assert set(out["properties"]) == {
        "escalation_id",
        "status",
        "escalated_at",
        "reason",
        "summary",
    }
    assert out["additionalProperties"] is False

    defs = out["$defs"]
    summary = defs["EscalationSummaryOut"]
    assert set(summary["properties"]) == _SUMMARY_FIELDS
    assert summary["additionalProperties"] is False

    card = defs["EscalationCardOut"]
    assert set(card["properties"]) == {"card_id", "masked_card"}
    assert card["additionalProperties"] is False

    transaction = defs["TransactionItemOut"]
    assert set(transaction["properties"]) == set(
        TransactionItemOut.model_json_schema()["properties"]
    )
    assert transaction["additionalProperties"] is False

    for schema in (out, summary, card):
        assert all("description" in p for p in schema["properties"].values())

    assert _refs(out["properties"]["summary"]) == {"#/$defs/EscalationSummaryOut"}
    assert _refs(summary["properties"]["transaction"]) == {"#/$defs/TransactionItemOut"}
    assert _refs(summary["properties"]["card"]) == {"#/$defs/EscalationCardOut"}
    assert summary["properties"]["identity_verified"]["type"] == "boolean"


# Regla: RN-006-08 — Una derivación nueva queda con un `escalation_id` opaco y único, no
#   derivado del número de ninguna tarjeta; `status = PENDING`, que esta feature nunca cambia;
#   `escalated_at` igual al instante del reloj inyectado en ISO 8601 con la zona de Bogotá
#   (`−05:00`); el `reason` recibido; y un resumen. El resumen es **completo** si la
#   conversación está verificada (`identity_verified = true`, `customer_id` del cliente
#   verificado y los datos indicados) y **limitado** si no lo está (`identity_verified = false`,
#   `customer_id`, `transaction`, `card` y `dispute_id` en `null` y `prior_actions` vacía). En
#   ambos casos trae `conversation_id` y la nota, si la hay.
# AC-006-01 · Art. 7 (salida cerrada)
def test_ac_006_01_escalar_a_analista__output__matches_schema_with_pending_status() -> None:
    """AC-006-01: una salida completa cumple EscalarAnalistaOut con status PENDING."""
    out = EscalarAnalistaOut(
        escalation_id="E-1",
        status="PENDING",
        escalated_at="2026-10-17T10:00:00-05:00",
        reason="FRAUD_SUSPECTED",
        summary=EscalationSummaryOut(
            conversation_id="A",
            identity_verified=True,
            customer_id="C-0001",
            transaction=TransactionItemOut(
                transaction_id="TX-L1",
                occurred_at="2026-10-10T12:00:00-05:00",
                merchant="Tienda Aurora",
                amount="85000.00",
                currency="COP",
                status="CONFIRMED",
                card_id="CARD-L1",
                masked_card="**** 4321",
                merchant_country="CO",
            ),
            card=EscalationCardOut(card_id="CARD-L1", masked_card="**** 4321"),
            prior_actions=[],
            dispute_id=None,
            note=None,
        ),
    )
    dumped = out.model_dump()
    assert set(dumped) == {"escalation_id", "status", "escalated_at", "reason", "summary"}
    assert set(dumped["summary"]) == _SUMMARY_FIELDS
    assert set(dumped["summary"]["card"]) == {"card_id", "masked_card"}
    assert dumped["status"] == "PENDING"
    status = EscalarAnalistaOut.model_json_schema()["properties"]["status"]
    assert _const_or_enum(status) == {"PENDING"}


# Regla: RN-006-02 — El motivo es un código de un catálogo cerrado que distingue mayúsculas:
#   `FRAUD_SUSPECTED` (sospecha de fraude), `AMOUNT_OVER_THRESHOLD` (monto sobre el umbral),
#   `INSUFFICIENT_OR_CONTRADICTORY_INFO` (información insuficiente o contradictoria),
#   `INCONCLUSIVE_RULES` (reglas no concluyentes), `UNRECOVERABLE_SYSTEM_FAILURE` (falla no
#   recuperable del sistema), `IDENTITY_VERIFICATION_FAILED` (verificación de identidad fallida
#   o agotada) y `OTHER` (otro). Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`.
# AC-006-02 · Art. 7 (contrato cerrado)
def test_ac_006_02_escalar_a_analista__output_reason__admits_only_the_seven_codes() -> None:
    """AC-006-02: reason admite solo los 7 códigos en la salida."""
    out = EscalarAnalistaOut.model_json_schema()
    assert _const_or_enum(out["properties"]["reason"]) == _REASONS
    assert len(_const_or_enum(out["properties"]["reason"])) == 7


# Regla: RN-006-02 — Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT` (el enum se
#   publica al LLM).
# Regla: RN-006-10 — Validación de entrada: `conversation_id` obligatorio y no vacío tras
#   recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason`
#   obligatorio y del catálogo de RN-006-02.
# AC-006-03 · Art. 8 (contrato publicado)
def test_ac_006_03_escalar_a_analista__reason_codes__are_the_seven_spec_values() -> None:
    """AC-006-03: ESCALATION_REASON_CODES contiene exactamente los 7 códigos."""
    assert set(ESCALATION_REASON_CODES) == _REASONS
    assert len(ESCALATION_REASON_CODES) == 7


# Regla: RN-006-03 — La derivación **no** exige identidad verificada. Si la solicitud no trae
#   datos del cliente, se registra en cualquier conversación: verificada, sin verificar,
#   bloqueada por agotar sus intentos o desconocida para el servidor.
# Regla: RN-006-08 — En el resumen limitado `customer_id`, `transaction`, `card` y `dispute_id`
#   van en `null` y `prior_actions` vacía; en ambos casos trae `conversation_id` y la nota, si
#   la hay.
# AC-006-04 · Art. 7 (resumen limitado sin identidad)
def test_ac_006_04_escalar_a_analista__limited_summary__admits_null_fields() -> None:
    """AC-006-04: el resumen limitado se expresa con null y prior_actions vacía."""
    props = EscalationSummaryOut.model_json_schema()["properties"]
    for field in ("customer_id", "transaction", "card", "dispute_id", "note"):
        assert _admits_null(props[field]), field
    limited = EscalationSummaryOut(
        conversation_id="B",
        identity_verified=False,
        customer_id=None,
        transaction=None,
        card=None,
        prior_actions=[],
        dispute_id=None,
        note=None,
    )
    assert limited.identity_verified is False
    assert limited.model_dump()["prior_actions"] == []


# Regla: RN-006-05 — `prior_actions` es una lista de códigos de un catálogo cerrado que
#   distingue mayúsculas: `DISPUTE_OPENED` (se abrió una disputa) y `CARD_BLOCKED` (se bloqueó
#   la tarjeta). Ausente, `null` o vacía significa que no se realizó ninguna acción.
# Regla: RN-006-12 — `summary` contiene `prior_actions` y `dispute_id`.
# AC-006-06 · Art. 7 (catálogo cerrado)
def test_ac_006_06_escalar_a_analista__prior_actions__admit_only_the_two_codes() -> None:
    """AC-006-06: los elementos de prior_actions admiten solo DISPUTE_OPENED y CARD_BLOCKED."""
    prop = EscalationSummaryOut.model_json_schema()["properties"]["prior_actions"]
    assert prop["type"] == "array"
    assert _const_or_enum(prop["items"]) == _PRIOR_ACTIONS


# Regla: RN-006-05 — Un código fuera del catálogo, un código repetido o una incoherencia ⇒
#   `INVALID_INPUT`.
# Regla: RN-006-10 — `prior_actions` y `note` según RN-006-05 y RN-006-07.
# AC-006-07 · Art. 8 (contrato publicado)
def test_ac_006_07_escalar_a_analista__prior_action_codes__are_the_two_spec_values() -> None:
    """AC-006-07: PRIOR_ACTION_CODES contiene exactamente los 2 códigos."""
    assert set(PRIOR_ACTION_CODES) == _PRIOR_ACTIONS
    assert len(PRIOR_ACTION_CODES) == 2


# Regla: RN-006-07 — `note` es opcional. Se recorta; vacía o solo espacios equivale a sin nota
#   (`null`). Tras recortar admite de 1 a 300 caracteres.
# AC-006-09 · Art. 7 (nota opcional)
def test_ac_006_09_escalar_a_analista__optional_fields__admit_null() -> None:
    """AC-006-09: note y dispute_id admiten null en el resumen (nota ausente)."""
    props = EscalationSummaryOut.model_json_schema()["properties"]
    assert _admits_null(props["note"])
    assert _admits_null(props["dispute_id"])
    summary = EscalationSummaryOut(
        conversation_id="A",
        identity_verified=True,
        customer_id="C-0001",
        transaction=None,
        card=None,
        prior_actions=[],
        dispute_id=None,
        note=None,
    )
    assert summary.note is None


# Regla: RN-006-04 — Si algún dato no cumple, porque es de otro cliente, de otra tarjeta o
#   porque no existe, se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en todos los
#   casos y sin datos de ningún cliente.
# AC-006-12 · Art. 7 (sin filtrar existencia de datos ajenos)
def test_ac_006_12_escalar_a_analista__error_catalog__includes_not_found() -> None:
    """AC-006-12: ErrorCode contiene NOT_FOUND y sigue siendo el catálogo de 7 códigos."""
    assert ErrorCode.NOT_FOUND.value == "NOT_FOUND"
    assert {c.value for c in ErrorCode} == _ERROR_CODES
    assert len(ErrorCode) == 7


# Regla: RN-006-10 — Toda violación ⇒ `INVALID_INPUT`, sin derivación registrada.
# AC-006-16 · Art. 10 (sobre de error)
def test_ac_006_16_escalar_a_analista__error_envelope__has_code_message_retryable() -> None:
    """AC-006-16: ToolErrorOut conserva code, message y retryable; admite INVALID_INPUT."""
    err = ToolErrorOut(code=ErrorCode.INVALID_INPUT, message="Entrada inválida.", retryable=False)
    assert err.retryable is False
    assert set(ToolErrorOut.model_json_schema()["properties"]) == {"code", "message", "retryable"}


# Regla: RN-006-15 — Ante una falla inesperada (p. ej. el repositorio de derivaciones no
#   responde al registrar), la herramienta devuelve `INTERNAL` con `retryable = false` y sin
#   detalles internos (trazas, SQL, texto de la excepción). La operación es atómica: no queda
#   ninguna derivación ni clave de reintento registrada.
# AC-006-19 · Art. 10 (sobre de error)
def test_ac_006_19_escalar_a_analista__error_envelope__supports_internal_not_retryable() -> None:
    """AC-006-19: ToolErrorOut admite INTERNAL con retryable = false."""
    err = ToolErrorOut(code=ErrorCode.INTERNAL, message="Error interno.", retryable=False)
    assert err.code is ErrorCode.INTERNAL
    assert err.retryable is False
    assert set(ToolErrorOut.model_json_schema()["properties"]) == {"code", "message", "retryable"}


# Regla: RN-007-30 — `TransactionItem` (RN-003-12) incorpora `merchant_country`: el código ISO 3166-1 alfa-2 del país del comercio, en mayúsculas (`CO` = Colombia).  # noqa: E501
# AC-007-33 · Art. 7 (datos mínimos)
def test_ac_007_33_escalar_a_analista__transaction_schema__has_merchant_country() -> None:
    """AC-007-33: la transacción del resumen incluye merchant_country y es un esquema cerrado."""
    item: dict[str, Any] = EscalarAnalistaOut.model_json_schema()["$defs"]["TransactionItemOut"]
    assert "merchant_country" in item["properties"]
    assert item["additionalProperties"] is False
