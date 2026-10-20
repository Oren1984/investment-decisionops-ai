import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, created_at, uuid_pk


class Instrument(Base):
    __tablename__ = "instrument"

    id: Mapped[uuid.UUID] = uuid_pk()
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    venue_mic: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # equity | etf | fx | index
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False)  # equity | fx | index
    tradable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    not_tradable_reason: Mapped[str | None] = mapped_column(Text)
    broker_instrument_id: Mapped[str | None] = mapped_column(String(64))
    reference_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    volatility: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False, default=Decimal("0.015"))

    __table_args__ = (UniqueConstraint("venue_mic", "symbol", name="uq_instrument_venue_symbol"),)


class QuoteSnapshot(Base):
    """Latest quote per instrument. In Mock mode these are synthetic and labelled so everywhere."""

    __tablename__ = "quote_snapshot"

    instrument_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("instrument.id", ondelete="CASCADE"),
                                                     primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    change_pct: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=Decimal(0))
    as_of: Mapped[datetime] = mapped_column(TS, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="mock")  # mock | broker
    stale_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DataFeed(Base):
    __tablename__ = "data_feed"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_label: Mapped[str] = mapped_column(String(20), nullable=False)  # mock | external | computed
    state: Mapped[str] = mapped_column(String(20), nullable=False)  # not_configured | fresh | stale | error
    last_success_at: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)
    stale_after_seconds: Mapped[int] = mapped_column(nullable=False, default=300)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    instrument_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = created_at()
