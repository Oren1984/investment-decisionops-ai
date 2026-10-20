import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, created_at, uuid_pk


class CalendarEvent(Base):
    """Stored events. Exchange sessions and holidays are computed, not stored."""

    __tablename__ = "calendar_event"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # reminder | research_cycle | economic
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(TS)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # user | mock | external
    source_name: Mapped[str | None] = mapped_column(String(120))
    fetched_at: Mapped[datetime | None] = mapped_column(TS)
    venue_mic: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (Index("ix_calendar_event_start", "starts_at"),)


class ResearchTimer(Base):
    """User-started, purely informational timer. It has no path to order submission."""

    __tablename__ = "research_timer"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(TS)
