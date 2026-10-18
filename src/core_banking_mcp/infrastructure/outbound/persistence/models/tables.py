"""Tablas SQLAlchemy del core bancario (plan §4). No cruzan al dominio (§3.2.4)."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, text
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
    birth_date: Mapped[date] = mapped_column(Date)
    document_issue_date: Mapped[date] = mapped_column(Date)

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
    card_ref: Mapped[str] = mapped_column(String, unique=True, index=True)  # card_id opaco

    customer: Mapped[CustomerRow] = relationship(back_populates="cards")


class TransactionRow(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_card_id_occurred_at", "card_id", "occurred_at"),)

    transaction_id: Mapped[str] = mapped_column(String, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.card_id"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC sin zona
    merchant: Mapped[str] = mapped_column(String)
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String)


class DisputeRow(Base):
    __tablename__ = "disputes"
    __table_args__ = (
        Index("ux_disputes_conversation_key", "conversation_id", "idempotency_key", unique=True),
        Index(
            "ux_disputes_open_transaction",
            "transaction_id",
            unique=True,
            sqlite_where=text("status = 'OPEN'"),
        ),
    )

    dispute_id: Mapped[str] = mapped_column(String, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.transaction_id"))
    conversation_id: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    opened_at: Mapped[datetime] = mapped_column(DateTime)  # UTC sin zona
