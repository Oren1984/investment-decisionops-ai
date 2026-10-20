import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, created_at, updated_at, uuid_pk


class OrderTicket(Base):
    """An order from ticket to final state. `mode` is stored on every record; modes never mix."""

    __tablename__ = "order_ticket"

    id: Mapped[uuid.UUID] = uuid_pk()
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    broker: Mapped[str] = mapped_column(String(16), nullable=False)
    account_id: Mapped[str] = mapped_column(String(40), nullable=False)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="SET NULL"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("instrument.id", ondelete="RESTRICT"), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # buy | sell
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    order_type: Mapped[str] = mapped_column(String(12), nullable=False)  # market | limit | stop | stop_limit
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    tif: Mapped[str] = mapped_column(String(4), nullable=False, default="DAY")  # DAY | GTC
    client_order_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(18), nullable=False, default="draft")
    preview: Mapped[dict | None] = mapped_column(JSONB)
    previewed_at: Mapped[datetime | None] = mapped_column(TS)
    broker_order_id: Mapped[str | None] = mapped_column(String(64))
    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal(0))
    avg_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    mock_scenario: Mapped[str | None] = mapped_column(String(24))
    submitted_at: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (Index("ix_order_status", "mode", "status"),)


class OrderApproval(Base):
    __tablename__ = "order_approval"

    id: Mapped[uuid.UUID] = uuid_pk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("order_ticket.id", ondelete="CASCADE"), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active")  # active | used | invalidated | expired


class OrderEvent(Base):
    __tablename__ = "order_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("order_ticket.id", ondelete="CASCADE"), nullable=False)
    at: Mapped[datetime] = mapped_column(TS, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(18))
    to_status: Mapped[str] = mapped_column(String(18), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (Index("ix_order_event_ticket", "ticket_id", "at"),)


class Execution(Base):
    __tablename__ = "execution"

    id: Mapped[uuid.UUID] = uuid_pk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("order_ticket.id", ondelete="CASCADE"), nullable=False)
    broker_exec_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    commission: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    at: Mapped[datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (UniqueConstraint("ticket_id", "broker_exec_id", name="uq_execution"),)


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_run"

    id: Mapped[uuid.UUID] = uuid_pk()
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    started_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)  # periodic | manual | reconnect
    checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mismatches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)


class StopState(Base):
    __tablename__ = "stop_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    engaged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    changed_at: Mapped[datetime | None] = mapped_column(TS)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    reason: Mapped[str | None] = mapped_column(Text)


class CancelBatch(Base):
    """Tracked 'cancel open orders' workflow, separate from the stop control."""

    __tablename__ = "cancel_batch"

    id: Mapped[uuid.UUID] = uuid_pk()
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = created_at()
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="running")  # running | done
    ticket_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    results: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    updated_at: Mapped[datetime] = updated_at()
