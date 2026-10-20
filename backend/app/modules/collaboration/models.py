import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, created_at, updated_at, uuid_pk

SHAREABLE_TYPES = ("decision", "document", "note", "meeting")


class ShareGrant(Base):
    """Object-level grant to a collaborator. Default deny for everything not granted."""

    __tablename__ = "share_grant"

    id: Mapped[uuid.UUID] = uuid_pk()
    object_type: Mapped[str] = mapped_column(String(16), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    grantee_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    permission: Mapped[str] = mapped_column(String(8), nullable=False)  # view | comment
    include_portfolio_context: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)

    __table_args__ = (Index("ix_grant_lookup", "grantee_id", "object_type", "object_id"),)


class Note(Base):
    __tablename__ = "note"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="SET NULL"))
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("meeting.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    redacted_at: Mapped[datetime | None] = mapped_column(TS)


class Comment(Base):
    __tablename__ = "comment"

    id: Mapped[uuid.UUID] = uuid_pk()
    object_type: Mapped[str] = mapped_column(String(16), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUIDT, nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at()
    redacted_at: Mapped[datetime | None] = mapped_column(TS)

    __table_args__ = (Index("ix_comment_object", "object_type", "object_id"),)


class ActionItem(Base):
    __tablename__ = "action_item"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"))
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("meeting.id", ondelete="CASCADE"))
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="SET NULL"))
    due_at: Mapped[datetime | None] = mapped_column(TS)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="open")  # open | done
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
