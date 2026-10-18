"""Tests de los value objects de derivación a un analista."""

from datetime import UTC, datetime
from typing import Any

import pytest

from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.escalation import (
    Escalation,
    EscalationReason,
    EscalationRequest,
    EscalationStatus,
    PriorAction,
)

_ESCALATED_AT = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
_PAN = "4111111111114321"

_REASONS = [
    "FRAUD_SUSPECTED",
    "AMOUNT_OVER_THRESHOLD",
    "INSUFFICIENT_OR_CONTRADICTORY_INFO",
    "INCONCLUSIVE_RULES",
    "UNRECOVERABLE_SYSTEM_FAILURE",
    "IDENTITY_VERIFICATION_FAILED",
    "OTHER",
]


def _create(**overrides: Any) -> EscalationRequest:
    values: dict[str, Any] = {
        "conversation_id": "A",
        "reason": "FRAUD_SUSPECTED",
        "idempotency_key": "K-1",
    }
    values.update(overrides)
    return EscalationRequest.create(**values)


def _escalation(**overrides: Any) -> Escalation:
    values: dict[str, Any] = {
        "escalation_id": "ESC-000001",
        "conversation_id": "A",
        "idempotency_key": "K-1",
        "reason": EscalationReason.FRAUD_SUSPECTED,
        "status": EscalationStatus.PENDING,
        "escalated_at": _ESCALATED_AT,
        "identity_verified": True,
        "customer_id": "C-0001",
        "transaction_id": "TX-L1",
        "card_id": "CARD-L1",
        "prior_actions": frozenset({PriorAction.CARD_BLOCKED}),
        "dispute_id": None,
        "note": "revisar",
    }
    values.update(overrides)
    return Escalation(**values)


# Regla: RN-006-02 — El motivo es un código de un catálogo cerrado que distingue mayúsculas:
#   `FRAUD_SUSPECTED` (sospecha de fraude), `AMOUNT_OVER_THRESHOLD` (monto sobre el umbral),
#   `INSUFFICIENT_OR_CONTRADICTORY_INFO` (información insuficiente o contradictoria),
#   `INCONCLUSIVE_RULES` (reglas no concluyentes), `UNRECOVERABLE_SYSTEM_FAILURE` (falla no
#   recuperable del sistema), `IDENTITY_VERIFICATION_FAILED` (verificación de identidad fallida o
#   agotada) y `OTHER` (otro). Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`.
# Regla: RN-006-10 — Validación de entrada: `conversation_id` obligatorio y no vacío tras
#   recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason`
#   obligatorio y del catálogo de RN-006-02; `transaction_id`, `card_id` y `dispute_id`
#   opcionales (ausentes o `null`) y, si se envían, de 1 a 64 caracteres tras recortar (vacío o
#   solo espacios ⇒ `INVALID_INPUT`); `prior_actions` y `note` según RN-006-05 y RN-006-07. Toda
#   violación ⇒ `INVALID_INPUT`, sin derivación registrada.
# AC-006-03 · Art. 3
@pytest.mark.parametrize("reason", ["FRAUD", "fraud_suspected", "sospecha de fraude", "", None])
def test_ac_006_03_escalation_request_rejects_invalid_reason(reason: str | None) -> None:
    """AC-006-03: motivo fuera del catálogo, en minúsculas, vacío o ausente es INVALID_INPUT."""
    with pytest.raises(InvalidInputError) as exc:
        _create(reason=reason)
    assert exc.value.field == "reason"


# Regla: RN-006-02 — El motivo es un código de un catálogo cerrado que distingue mayúsculas:
#   `FRAUD_SUSPECTED` (sospecha de fraude), `AMOUNT_OVER_THRESHOLD` (monto sobre el umbral),
#   `INSUFFICIENT_OR_CONTRADICTORY_INFO` (información insuficiente o contradictoria),
#   `INCONCLUSIVE_RULES` (reglas no concluyentes), `UNRECOVERABLE_SYSTEM_FAILURE` (falla no
#   recuperable del sistema), `IDENTITY_VERIFICATION_FAILED` (verificación de identidad fallida o
#   agotada) y `OTHER` (otro). Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`.
# AC-006-02 · Art. 3
@pytest.mark.parametrize("code", _REASONS)
def test_ac_006_02_escalation_request_accepts_every_reason(code: str) -> None:
    """AC-006-02: los siete códigos del catálogo son motivos válidos."""
    request = _create(reason=code)
    assert request.reason is EscalationReason(code)


