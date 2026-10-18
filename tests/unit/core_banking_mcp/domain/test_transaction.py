"""Tests de los value objects Transaction, TransactionStatus y CustomerCard."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.transaction import (
    CustomerCard,
    Transaction,
    TransactionStatus,
)

_OCCURRED_AT = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)


def _transaction(**overrides: object) -> Transaction:
    base = Transaction(
        transaction_id="TX-0001",
        card_id="CARD-0001",
        card_last4="4321",
        occurred_at=_OCCURRED_AT,
        merchant="Comercio Ficticio",
        amount=Decimal("125000"),
        currency="COP",
        status=TransactionStatus.CONFIRMED,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


# Regla: RN-003-09 — Se devuelven transacciones en cualquier estado: confirmada (`CONFIRMED`), pendiente (`PENDING`) o reversada (`REVERSED`). El monto es siempre el original y positivo; la reversión se ve solo en el estado.  # noqa: E501
# AC-003-03 · Art. 3
@pytest.mark.parametrize(
    "status",
    list(TransactionStatus),
    ids=["confirmed", "pending", "reversed"],
)
def test_ac_003_03_transaction_accepts_every_status(status: TransactionStatus) -> None:
    """AC-003-03: la transacción admite los tres estados con monto 125000."""
    transaction = _transaction(status=status)

    assert transaction.status is status
    assert transaction.amount == Decimal("125000")
    assert {s.value for s in TransactionStatus} == {"CONFIRMED", "PENDING", "REVERSED"}


# Regla: RN-003-09 — Se devuelven transacciones en cualquier estado: confirmada (`CONFIRMED`), pendiente (`PENDING`) o reversada (`REVERSED`). El monto es siempre el original y positivo; la reversión se ve solo en el estado.  # noqa: E501
# Regla: RN-003-12 — Cada transacción devuelta contiene solo: `transaction_id`, `occurred_at`, `merchant`, `amount` (texto decimal positivo con exactamente 2 decimales), `currency` (código ISO 4217, p. ej. `COP`, `USD`), `status`, `card_id` y `masked_card`.  # noqa: E501
# AC-003-16 · Art. 3
@pytest.mark.parametrize(
    ("amount", "currency"),
    [
        (Decimal("125000"), "COP"),
        (Decimal("49.9"), "USD"),
        (Decimal("0.05"), "USD"),
    ],
    ids=["entero-cop", "un-decimal-usd", "centavos-usd"],
)
def test_ac_003_16_transaction_accepts_amounts_with_up_to_two_decimals(
    amount: Decimal, currency: str
) -> None:
    """AC-003-16: montos Decimal con hasta 2 decimales y moneda ISO 4217."""
    transaction = _transaction(amount=amount, currency=currency)

    assert transaction.amount == amount
    assert isinstance(transaction.amount, Decimal)
    assert transaction.currency == currency


# Soporte de tests: invariantes de Transaction · Art. 3
@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": Decimal("0")},
        {"amount": Decimal("-1")},
        {"amount": Decimal("1.005")},
        {"currency": "cop"},
        {"currency": "CO"},
        {"currency": "COPX"},
        {"currency": "C0P"},
        {"occurred_at": datetime(2026, 9, 10, 15, 0)},
        {"transaction_id": ""},
        {"card_id": ""},
        {"merchant": ""},
        {"card_last4": "432"},
        {"card_last4": "43211"},
        {"card_last4": "43a1"},
    ],
    ids=[
        "monto-cero",
        "monto-negativo",
        "monto-tres-decimales",
        "moneda-minuscula",
        "moneda-2-letras",
        "moneda-4-letras",
        "moneda-con-digito",
        "fecha-sin-zona",
        "transaction-id-vacio",
        "card-id-vacio",
        "comercio-vacio",
        "last4-3-digitos",
        "last4-5-digitos",
        "last4-no-numerico",
    ],
)
def test_transaction_rejects_invalid_fields(overrides: dict[str, object]) -> None:
    with pytest.raises(InvalidInputError):
        _transaction(**overrides)


# Regla: RN-007-30 — merchant_country es un código ISO 3166-1 alfa-2 (2 letras ASCII mayúsculas), por defecto "CO".  # noqa: E501
# AC-007-33 · Art. 3
@pytest.mark.parametrize(
    "bad", ["co", "COL", "", "C1"], ids=["minuscula", "3-letras", "vacio", "digito"]
)
def test_ac_007_33_transaction_rejects_invalid_merchant_country(bad: str) -> None:
    """AC-007-33: merchant_country inválido lanza InvalidInputError; "US" se conserva; defecto "CO"."""  # noqa: E501
    with pytest.raises(InvalidInputError) as exc:
        _transaction(merchant_country=bad)
    assert exc.value.field == "merchant_country"

    assert _transaction(merchant_country="US").merchant_country == "US"
    assert _transaction().merchant_country == "CO"


# Soporte de tests: invariantes de CustomerCard · Art. 3
@pytest.mark.parametrize(
    ("card_id", "last4"),
    [("", "4321"), ("CARD-0001", "432"), ("CARD-0001", "abcd")],
    ids=["card-id-vacio", "last4-corto", "last4-no-numerico"],
)
def test_customer_card_rejects_invalid_fields(card_id: str, last4: str) -> None:
    with pytest.raises(InvalidInputError):
        CustomerCard(card_id=card_id, last4=last4)


# Soporte de tests: construcción válida de CustomerCard · Art. 3
def test_customer_card_accepts_valid_fields() -> None:
    card = CustomerCard(card_id="CARD-0001", last4="4321")

    assert (card.card_id, card.last4) == ("CARD-0001", "4321")
