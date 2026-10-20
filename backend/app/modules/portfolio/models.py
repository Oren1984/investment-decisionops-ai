import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, created_at, updated_at, uuid_pk


class Portfolio(Base):
    """One portfolio per trading mode; modes never share records."""

    __tablename__ = "portfolio"

    id: Mapped[uuid.UUID] = uuid_pk()
    mode: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)  # mock | paper | live
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ILS")
    account_id: Mapped[str | None] = mapped_column(String(40))
    as_of: Mapped[datetime | None] = mapped_column(TS)


class Position(Base):
    __tablename__ = "position"

    id: Mapped[uuid.UUID] = uuid_pk()
    portfolio_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=False)
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("instrument.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    as_of: Mapped[datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (UniqueConstraint("portfolio_id", "instrument_id", name="uq_position_instrument"),)


class CashBalance(Base):
    __tablename__ = "cash_balance"

    id: Mapped[uuid.UUID] = uuid_pk()
    portfolio_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    as_of: Mapped[datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (UniqueConstraint("portfolio_id", "currency", name="uq_cash_currency"),)


class ManualHolding(Base):
    """Assets held outside the broker (e.g. TASE holdings at an Israeli bank). Labelled 'Manual'."""

    __tablename__ = "manual_holding"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    venue_mic: Mapped[str | None] = mapped_column(String(10))
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False, default="equity")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    value_as_of: Mapped[datetime] = mapped_column(TS, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
