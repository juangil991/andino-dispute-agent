"""Tablas SQLAlchemy del core bancario (plan §4). No cruzan al dominio (§3.2.4)."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class CustomerRow(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    full_name: Mapped[str] = mapped_column(String)
    full_name_normalized: Mapped[str] = mapped_column(String, index=True)
    document: Mapped[str] = mapped_column(String, unique=True)
    document_normalized: Mapped[str] = mapped_column(String, index=True, unique=True)

    cards: Mapped[list["CardRow"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan", order_by="CardRow.card_id"
    )


class CardRow(Base):
    __tablename__ = "cards"

    card_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"))
    pan: Mapped[str] = mapped_column(String)  # PAN ficticio (Art. 1)
    last4: Mapped[str] = mapped_column(String(4), index=True)
    status: Mapped[str] = mapped_column(String)

    customer: Mapped[CustomerRow] = relationship(back_populates="cards")
