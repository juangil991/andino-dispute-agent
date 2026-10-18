"""Repositorio de clientes sobre SQLAlchemy; mapea filas a entidades de dominio."""

from collections.abc import Mapping

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from core_banking_mcp.domain.models.customer import Card, CardStatus, Customer
from core_banking_mcp.domain.models.identity import IdentityRecord
from core_banking_mcp.domain.models.search import SearchCriteria
from core_banking_mcp.domain.normalization import normalize_document, normalize_name
from core_banking_mcp.infrastructure.outbound.persistence.models.tables import (
    CardRow,
    CustomerRow,
)

_SYNTHETIC_PAN_PREFIX = "000000000000"


class SqlAlchemyCustomerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        customer: Customer,
        pans: Mapping[str, str] | None = None,
        *,
        identity: IdentityRecord,
    ) -> None:
        """Inserta el cliente y sus tarjetas, calculando las columnas normalizadas.

        El dominio no guarda el PAN: `pans` mapea last4 -> PAN ficticio. Si falta
        una clave, se guarda un PAN sintético "000000000000" + last4.
        """
        pans = pans or {}
        stored_cards = self._session.scalar(select(func.count()).select_from(CardRow)) or 0
        row = CustomerRow(
            customer_id=customer.customer_id,
            full_name=customer.full_name,
            full_name_normalized=normalize_name(customer.full_name),
            document=customer.document,
            document_normalized=normalize_document(customer.document),
            birth_date=identity.birth_date,
            document_issue_date=identity.document_issue_date,
            cards=[
                CardRow(
                    pan=pans.get(card.last4, _SYNTHETIC_PAN_PREFIX + card.last4),
                    last4=card.last4,
                    status=card.status.value,
                    card_ref=f"CARD-{stored_cards + position:04d}",
                )
                for position, card in enumerate(customer.cards, start=1)
            ],
        )
        self._session.add(row)
        self._session.commit()

    def find_matching(self, criteria: SearchCriteria, limit: int) -> list[Customer]:
        conditions: list[ColumnElement[bool]] = []
        if criteria.document is not None:
            conditions.append(CustomerRow.document_normalized == criteria.document)
        if criteria.full_name is not None:
            conditions.append(CustomerRow.full_name_normalized == criteria.full_name)
        if criteria.card_last4 is not None:
            conditions.append(CustomerRow.cards.any(CardRow.last4 == criteria.card_last4))
        stmt = select(CustomerRow).where(*conditions).order_by(CustomerRow.customer_id).limit(limit)
        return [_to_entity(row) for row in self._session.scalars(stmt)]

    def find_identity(self, customer_id: str) -> IdentityRecord | None:
        row = self._session.get(CustomerRow, customer_id)
        if row is None:
            return None
        return IdentityRecord(row.birth_date, row.document_issue_date)


def _to_entity(row: CustomerRow) -> Customer:
    return Customer(
        customer_id=row.customer_id,
        full_name=row.full_name,
        document=row.document,
        cards=tuple(Card(c.last4, CardStatus(c.status), c.card_ref) for c in row.cards),
    )
