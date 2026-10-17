from datetime import date

import pytest

from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.identity import VerificationRequest

TODAY = date(2026, 10, 17)

_VALID = {
    "conversation_id": "conv-1",
    "customer_id": "cust-1",
    "birth_date": "1990-03-15",
    "document_issue_date": "2008-04-20",
}


def _create(**overrides: str | None) -> VerificationRequest:
    data = {**_VALID, **overrides}
    return VerificationRequest.create(
        conversation_id=data["conversation_id"],
        customer_id=data["customer_id"],
        birth_date=data["birth_date"],
        document_issue_date=data["document_issue_date"],
        today=TODAY,
    )


# Regla: RN-002-07 — validación de la entrada de verificación (fechas ISO reales, ids acotados)
# AC-002-08 · Art. 3
@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        pytest.param({"birth_date": ""}, "birth_date", id="empty_birth_date"),
        pytest.param({"birth_date": None}, "birth_date", id="none_birth_date"),
        pytest.param({"document_issue_date": ""}, "document_issue_date", id="empty_issue_date"),
        pytest.param({"document_issue_date": None}, "document_issue_date", id="none_issue_date"),
        pytest.param({"birth_date": "1990-02-31"}, "birth_date", id="impossible_birth_date"),
        pytest.param(
            {"document_issue_date": "2008-02-31"}, "document_issue_date", id="impossible_issue_date"
        ),
        pytest.param({"birth_date": "15/03/1990"}, "birth_date", id="birth_date_wrong_format"),
        pytest.param({"birth_date": "2026-10-18"}, "birth_date", id="future_birth_date"),
        pytest.param(
            {"document_issue_date": "2026-10-18"}, "document_issue_date", id="future_issue_date"
        ),
        pytest.param(
            {"birth_date": "1990-03-15", "document_issue_date": "1990-03-14"},
            "document_issue_date",
            id="issue_before_birth",
        ),
        pytest.param({"customer_id": None}, "customer_id", id="none_customer_id"),
        pytest.param({"customer_id": ""}, "customer_id", id="empty_customer_id"),
        pytest.param({"customer_id": "   "}, "customer_id", id="blank_customer_id"),
        pytest.param({"customer_id": "c" * 33}, "customer_id", id="customer_id_too_long"),
        pytest.param({"conversation_id": None}, "conversation_id", id="none_conversation_id"),
        pytest.param({"conversation_id": ""}, "conversation_id", id="empty_conversation_id"),
        pytest.param({"conversation_id": "   "}, "conversation_id", id="blank_conversation_id"),
    ],
)
def test_ac_002_08_invalid_request_is_rejected(
    overrides: dict[str, str | None], field: str
) -> None:
    """AC-002-08: datos de verificación inválidos son INVALID_INPUT."""
    with pytest.raises(InvalidInputError) as exc:
        _create(**overrides)
    assert exc.value.field == field


# Regla: RN-002-07 — fechas en formato ISO estricto AAAA-MM-DD
# AC-002-08 · Art. 3
@pytest.mark.parametrize(
    "value",
    [
        pytest.param("20260115", id="basic_format"),
        pytest.param("2026-W03-2", id="iso_week"),
        pytest.param(" 1990-03-15", id="leading_space"),
        pytest.param("1990-03-15 ", id="trailing_space"),
        pytest.param("١٩٩٠-٠٣-١٥", id="arabic_indic_digits"),
    ],
)
def test_ac_002_08_non_strict_iso_formats_are_rejected(value: str) -> None:
    """AC-002-08: solo se acepta AAAA-MM-DD en dígitos ASCII."""
    with pytest.raises(InvalidInputError) as exc:
        _create(birth_date=value)
    assert exc.value.field == "birth_date"


# Regla: RN-002-07 — la expedición no puede ser anterior al nacimiento
# AC-002-03 · Art. 3
def test_ac_002_03_swapped_dates_are_invalid() -> None:
    """AC-002-03: fechas intercambiadas (expedición anterior al nacimiento) son inválidas."""
    with pytest.raises(InvalidInputError):
        _create(birth_date="2008-04-20", document_issue_date="1990-03-15")


# Regla: RN-002-08 — "hoy" es la fecha del reloj inyectado
# AC-002-09 · Art. 3
def test_ac_002_09_request_date_limits() -> None:
    """AC-002-09: expedición igual a hoy y nacimiento igual a expedición son válidas."""
    today = _create(birth_date="2026-10-17", document_issue_date="2026-10-17")
    assert today.birth_date == TODAY
    assert today.document_issue_date == TODAY
    same = _create(birth_date="1990-03-15", document_issue_date="1990-03-15")
    assert same.birth_date == same.document_issue_date == date(1990, 3, 15)


# Regla: RN-002-07 — customer_id entre 1 y 32 caracteres
# AC-002-08 · Art. 3
def test_ac_002_08_customer_id_length_boundary_and_trimming() -> None:
    """AC-002-08: customer_id de 32 caracteres es válido y los ids se recortan."""
    request = _create(customer_id="  " + "c" * 32 + "  ", conversation_id="  conv-9  ")
    assert request.customer_id == "c" * 32
    assert request.conversation_id == "conv-9"
