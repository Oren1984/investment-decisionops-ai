import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, created_at, updated_at, uuid_pk


class Meeting(Base):
    __tablename__ = "meeting"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(10), nullable=False)  # mock | manual | zoom (how it is scheduled)
    link_provider: Mapped[str | None] = mapped_column(String(16))  # zoom | google_meet | teams | other (None: mock)
    provider_status: Mapped[str] = mapped_column(String(16), nullable=False)
    # simulated | linked | scheduled | not_configured | unavailable | draft
    provider_meeting_id: Mapped[str | None] = mapped_column(String(64))
    join_url: Mapped[str | None] = mapped_column(Text)
    provider_error: Mapped[str | None] = mapped_column(Text)
    agenda: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class MeetingParticipant(Base):
    __tablename__ = "meeting_participant"

    id: Mapped[uuid.UUID] = uuid_pk()
    meeting_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("meeting.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
