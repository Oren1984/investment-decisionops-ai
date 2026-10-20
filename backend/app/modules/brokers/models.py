"""Mock broker's own state — the simulated 'broker side', kept separate from our order records so that
reconciliation is a genuine comparison between two sources."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, created_at, uuid_pk


class MockBrokerOrder(Base):
    __tablename__ = "mock_broker_order"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_ref: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)  # our client_order_id
    broker_order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    filled: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal(0))
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # working | partially_filled | filled | cancelled | rejected
    scenario: Mapped[str] = mapped_column(String(24), nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    executions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime | None] = mapped_column(TS)


class BrokerConnection(Base):
    __tablename__ = "broker_connection"

    mode: Mapped[str] = mapped_column(String(10), primary_key=True)
    broker: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # connected | disconnected | not_configured | disabled
    account_id: Mapped[str | None] = mapped_column(String(40))
    last_connected_at: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(String(400))
