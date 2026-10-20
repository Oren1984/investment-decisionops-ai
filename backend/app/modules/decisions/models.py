import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import TS, UUIDT, created_at, updated_at, uuid_pk


class Decision(Base):
    __tablename__ = "decision"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    instrument_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="mock")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome: Mapped[str | None] = mapped_column(String(10))  # accept | reject | defer
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    closed_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class DecisionVersion(Base):
    __tablename__ = "decision_version"

    id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="CASCADE"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # decision | correction
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)  # required for corrections
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("evidence_snapshot.id", ondelete="RESTRICT"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (UniqueConstraint("decision_id", "version_no", name="uq_decision_version"),)


class EvidenceSnapshot(Base):
    __tablename__ = "evidence_snapshot"

    id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("workflow_run.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    integrity_status: Mapped[str] = mapped_column(String(12), nullable=False, default="verified")  # verified | redacted
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checks_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EvidenceItem(Base):
    """One quote, data point, passage or agent output. Content is immutable once the snapshot is frozen,
    except through the controlled redaction operation (enforced by a database trigger)."""

    __tablename__ = "evidence_item"

    id: Mapped[uuid.UUID] = uuid_pk()
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("evidence_snapshot.id", ondelete="CASCADE"),
                                                   nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[dict | None] = mapped_column(JSONB)
    provenance: Mapped[dict | None] = mapped_column(JSONB)
    output_label: Mapped[str] = mapped_column(String(12), nullable=False)  # simulated | computed | model
    salt: Mapped[str | None] = mapped_column(String(64))
    item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)  # no FK: documents may be deleted
    source_removed_at: Mapped[datetime | None] = mapped_column(TS)
    redacted_at: Mapped[datetime | None] = mapped_column(TS)
    redaction_reason: Mapped[str | None] = mapped_column(String(40))
    redaction_event_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)

    __table_args__ = (
        UniqueConstraint("snapshot_id", "ordinal", name="uq_evidence_ordinal"),
        Index("ix_evidence_source_doc", "source_document_id"),
    )


class Assumption(Base):
    __tablename__ = "assumption"

    id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str | None] = mapped_column(String(80))
    expected: Mapped[str | None] = mapped_column(String(120))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT)

    __table_args__ = (UniqueConstraint("decision_id", "code", name="uq_assumption_code"),)


class DecisionEvent(Base):
    """Visible decision history (never rewritten silently)."""

    __tablename__ = "decision_event"

    id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="CASCADE"), nullable=False)
    at: Mapped[datetime] = mapped_column(TS, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (Index("ix_decision_event_decision", "decision_id", "at"),)


class DecisionReview(Base):
    __tablename__ = "decision_review"

    id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = created_at()
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("app_user.id", ondelete="SET NULL"))
    process_rubric: Mapped[dict] = mapped_column(JSONB, nullable=False)
    process_score: Mapped[int] = mapped_column(Integer, nullable=False)
    process_max: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    benchmark_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    assumption_observations: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    redacted_at: Mapped[datetime | None] = mapped_column(TS)


class Lesson(Base):
    __tablename__ = "lesson"

    id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="CASCADE"), nullable=False)
    review_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("decision_review.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = created_at()
    redacted_at: Mapped[datetime | None] = mapped_column(TS)


class ProposedAction(Base):
    """Inert suggestion from an agent. Never executed by the system; the owner acts through normal routes."""

    __tablename__ = "proposed_action"

    id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(UUIDT, ForeignKey("decision.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUIDT, ForeignKey("workflow_run.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # follow_up_research | order_intent | share | reminder
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    output_label: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open")  # open | dismissed | acted_on
    created_at: Mapped[datetime] = created_at()