# Regla: RN-006-05 — `prior_actions` es una lista de códigos de un catálogo cerrado que
#   distingue mayúsculas: `DISPUTE_OPENED` (se abrió una disputa) y `CARD_BLOCKED` (se bloqueó la
#   tarjeta). Ausente, `null` o vacía significa que no se realizó ninguna acción. Coherencia:
#   `DISPUTE_OPENED` exige `dispute_id` y `transaction_id`; `dispute_id` sin `DISPUTE_OPENED` no
#   se admite; `CARD_BLOCKED` exige `card_id`. Un código fuera del catálogo, un código repetido o
#   una incoherencia ⇒ `INVALID_INPUT`.
# Regla: RN-006-10 — Validación de entrada: `conversation_id` obligatorio y no vacío tras
#   recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason`
#   obligatorio y del catálogo de RN-006-02; `transaction_id`, `card_id` y `dispute_id`
#   opcionales (ausentes o `null`) y, si se envían, de 1 a 64 caracteres tras recortar (vacío o
#   solo espacios ⇒ `INVALID_INPUT`); `prior_actions` y `note` según RN-006-05 y RN-006-07. Toda
#   violación ⇒ `INVALID_INPUT`, sin derivación registrada.
# AC-006-07 · Art. 3
@pytest.mark.parametrize(
    "entry",
    [
        {"prior_actions": ["DISPUTE_OPENED"], "transaction_id": "TX-L1"},
        {"prior_actions": ["DISPUTE_OPENED"], "dispute_id": "D-1"},
        {"dispute_id": "D-1", "transaction_id": "TX-L1"},
        {"prior_actions": ["CARD_BLOCKED"]},
        {"prior_actions": ["CARD_BLOCKED", "CARD_BLOCKED"], "card_id": "CARD-L1"},
        {"prior_actions": ["CARD_CANCELLED"]},
        {"prior_actions": ["card_blocked"], "card_id": "CARD-L1"},
    ],
    ids=[
        "dispute_opened_sin_dispute_id",
        "dispute_opened_sin_transaction_id",
        "dispute_id_sin_dispute_opened",
        "card_blocked_sin_card_id",
        "codigo_repetido",
        "codigo_fuera_del_catalogo",
        "codigo_en_minusculas",
    ],
)
def test_ac_006_07_escalation_request_rejects_incoherent_prior_actions(
    entry: dict[str, Any],
) -> None:
    """AC-006-07: acciones previas incoherentes, repetidas o fuera de catálogo: INVALID_INPUT."""
    with pytest.raises(InvalidInputError):
        _create(**entry)


# Regla: RN-006-07 — `note` es opcional. Se recorta; vacía o solo espacios equivale a sin nota
#   (`null`). Tras recortar admite de 1 a 300 caracteres; más ⇒ `INVALID_INPUT`. Toda secuencia
#   de 13 a 19 dígitos seguidos que contenga se guarda, se devuelve y se audita sustituida por
#   `[REDACTED]`. La nota es información para el analista y nunca se interpreta como instrucción
#   (RN-006-14).
# Regla: RN-006-10 — Validación de entrada: `conversation_id` obligatorio y no vacío tras
#   recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason`
#   obligatorio y del catálogo de RN-006-02; `transaction_id`, `card_id` y `dispute_id`
#   opcionales (ausentes o `null`) y, si se envían, de 1 a 64 caracteres tras recortar (vacío o
#   solo espacios ⇒ `INVALID_INPUT`); `prior_actions` y `note` según RN-006-05 y RN-006-07. Toda
#   violación ⇒ `INVALID_INPUT`, sin derivación registrada.
# AC-006-09 · Art. 3
@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"note": "x"}, "x"),
        ({"note": "n" * 300}, "n" * 300),
        ({"note": f"  {'n' * 300}  "}, "n" * 300),
        ({}, None),
        ({"note": None}, None),
        ({"note": ""}, None),
        ({"note": "   "}, None),
    ],
    ids=["1_caracter", "300", "300_con_espacios", "ausente", "none", "vacia", "solo_espacios"],
)
def test_ac_006_09_escalation_request_normalizes_note(
    kwargs: dict[str, Any], expected: str | None
) -> None:
    """AC-006-09: la nota se recorta, la vacía es None y 300 caracteres es el máximo."""
    request = _create(reason="OTHER", **kwargs)
    assert request.note == expected


