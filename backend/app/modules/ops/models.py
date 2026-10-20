import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, uuid_pk


class RequestMetric(Base):
    __tablename__ = "request_metric"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(TS, nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    route: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_request_metric_at", "at"),)


class Alert(Base):
    __tablename__ = "alert"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)  # dedupe key
    severity: Mapped[str] = mapped_column(String(8), nullable=False)  # info | warning | critical
    message: Mapped[str] = mapped_column(Text, nullable=False)
    help_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(TS, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(TS, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(TS)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (Index("ix_alert_open", "kind", "key", "resolved_at"),)


class ExportFile(Base):
    """In-app stored export. Lists which documents it contains so full erasure can delete it."""

    __tablename__ = "export_file"

    id: Mapped[uuid.UUID] = uuid_pk()
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)


class ModelVerification(Base):
    """Evidence that a real local model run happened (model name + digest)."""

    __tablename__ = "model_verification"

    id: Mapped[uuid.UUID] = uuid_pk()
    at: Mapped[datetime] = mapped_column(TS, nullable=False)
    model_name: Mapped[str] = mapped_column(String(80), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
