import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, created_at, uuid_pk


class User(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # owner | collaborator
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Jerusalem")
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(TS)
    disabled_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = created_at()


class Session(Base):
    __tablename__ = "user_session"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the cookie token
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at()
    last_seen_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    stepped_up_at: Mapped[datetime | None] = mapped_column(TS)
    user_agent: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (Index("ix_session_user", "user_id"),)


class RecoveryCode(Base):
    __tablename__ = "recovery_code"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TS)


class Invitation(Base):
    __tablename__ = "invitation"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="SET NULL"))


class LoginAttempt(Base):
    __tablename__ = "login_attempt"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(128), nullable=False)  # hashed email or client
    at: Mapped[datetime] = mapped_column(TS, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (Index("ix_login_attempt_key_at", "key", "at"),)


class SetupToken(Base):
    __tablename__ = "setup_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TS)
    note: Mapped[str | None] = mapped_column(Text)