# Regla: RN-006-07 — `note` es opcional. Se recorta; vacía o solo espacios equivale a sin nota
#   (`null`). Tras recortar admite de 1 a 300 caracteres; más ⇒ `INVALID_INPUT`. Toda secuencia
#   de 13 a 19 dígitos seguidos que contenga se guarda, se devuelve y se audita sustituida por
#   `[REDACTED]`. La nota es información para el analista y nunca se interpreta como instrucción
#   (RN-006-14).
# AC-006-09 · Art. 3
def test_ac_006_09_escalation_request_rejects_note_over_300_characters() -> None:
    """AC-006-09: una nota de 301 caracteres es INVALID_INPUT sobre el campo note."""
    with pytest.raises(InvalidInputError) as exc:
        _create(reason="OTHER", note="n" * 301)
    assert exc.value.field == "note"


# Regla: RN-006-07 — `note` es opcional. Se recorta; vacía o solo espacios equivale a sin nota
#   (`null`). Tras recortar admite de 1 a 300 caracteres; más ⇒ `INVALID_INPUT`. Toda secuencia
#   de 13 a 19 dígitos seguidos que contenga se guarda, se devuelve y se audita sustituida por
#   `[REDACTED]`. La nota es información para el analista y nunca se interpreta como instrucción
#   (RN-006-14).
# AC-006-10 · Art. 3
def test_ac_006_10_escalation_request_redacts_card_numbers_in_note() -> None:
    """AC-006-10: el número de tarjeta de la nota se guarda como [REDACTED]."""
    request = _create(note=f"Cliente dicta la tarjeta {_PAN} y pide ayuda")
    assert request.note == "Cliente dicta la tarjeta [REDACTED] y pide ayuda"
    assert _PAN not in (request.note or "")


# Regla: RN-006-10 — Validación de entrada: `conversation_id` obligatorio y no vacío tras
#   recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason`
#   obligatorio y del catálogo de RN-006-02; `transaction_id`, `card_id` y `dispute_id`
#   opcionales (ausentes o `null`) y, si se envían, de 1 a 64 caracteres tras recortar (vacío o
#   solo espacios ⇒ `INVALID_INPUT`); `prior_actions` y `note` según RN-006-05 y RN-006-07. Toda
#   violación ⇒ `INVALID_INPUT`, sin derivación registrada.
# AC-006-16 · Art. 3
@pytest.mark.parametrize(
    ("entry", "field"),
    [
        ({"idempotency_key": None}, "idempotency_key"),
        ({"idempotency_key": ""}, "idempotency_key"),
        ({"idempotency_key": "   "}, "idempotency_key"),
        ({"idempotency_key": "k" * 65}, "idempotency_key"),
        ({"conversation_id": None}, "conversation_id"),
        ({"conversation_id": ""}, "conversation_id"),
        ({"conversation_id": "   "}, "conversation_id"),
        ({"transaction_id": ""}, "transaction_id"),
        ({"transaction_id": "   "}, "transaction_id"),
        ({"transaction_id": "t" * 65}, "transaction_id"),
        ({"card_id": ""}, "card_id"),
        ({"card_id": "   "}, "card_id"),
        ({"card_id": "c" * 65}, "card_id"),
        (
            {"dispute_id": "", "prior_actions": ["DISPUTE_OPENED"], "transaction_id": "TX-L1"},
            "dispute_id",
        ),
        (
            {"dispute_id": "   ", "prior_actions": ["DISPUTE_OPENED"], "transaction_id": "TX-L1"},
            "dispute_id",
        ),
    ],
)
def test_ac_006_16_escalation_request_rejects_invalid_fields(
    entry: dict[str, Any], field: str
) -> None:
    """AC-006-16: claves, conversación e ids ausentes, vacíos o de 65 caracteres son inválidos."""
    with pytest.raises(InvalidInputError) as exc:
        _create(**entry)
    assert exc.value.field == field


