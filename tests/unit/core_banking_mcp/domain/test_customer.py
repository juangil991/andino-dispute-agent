"""Tests de las entidades de dominio Customer y Card (plan 001 §4)."""

import dataclasses

import pytest

from core_banking_mcp.domain.errors import DomainError, InvalidInputError
from core_banking_mcp.domain.models.customer import Card, CardStatus, Customer


def test_card_rejects_last4_that_is_not_four_digits() -> None:
    """AC-001-01: last4 debe tener exactamente cuatro dígitos."""
    for bad in ("123", "12345", "12a4", "", "    "):
        with pytest.raises(InvalidInputError) as exc:
            Card(last4=bad, status=CardStatus.ACTIVE)
        assert exc.value.field == "last4"


def test_card_accepts_valid_last4() -> None:
    """AC-001-01: una tarjeta válida conserva last4 y status."""
    card = Card(last4="0042", status=CardStatus.BLOCKED)
    assert card.last4 == "0042"
    assert card.status is CardStatus.BLOCKED


# Soporte de tests: Card expone card_id opcional · Art. 3
def test_card_exposes_optional_card_id() -> None:
    """Card expone card_id opcional, None por defecto."""
    assert Card("4321", CardStatus.ACTIVE, card_id="CARD-0001").card_id == "CARD-0001"
    assert Card("4321", CardStatus.ACTIVE).card_id is None


def test_card_status_members() -> None:
    """AC-001-01: estados de tarjeta soportados."""
    assert {s.name for s in CardStatus} == {"ACTIVE", "BLOCKED", "CANCELLED"}


@pytest.mark.parametrize("field", ["customer_id", "full_name", "document"])
def test_customer_rejects_empty_required_fields(field: str) -> None:
    """AC-001-03: Customer rechaza campos obligatorios vacíos."""
    kwargs = {"customer_id": "c-1", "full_name": "Ana Prueba", "document": "000111"}
    kwargs[field] = "  "
    with pytest.raises(InvalidInputError) as exc:
        Customer(**kwargs, cards=())
    assert exc.value.field == field


def test_customer_is_immutable_and_holds_cards() -> None:
    """AC-001-01: Customer es inmutable y guarda sus tarjetas como tupla."""
    card = Card(last4="1234", status=CardStatus.ACTIVE)
    customer = Customer(customer_id="c-1", full_name="Ana Prueba", document="000111", cards=(card,))
    assert customer.cards == (card,)
    with pytest.raises(dataclasses.FrozenInstanceError):
        customer.full_name = "Otro"  # type: ignore[misc]


def test_invalid_input_error_exposes_field_and_reason() -> None:
    """AC-001-03: InvalidInputError expone field y reason y es DomainError."""
    err = InvalidInputError("document", "vacío")
    assert isinstance(err, DomainError)
    assert err.field == "document"
    assert err.reason == "vacío"
