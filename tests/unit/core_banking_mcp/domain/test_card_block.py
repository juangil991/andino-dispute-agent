"""Tests unitarios de los value objects de bloqueo de tarjeta (feature 005)."""

from datetime import UTC, datetime

import pytest

from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.card_block import (
    BlockReason,
    CardBlock,
    CardBlockRequest,
    OwnedCard,
)
from core_banking_mcp.domain.models.customer import CardStatus

BLOCKED_AT = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)


# Regla: RN-005-02 — El motivo es un código de un catálogo cerrado que distingue mayúsculas:
#   `FRAUD_SUSPECTED` (sospecha de fraude) y `LOST_OR_STOLEN` (tarjeta perdida o robada). Cualquier
#   otro valor, vacío o ausente ⇒ `INVALID_INPUT`.
# AC-005-03 · Art. 3
@pytest.mark.parametrize("reason", ["STOLEN", "fraud_suspected", "sospecha de fraude", "", None])
def test_ac_005_03_card_block_request_rejects_invalid_reason(reason: str | None) -> None:
    """AC-005-03: un motivo fuera del catálogo se rechaza con field = reason."""
    with pytest.raises(InvalidInputError) as exc:
        CardBlockRequest.create("conv-1", "card-1", reason, "key-1")
    assert exc.value.field == "reason"


# Regla: RN-005-02 — El motivo es un código de un catálogo cerrado que distingue mayúsculas:
#   `FRAUD_SUSPECTED` (sospecha de fraude) y `LOST_OR_STOLEN` (tarjeta perdida o robada). Cualquier
#   otro valor, vacío o ausente ⇒ `INVALID_INPUT`.
# AC-005-02 · Art. 3
@pytest.mark.parametrize("reason", list(BlockReason))
def test_ac_005_02_card_block_request_accepts_every_reason(reason: BlockReason) -> None:
    """AC-005-02: cada motivo permitido crea la solicitud."""
    request = CardBlockRequest.create("conv-1", "card-1", reason.value, "key-1")
    assert request.reason is reason


# Regla: RN-005-08 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar;
#   `card_id` obligatorio, de 1 a 64 caracteres tras recortar; `idempotency_key` obligatoria, de 1 a
#   64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-005-02. Toda violación ⇒
#   `INVALID_INPUT`, sin cambiar ninguna tarjeta.
# AC-005-10 · Art. 3
@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"card_id": None}, "card_id"),
        ({"card_id": ""}, "card_id"),
        ({"card_id": "   "}, "card_id"),
        ({"card_id": "c" * 65}, "card_id"),
        ({"idempotency_key": None}, "idempotency_key"),
        ({"idempotency_key": ""}, "idempotency_key"),
        ({"idempotency_key": "   "}, "idempotency_key"),
        ({"idempotency_key": "k" * 65}, "idempotency_key"),
        ({"conversation_id": None}, "conversation_id"),
        ({"conversation_id": ""}, "conversation_id"),
        ({"conversation_id": "   "}, "conversation_id"),
    ],
)
def test_ac_005_10_card_block_request_rejects_invalid_fields(
    kwargs: dict[str, str | None], field: str
) -> None:
    """AC-005-10: datos de entrada inválidos se rechazan con el campo correspondiente."""
    args: dict[str, str | None] = {
        "conversation_id": "conv-1",
        "card_id": "card-1",
        "reason": "FRAUD_SUSPECTED",
        "idempotency_key": "key-1",
    }
    args.update(kwargs)
    with pytest.raises(InvalidInputError) as exc:
        CardBlockRequest.create(**args)
    assert exc.value.field == field


# Regla: RN-005-08 — Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar;
#   `card_id` obligatorio, de 1 a 64 caracteres tras recortar; `idempotency_key` obligatoria, de 1 a
#   64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-005-02. Toda violación ⇒
#   `INVALID_INPUT`, sin cambiar ninguna tarjeta.
# AC-005-10 · Art. 3
def test_ac_005_10_card_block_request_accepts_64_chars_boundary() -> None:
    """AC-005-10: 64 caracteres es el borde exacto válido."""
    request = CardBlockRequest.create("conv-1", "c" * 64, "LOST_OR_STOLEN", "k" * 64)
    assert len(request.card_id) == 64
    assert len(request.idempotency_key) == 64


# Soporte de tests: normalización (trim) de CardBlockRequest · Art. 3
def test_card_block_request_trims_values() -> None:
    request = CardBlockRequest.create(" conv-1 ", " card-1 ", "FRAUD_SUSPECTED", " key-1 ")
    assert (request.conversation_id, request.card_id, request.idempotency_key) == (
        "conv-1",
        "card-1",
        "key-1",
    )


# Soporte de tests: invariantes de OwnedCard · Art. 3
def test_owned_card_valid_and_invariants() -> None:
    card = OwnedCard(" card-1 ", "1234", CardStatus.ACTIVE)
    assert card.card_id == "card-1"
    with pytest.raises(InvalidInputError):
        OwnedCard("", "1234", CardStatus.ACTIVE)
    for bad in ("123", "12345", "12a4", ""):
        with pytest.raises(InvalidInputError):
            OwnedCard("card-1", bad, CardStatus.ACTIVE)


def _block(**overrides: object) -> CardBlock:
    args: dict[str, object] = {
        "card_id": "card-1",
        "conversation_id": "conv-1",
        "idempotency_key": "key-1",
        "reason": BlockReason.FRAUD_SUSPECTED,
        "blocked_at": BLOCKED_AT,
    }
    args.update(overrides)
    return CardBlock(**args)  # type: ignore[arg-type]


# Soporte de tests: invariantes de CardBlock (textos vacíos y fecha naive) · Art. 3
def test_card_block_rejects_empty_texts_and_naive_datetime() -> None:
    for field in ("card_id", "conversation_id", "idempotency_key"):
        with pytest.raises(InvalidInputError) as exc:
            _block(**{field: "  "})
        assert exc.value.field == field
    with pytest.raises(InvalidInputError) as exc:
        _block(blocked_at=datetime(2026, 1, 1, 10, 0))
    assert exc.value.field == "blocked_at"


# Soporte de tests: normalización (trim) de CardBlock · Art. 3
def test_card_block_trims_values() -> None:
    assert _block(card_id=" card-1 ").card_id == "card-1"


# Soporte de tests: comparación same_request de CardBlock · Art. 3
def test_card_block_same_request() -> None:
    block = _block()
    assert block.same_request("card-1", BlockReason.FRAUD_SUSPECTED)
    assert not block.same_request("card-2", BlockReason.FRAUD_SUSPECTED)
    assert not block.same_request("card-1", BlockReason.LOST_OR_STOLEN)