# Regla: RN-006-10 — Validación de entrada: `conversation_id` obligatorio y no vacío tras
#   recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason`
#   obligatorio y del catálogo de RN-006-02; `transaction_id`, `card_id` y `dispute_id`
#   opcionales (ausentes o `null`) y, si se envían, de 1 a 64 caracteres tras recortar (vacío o
#   solo espacios ⇒ `INVALID_INPUT`); `prior_actions` y `note` según RN-006-05 y RN-006-07. Toda
#   violación ⇒ `INVALID_INPUT`, sin derivación registrada.
# AC-006-16 · Art. 3
def test_ac_006_16_escalation_request_accepts_ids_of_exactly_64_characters() -> None:
    """AC-006-16: 64 caracteres es el borde válido de cada id."""
    request = _create(
        idempotency_key="k" * 64,
        transaction_id="t" * 64,
        card_id="c" * 64,
        dispute_id="d" * 64,
        prior_actions=["DISPUTE_OPENED"],
    )
    assert len(request.idempotency_key) == 64
    assert request.transaction_id == "t" * 64
    assert request.card_id == "c" * 64
    assert request.dispute_id == "d" * 64


# Soporte de tests: invariantes de EscalationRequest y Escalation · Art. 3
def test_escalation_request_trims_values() -> None:
    request = _create(
        conversation_id="  A  ",
        idempotency_key="  K-1 ",
        transaction_id=" TX-L1 ",
        card_id=" CARD-L1 ",
        dispute_id=" D-1 ",
        prior_actions=["DISPUTE_OPENED"],
    )
    assert request.conversation_id == "A"
    assert request.idempotency_key == "K-1"
    assert request.transaction_id == "TX-L1"
    assert request.card_id == "CARD-L1"
    assert request.dispute_id == "D-1"
    assert request.prior_actions == frozenset({PriorAction.DISPUTE_OPENED})


# Soporte de tests: invariantes de EscalationRequest y Escalation · Art. 3
@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({}, False),
        ({"note": "revisar"}, False),
        ({"transaction_id": "TX-L1"}, True),
        ({"card_id": "CARD-L1"}, True),
        (
            {"dispute_id": "D-1", "transaction_id": "TX-L1", "prior_actions": ["DISPUTE_OPENED"]},
            True,
        ),
    ],
    ids=["sin_datos", "solo_nota", "transaccion", "tarjeta", "disputa"],
)
def test_escalation_request_has_customer_data(entry: dict[str, Any], expected: bool) -> None:
    assert _create(**entry).has_customer_data is expected


# Soporte de tests: invariantes de EscalationRequest y Escalation · Art. 3
def test_escalation_request_without_prior_actions_has_empty_set() -> None:
    assert _create().prior_actions == frozenset()
    assert _create(prior_actions=[]).prior_actions == frozenset()


# Soporte de tests: invariantes de EscalationRequest y Escalation · Art. 3
@pytest.mark.parametrize("field", ["escalation_id", "conversation_id", "idempotency_key"])
def test_escalation_rejects_empty_required_text(field: str) -> None:
    with pytest.raises(InvalidInputError) as exc:
        _escalation(**{field: "  "})
    assert exc.value.field == field


