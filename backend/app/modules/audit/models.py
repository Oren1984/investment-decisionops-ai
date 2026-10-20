import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT


class AuditEvent(Base):
    """Append-only record of important changes and approvals. Never holds document content or secrets."""

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(TS, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    actor_role: Mapped[str | None] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(40))
    object_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (Index("ix_audit_at", "at"), Index("ix_audit_object", "object_type", "object_id"))


class ErasureLedger(Base):
    """Non-content list of erasures, re-applied after any restore (also mirrored to a file outside backups)."""

    __tablename__ = "erasure_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUIDT, primary_key=True)
    at: Mapped[datetime] = mapped_column(TS, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)  # document_erase | document_remove | delete_all
    entry: Mapped[dict] = mapped_column(JSONB, nullable=False)
