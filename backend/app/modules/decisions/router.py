import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DB

from app.core import audit
from app.core.authz import Principal, perm
from app.core.db import get_db
from app.core.errors import Conflict, NotFound
from app.modules.decisions import service
from app.modules.decisions.models import (
    Decision,
    DecisionEvent,
    DecisionReview,
    DecisionVersion,
    EvidenceSnapshot,
    Lesson,
    ProposedAction,
)
from app.modules.decisions.service import RUBRIC, snapshot_view, workflow_bar
from app.modules.settings.service import trading_mode
from app.modules.workflows.models import WorkflowRun

router = APIRouter(prefix="/api", tags=["decisions"])


class DecisionIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    question: str = Field(min_length=10, max_length=4000)
    instrument_ids: list[uuid.UUID] = []
    start_run: bool = True
    mode: Literal["deterministic", "model"] = "deterministic"


class DecisionEdit(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    question: str | None = Field(default=None, min_length=10, max_length=4000)
    instrument_ids: list[uuid.UUID] | None = None


@router.get("/decisions")
def list_decisions(status: str | None = None, db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:decisions"))):
    stmt = select(Decision).order_by(Decision.updated_at.desc())
    if status:
        stmt = stmt.where(Decision.status == status)
    return [service.decision_summary(db, d) for d in db.scalars(stmt)]


@router.post("/decisions")
def create(body: DecisionIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:decisions"))):
    from app.modules.workflows.service import start_run

    d = service.create_decision(db, principal, body.title, body.question, body.instrument_ids, trading_mode(db))
    run = start_run(db, principal, d, body.mode) if body.start_run else None
    return {**service.decision_summary(db, d), "run_id": str(run.id) if run else None}


@router.get("/workflow/current")
def current_workflow(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:decisions"))):
    active = db.scalar(select(WorkflowRun).where(WorkflowRun.status.in_(("queued", "running")))
                       .order_by(WorkflowRun.created_at.desc()))
    d = db.get(Decision, active.decision_id) if active else db.scalar(
        select(Decision).where(Decision.status.notin_(("closed",))).order_by(Decision.updated_at.desc()))
    return workflow_bar(db, d) if d else None


@router.get("/decisions/insights")
def insights(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:decisions"))):
    return service.insights(db)


@router.get("/lessons")
def lessons(q: str | None = None, tag: str | None = None, db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:decisions"))):
    stmt = select(Lesson, Decision).join(Decision, Decision.id == Lesson.decision_id).order_by(Lesson.created_at.desc())
    if q:
        stmt = stmt.where(or_(Lesson.text.ilike(f"%{q}%"), Decision.title.ilike(f"%{q}%")))
    if tag:
        stmt = stmt.where(Lesson.tags.contains([tag.lower()]))
    return [{"id": str(lesson.id), "text": lesson.text, "tags": lesson.tags, "decision_id": str(d.id),
             "decision_title": d.title, "created_at": lesson.created_at} for lesson, d in db.execute(stmt.limit(100))]


@router.get("/decisions/{decision_id}")
def get_decision(decision_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:decisions"))):
    from app.modules.orders.models import OrderTicket

    d = service.get_decision(db, decision_id)
    snap = service.latest_snapshot(db, d.id)
    versions = db.scalars(select(DecisionVersion).where(DecisionVersion.decision_id == d.id)
                          .order_by(DecisionVersion.version_no))
    events = db.scalars(select(DecisionEvent).where(DecisionEvent.decision_id == d.id).order_by(DecisionEvent.at))
    reviews = db.scalars(select(DecisionReview).where(DecisionReview.decision_id == d.id)
                         .order_by(DecisionReview.created_at))
    lessons_ = db.scalars(select(Lesson).where(Lesson.decision_id == d.id).order_by(Lesson.created_at))
    orders = db.scalars(select(OrderTicket).where(OrderTicket.decision_id == d.id).order_by(OrderTicket.created_at))
    return {
        **service.decision_summary(db, d),
        "workflow": workflow_bar(db, d),
        "snapshot": {"id": str(snap.id), "hash": snap.snapshot_hash, "integrity_status": snap.integrity_status,
                     "checks_passed": snap.checks_passed, "checks_total": snap.checks_total,
                     "created_at": snap.created_at} if snap else None,
        "versions": [{"version_no": v.version_no, "kind": v.kind, "outcome": v.outcome, "rationale": v.rationale,
                      "explanation": v.explanation, "snapshot_id": str(v.snapshot_id) if v.snapshot_id else None,
                      "created_at": v.created_at} for v in versions],
        "events": [{"at": e.at, "kind": e.kind, "summary": e.summary} for e in events],
        "assumptions": service.assumptions_for(db, d.id),
        "proposals": service.proposals_for(db, d.id),
        "reviews": [{"id": str(r.id), "created_at": r.created_at, "process_rubric": r.process_rubric,
                     "process_score": r.process_score, "process_max": r.process_max,
                     "outcome_return_pct": float(r.outcome_return_pct) if r.outcome_return_pct is not None else None,
                     "benchmark_return_pct": float(r.benchmark_return_pct) if r.benchmark_return_pct is not None else None,
                     "assumption_observations": r.assumption_observations, "notes": r.notes,
                     "quadrant": service.quadrant(r)} for r in reviews],
        "lessons": [{"id": str(x.id), "text": x.text, "tags": x.tags} for x in lessons_],
        "orders": [{"id": str(o.id), "status": o.status, "side": o.side, "quantity": float(o.quantity),
                    "mode": o.mode} for o in orders],
        "rubric": RUBRIC,
    }


@router.patch("/decisions/{decision_id}")
def edit(decision_id: uuid.UUID, body: DecisionEdit, db: DB = Depends(get_db, scope="function"),
         principal: Principal = Depends(perm("write:decisions"))):
    d = service.get_decision(db, decision_id)
    if d.status not in ("draft", "blocked", "cancelled"):
        raise Conflict("not_editable", "Only draft, blocked or cancelled decisions can be edited. "
                       "Decided records are changed through a correction.")
    if body.title:
        d.title = body.title
    if body.question:
        d.question = body.question
    if body.instrument_ids is not None:
        d.instrument_ids = [str(i) for i in body.instrument_ids]
    audit.record(db, "decision.edited", actor=principal, object_type="decision", object_id=d.id)
    return service.decision_summary(db, d)


@router.get("/decisions/{decision_id}/evidence")
def evidence(decision_id: uuid.UUID, snapshot_id: uuid.UUID | None = None, db: DB = Depends(get_db, scope="function"),
             _=Depends(perm("read:decisions"))):
    d = service.get_decision(db, decision_id)
    snap = db.get(EvidenceSnapshot, snapshot_id) if snapshot_id else service.latest_snapshot(db, d.id)
    if snap is None or snap.decision_id != d.id:
        raise NotFound("Evidence snapshot")
    return snapshot_view(db, snap)


@router.get("/decisions/{decision_id}/replay")
def replay(decision_id: uuid.UUID, version: int | None = Query(default=None, ge=1), db: DB = Depends(get_db, scope="function"),
           _=Depends(perm("read:decisions"))):
    """Replay reads ONLY the frozen snapshot bound to the version, never live data."""
    d = service.get_decision(db, decision_id)
    v = db.scalar(select(DecisionVersion).where(DecisionVersion.decision_id == d.id,
                                                DecisionVersion.version_no == (version or d.current_version)))
    if v is None or v.snapshot_id is None:
        raise NotFound("Decision version")
    snap = db.get(EvidenceSnapshot, v.snapshot_id)
    return {"version": {"version_no": v.version_no, "kind": v.kind, "outcome": v.outcome, "rationale": v.rationale,
                        "explanation": v.explanation, "created_at": v.created_at},
            "decision": {"id": str(d.id), "title": d.title, "question": d.question},
            **snapshot_view(db, snap)}


class DecideIn(BaseModel):
    outcome: Literal["accept", "reject", "defer"]
    rationale: str = Field(min_length=10, max_length=4000)


class CorrectionIn(DecideIn):
    explanation: str = Field(min_length=10, max_length=2000)


@router.post("/decisions/{decision_id}/decide")
def decide(decision_id: uuid.UUID, body: DecideIn, db: DB = Depends(get_db, scope="function"),
           principal: Principal = Depends(perm("write:decisions"))):
    d = service.get_decision(db, decision_id)
    v = service.record_decision(db, principal, d, body.outcome, body.rationale)
    return {"version_no": v.version_no, "status": d.status}


@router.post("/decisions/{decision_id}/corrections")
def correct(decision_id: uuid.UUID, body: CorrectionIn, db: DB = Depends(get_db, scope="function"),
            principal: Principal = Depends(perm("write:decisions"))):
    d = service.get_decision(db, decision_id)
    v = service.correct_decision(db, principal, d, body.outcome, body.rationale, body.explanation)
    return {"version_no": v.version_no, "status": d.status}


class Observation(BaseModel):
    assumption_code: str
    observation: str = Field(max_length=1000)
    held: bool | None = None


class LessonIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    tags: list[str] = []


class ReviewIn(BaseModel):
    process_rubric: dict[str, int]
    outcome_return_pct: Decimal | None = None
    benchmark_return_pct: Decimal | None = None
    assumption_observations: list[Observation] = []
    notes: str | None = Field(default=None, max_length=4000)
    lessons: list[LessonIn] = []
    close: bool = False


@router.post("/decisions/{decision_id}/reviews")
def review(decision_id: uuid.UUID, body: ReviewIn, db: DB = Depends(get_db, scope="function"),
           principal: Principal = Depends(perm("write:decisions"))):
    d = service.get_decision(db, decision_id)
    data = body.model_dump()
    data["assumption_observations"] = [o.model_dump() for o in body.assumption_observations]
    r = service.submit_review(db, principal, d, data)
    return {"id": str(r.id), "status": d.status, "quadrant": service.quadrant(r)}


@router.post("/proposals/{proposal_id}/dismiss")
def dismiss(proposal_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:decisions"))):
    p = db.get(ProposedAction, proposal_id)
    if p is None:
        raise NotFound("Suggestion")
    p.status = "dismissed"
    audit.record(db, "decision.proposal_dismissed", actor=principal, object_type="proposed_action", object_id=p.id)
    return {"ok": True}