# Soporte de tests: invariantes de EscalationRequest y Escalation · Art. 3
def test_escalation_rejects_naive_escalated_at() -> None:
    with pytest.raises(InvalidInputError) as exc:
        _escalation(escalated_at=datetime(2026, 10, 17, 15, 0))
    assert exc.value.field == "escalated_at"


# Soporte de tests: invariantes de EscalationRequest y Escalation · Art. 3
@pytest.mark.parametrize(
    "overrides",
    [
        {"customer_id": "C-0001"},
        {"transaction_id": "TX-L1"},
        {"card_id": "CARD-L1"},
        {"dispute_id": "D-1"},
        {"prior_actions": frozenset({PriorAction.CARD_BLOCKED})},
    ],
    ids=["customer_id", "transaction_id", "card_id", "dispute_id", "prior_actions"],
)
def test_escalation_limited_summary_rejects_customer_data(overrides: dict[str, Any]) -> None:
    limited: dict[str, Any] = {
        "identity_verified": False,
        "customer_id": None,
        "transaction_id": None,
        "card_id": None,
        "dispute_id": None,
        "prior_actions": frozenset(),
    }
    assert _escalation(**limited).customer_id is None
    limited.update(overrides)
    with pytest.raises(InvalidInputError):
        _escalation(**limited)


# Soporte de tests: invariantes de EscalationRequest y Escalation · Art. 3
@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({}, True),
        ({"reason": "OTHER"}, False),
        ({"transaction_id": "TX-L2"}, False),
        ({"card_id": "CARD-L2"}, False),
        ({"card_id": None, "prior_actions": None}, False),
        ({"prior_actions": None}, False),
        ({"note": "otra"}, False),
        ({"note": None}, False),
        ({"note": "  revisar "}, True),
        ({"conversation_id": "B", "idempotency_key": "K-2"}, True),
    ],
    ids=[
        "igual",
        "otro_motivo",
        "otra_transaccion",
        "otra_tarjeta",
        "tarjeta_omitida",
        "acciones_omitidas",
        "otra_nota",
        "nota_omitida",
        "nota_sin_normalizar",
        "claves_no_se_comparan",
    ],
)
def test_escalation_same_request(entry: dict[str, Any], expected: bool) -> None:
    escalation = _escalation()
    base: dict[str, Any] = {
        "transaction_id": "TX-L1",
        "card_id": "CARD-L1",
        "prior_actions": ["CARD_BLOCKED"],
        "note": "revisar",
    }
    base.update(entry)
    assert escalation.same_request(_create(**base)) is expected


# Soporte de tests: invariantes de EscalationRequest y Escalation · Art. 3
def test_escalation_same_request_compares_prior_actions_as_set() -> None:
    both: dict[str, Any] = {
        "transaction_id": "TX-L1",
        "card_id": "CARD-L1",
        "dispute_id": "D-1",
        "note": "revisar",
    }
    escalation = _escalation(
        dispute_id="D-1",
        prior_actions=frozenset({PriorAction.CARD_BLOCKED, PriorAction.DISPUTE_OPENED}),
    )
    forward = _create(prior_actions=["DISPUTE_OPENED", "CARD_BLOCKED"], **both)
    backward = _create(prior_actions=["CARD_BLOCKED", "DISPUTE_OPENED"], **both)
    assert escalation.same_request(forward)
    assert escalation.same_request(backward)
    assert not escalation.same_request(_create(prior_actions=["DISPUTE_OPENED"], **both))


# Soporte de tests: invariantes de EscalationRequest y Escalation · Art. 3
def test_escalation_ordered_prior_actions_follows_catalog_order() -> None:
    escalation = _escalation(
        dispute_id="D-1",
        prior_actions=frozenset({PriorAction.CARD_BLOCKED, PriorAction.DISPUTE_OPENED}),
    )
    assert escalation.ordered_prior_actions() == (
        PriorAction.DISPUTE_OPENED,
        PriorAction.CARD_BLOCKED,
    )
    assert _escalation(prior_actions=frozenset()).ordered_prior_actions() == ()
