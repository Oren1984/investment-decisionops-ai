import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, created_at, updated_at, uuid_pk


class WorkflowRun(Base):
    __tablename__ = "workflow_run"

    id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[str] = mapped_column(String(14), nullable=False)  # deterministic | model
    status: Mapped[str] = mapped_column(String(14), nullable=False, default="queued")
    # queued | running | succeeded | failed | cancelled | interrupted | blocked
    current_step: Mapped[str | None] = mapped_column(String(24))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deadline_at: Mapped[datetime | None] = mapped_column(TS)
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    error: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(String(80))
    model_digest: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="SET NULL"))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    resume_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    research_loops: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (Index("ix_run_decision", "decision_id"),)


class WorkflowStep(Base):
    """Each step writes only its own output, keyed (run, step, attempt), so restarts never duplicate work."""

    __tablename__ = "workflow_step"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("workflow_run.id", ondelete="CASCADE"), nullable=False)
    step: Mapped[str] = mapped_column(String(24), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(14), nullable=False)  # running | succeeded | failed | cancelled | skipped
    output_kind: Mapped[str | None] = mapped_column(String(12))  # simulated | computed | model | mixed
    output: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    model_name: Mapped[str | None] = mapped_column(String(80))
    model_digest: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_document_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    redacted_at: Mapped[datetime | None] = mapped_column(TS)

    __table_args__ = (UniqueConstraint("run_id", "step", "attempt", name="uq_step_attempt"),)


class ToolCallLog(Base):
    """Audit of MCP tool calls: tool, argument hash, duration, size — never content."""

    __tablename__ = "tool_call_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    tool: Mapped[str] = mapped_column(String(48), nullable=False)
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(40))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    result_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    at: Mapped[datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (Index("ix_tool_call_run", "run_id", "role"),)


class Job(Base):
    """Postgres-backed job queue (FOR UPDATE SKIP LOCKED + leases + heartbeats)."""

    __tablename__ = "job"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    run_after: Mapped[datetime] = mapped_column(TS, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    lease_until: Mapped[datetime | None] = mapped_column(TS)
    locked_by: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (Index("ix_job_claim", "status", "run_after"),)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(TS, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    current_job: Mapped[int | None] = mapped_column(BigInteger)
