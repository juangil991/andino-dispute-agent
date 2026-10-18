"""Tests de los value objects de disputa."""

from datetime import UTC, datetime

import pytest

from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.dispute import (
    Dispute,
    DisputeReason,
    DisputeRequest,
    DisputeStatus,
)

_OPENED_AT = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _create(
    conversation_id: str | None = "conv-1",
    transaction_id: str | None = "tx-1",
    reason: str | None = "OTHER",
    idempotency_key: str | None = "key-1",
) -> DisputeRequest:
    return DisputeRequest.create(conversation_id, transaction_id, reason, idempotency_key)


def _dispute(**overrides: object) -> Dispute:
    values: dict[str, object] = {
        "dispute_id": "disp-1",
        "conversation_id": "conv-1",
        "idempotency_key": "key-1",
        "transaction_id": "tx-1",
        "reason": DisputeReason.OTHER,
        "status": DisputeStatus.OPEN,
        "opened_at": _OPENED_AT,
    }
    values.update(overrides)
    return Dispute(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "reason", ["FRAUD", "unrecognized_charge", "no reconoce el cargo", "", None]
)
def test_ac_004_03_dispute_request_rejects_invalid_reason(reason: str | None) -> None:
    """AC-004-03: motivo fuera del catálogo, vacío o ausente es INVALID_INPUT.

    Cubre: RN-004-02, RN-004-09
    """
    with pytest.raises(InvalidInputError) as exc:
        _create(reason=reason)
    assert exc.value.field == "reason"


@pytest.mark.parametrize(
    "code",
    ["UNRECOGNIZED_CHARGE", "DUPLICATE_CHARGE", "INCORRECT_AMOUNT", "NOT_RECEIVED", "OTHER"],
)
def test_ac_004_02_dispute_request_accepts_every_reason(code: str) -> None:
    """AC-004-02: los cinco códigos del catálogo son motivos válidos.

    Cubre: HU-004-01, RN-004-02
    """
    request = _create(reason=code)
    assert request.reason is DisputeReason(code)


@pytest.mark.parametrize("field", ["transaction_id", "idempotency_key"])
@pytest.mark.parametrize("value", [None, "", "   ", "x" * 65])
def test_ac_004_13_dispute_request_rejects_invalid_ids(field: str, value: str | None) -> None:
    """AC-004-13: transaction_id e idempotency_key ausentes, vacíos o de más de 64.

    Cubre: RN-004-09
    """
    with pytest.raises(InvalidInputError) as exc:
        _create(**{field: value})
    assert exc.value.field == field


@pytest.mark.parametrize("value", [None, "", "   "])
def test_ac_004_13_dispute_request_rejects_invalid_conversation_id(value: str | None) -> None:
    """AC-004-13: conversation_id ausente, vacío o solo espacios.

    Cubre: RN-004-09
    """
    with pytest.raises(InvalidInputError) as exc:
        _create(conversation_id=value)
    assert exc.value.field == "conversation_id"


@pytest.mark.parametrize("field", ["transaction_id", "idempotency_key"])
def test_ac_004_13_dispute_request_accepts_64_characters(field: str) -> None:
    """AC-004-13: 64 caracteres es el borde exacto válido.

    Cubre: RN-004-09
    """
    request = _create(**{field: "x" * 64})
    assert getattr(request, field) == "x" * 64


# Soporte de tests: invariantes de Dispute · Art. 3
def test_dispute_request_trims_values() -> None:
    request = _create(
        conversation_id=" conv-1 ", transaction_id=" tx-1 ", idempotency_key=" key-1 "
    )
    assert (request.conversation_id, request.transaction_id, request.idempotency_key) == (
        "conv-1",
        "tx-1",
        "key-1",
    )


# Soporte de tests: invariantes de Dispute · Art. 3
@pytest.mark.parametrize(
    "field", ["dispute_id", "conversation_id", "idempotency_key", "transaction_id"]
)
def test_dispute_rejects_empty_ids(field: str) -> None:
    with pytest.raises(InvalidInputError) as exc:
        _dispute(**{field: "  "})
    assert exc.value.field == field


# Soporte de tests: invariantes de Dispute · Art. 3
def test_dispute_rejects_naive_opened_at() -> None:
    with pytest.raises(InvalidInputError) as exc:
        _dispute(opened_at=datetime(2026, 10, 17, 12, 0))
    assert exc.value.field == "opened_at"


# Soporte de tests: invariantes de Dispute · Art. 3
def test_dispute_same_request_requires_both_to_match() -> None:
    dispute = _dispute()
    assert dispute.same_request("tx-1", DisputeReason.OTHER)
    assert not dispute.same_request("tx-2", DisputeReason.OTHER)
    assert not dispute.same_request("tx-1", DisputeReason.DUPLICATE_CHARGE)
