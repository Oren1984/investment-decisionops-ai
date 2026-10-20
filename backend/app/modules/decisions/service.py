"""Decision records: creation, evidence views, replay, decisions, corrections, reviews and lessons."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.authz import Principal
from app.core.clock import utcnow
from app.core.errors import AppError, Conflict, NotFound
from app.modules.decisions.evidence import verify
from app.modules.decisions.models import (
    Assumption,
    Decision,
    DecisionEvent,
    DecisionReview,
    DecisionVersion,
    EvidenceItem,
    EvidenceSnapshot,
    Lesson,
    ProposedAction,
)
from app.modules.decisions.state import LABELS, NEXT_ACTION, STAGES, transition
from app.modules.workflows.models import WorkflowRun

RUBRIC = {
    "evidence_quality": "Sources were relevant, fresh and cited",
    "alternatives_considered": "Counterarguments and alternatives were weighed",
    "risk_sizing": "Position size matched the downside scenarios and limits",
    "followed_plan": "The decision followed the recorded rationale",
    "timing_discipline": "No rushed or emotional timing",
}
RUBRIC_MAX_PER_ITEM = 2


def get_decision(db: Session, decision_id: uuid.UUID) -> Decision:
    d = db.get(Decision, decision_id)
    if d is None:
        raise NotFound("Decision")
    return d


def latest_snapshot(db: Session, decision_id: uuid.UUID) -> EvidenceSnapshot | None:
    return db.scalar(select(EvidenceSnapshot).where(EvidenceSnapshot.decision_id == decision_id,
                                                    EvidenceSnapshot.frozen.is_(True))
                     .order_by(EvidenceSnapshot.created_at.desc()))


def snapshot_view(db: Session, snap: EvidenceSnapshot, *, share_mode: bool = False,
                  include_portfolio: bool = True) -> dict:
    items = db.scalars(select(EvidenceItem).where(EvidenceItem.snapshot_id == snap.id).order_by(EvidenceItem.ordinal))
    out = []
    for it in items:
        content, provenance = it.content, it.provenance
        if share_mode and it.kind == "source_quote":
            content = {"withheld": True, "reason": "Raw quote data is not shared (market-data licensing)."}
        if share_mode and it.kind == "portfolio_context" and not include_portfolio:
            content = {"withheld": True, "reason": "Portfolio context is not part of this share."}
        out.append({"id": str(it.id), "ordinal": it.ordinal, "kind": it.kind, "title": it.title, "content": content,
                    "provenance": provenance, "output_label": it.output_label, "item_hash": it.item_hash,
                    "source_removed_at": it.source_removed_at, "redacted_at": it.redacted_at,
                    "redaction_reason": it.redaction_reason})
    v = verify(db, snap)
    banner = None
    if snap.integrity_status == "redacted":
        when = min((i["redacted_at"] for i in out if i["redacted_at"]), default=None)
        banner = (f"Evidence incomplete: {v['items_redacted']} item(s) were erased"
                  + (f" on {when.date().isoformat()}" if when else "") + " at the owner's request. "
                  "The remaining items are unchanged and verified." if v["ok"] else
                  "Evidence incomplete and verification failed.")
    return {"snapshot_id": str(snap.id), "created_at": snap.created_at, "snapshot_hash": snap.snapshot_hash,
            "integrity_status": snap.integrity_status, "checks_passed": snap.checks_passed,
            "checks_total": snap.checks_total, "verification": v, "banner": banner, "items": out}


def workflow_bar(db: Session, d: Decision) -> dict:
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.decision_id == d.id).order_by(WorkflowRun.created_at.desc()))
    status = d.status
    order = STAGES
    idx = order.index(status) if status in order else -1
    stages = []
    for i, s in enumerate(order):
        stages.append({"key": s, "label": LABELS[s], "state": "done" if idx > i else "current" if idx == i else "todo"})
    blockers = []
    if status == "blocked" and d.blocked_reason:
        blockers.append(d.blocked_reason)
    if run and run.status in ("failed", "interrupted"):
        blockers.append(run.error or f"Run {run.status}")
    return {"decision_id": str(d.id), "title": d.title, "status": status, "status_label": LABELS.get(status, status),
            "stages": stages, "blockers": blockers, "next_action": NEXT_ACTION.get(status, ""),
            "run": {"id": str(run.id), "status": run.status, "mode": run.mode, "current_step": run.current_step}
            if run else None}


def create_decision(db: Session, principal: Principal, title: str, question: str, instrument_ids: list[uuid.UUID],
                    mode: str) -> Decision:
    d = Decision(owner_id=principal.user_id, title=title, question=question,
                 instrument_ids=[str(i) for i in instrument_ids], status="draft", mode=mode)
    db.add(d)
    db.flush()
    db.add(DecisionEvent(decision_id=d.id, at=utcnow(), kind="created", summary="Question recorded."))
    audit.record(db, "decision.created", actor=principal, object_type="decision", object_id=d.id)
    return d


def record_decision(db: Session, principal: Principal, d: Decision, outcome: str, rationale: str) -> DecisionVersion:
    snap = latest_snapshot(db, d.id)
    if d.status != "ready_for_decision" or snap is None:
        raise Conflict("not_ready", "The evidence package must be frozen (Ready for decision) before you decide.")
    transition(d, "decided")
    version = DecisionVersion(decision_id=d.id, version_no=d.current_version + 1, kind="decision", outcome=outcome,
                              rationale=rationale, snapshot_id=snap.id, created_by=principal.user_id)
    d.current_version, d.outcome, d.decided_at = version.version_no, outcome, utcnow()
    db.add(version)
    db.add(DecisionEvent(decision_id=d.id, at=utcnow(), kind="decided",
                         summary=f"Owner decision: {outcome}. Version {version.version_no}.",
                         details={"snapshot_id": str(snap.id)}))
    audit.record(db, "decision.decided", actor=principal, object_type="decision", object_id=d.id,
                 details={"outcome": outcome, "version": version.version_no, "snapshot_hash": snap.snapshot_hash})
    return version


def correct_decision(db: Session, principal: Principal, d: Decision, outcome: str, rationale: str,
                     explanation: str) -> DecisionVersion:
    if d.status not in ("decided", "execution_linked"):
        raise Conflict("not_decided", "Only decided records can be corrected.")
    prev = db.scalar(select(DecisionVersion).where(DecisionVersion.decision_id == d.id)
                     .order_by(DecisionVersion.version_no.desc()))
    version = DecisionVersion(decision_id=d.id, version_no=d.current_version + 1, kind="correction", outcome=outcome,
                              rationale=rationale, explanation=explanation,
                              snapshot_id=prev.snapshot_id if prev else None, created_by=principal.user_id)
    d.current_version, d.outcome = version.version_no, outcome
    db.add(version)
    db.add(DecisionEvent(decision_id=d.id, at=utcnow(), kind="corrected",
                         summary=f"Correction recorded as version {version.version_no}: {explanation[:200]}"))
    audit.record(db, "decision.corrected", actor=principal, object_type="decision", object_id=d.id,
                 details={"version": version.version_no})
    return version


def submit_review(db: Session, principal: Principal, d: Decision, body: dict) -> DecisionReview:
    if d.status in ("decided", "execution_linked"):
        transition(d, "under_review")
    if d.status != "under_review":
        raise Conflict("not_reviewable", "Decide first; reviews compare the recorded decision with what happened.")
    rubric = {k: max(0, min(RUBRIC_MAX_PER_ITEM, int(body["process_rubric"].get(k, 0)))) for k in RUBRIC}
    review = DecisionReview(decision_id=d.id, created_by=principal.user_id, process_rubric=rubric,
                            process_score=sum(rubric.values()), process_max=RUBRIC_MAX_PER_ITEM * len(RUBRIC),
                            outcome_return_pct=body.get("outcome_return_pct"),
                            benchmark_return_pct=body.get("benchmark_return_pct"),
                            assumption_observations=body.get("assumption_observations", []), notes=body.get("notes"))
    db.add(review)
    db.flush()
    for lesson in body.get("lessons", []):
        if lesson.get("text"):
            db.add(Lesson(decision_id=d.id, review_id=review.id, text=lesson["text"][:2000],
                          tags=[t.strip().lower()[:30] for t in lesson.get("tags", []) if t.strip()][:8]))
    db.add(DecisionEvent(decision_id=d.id, at=utcnow(), kind="review",
                         summary=f"Review recorded: process {review.process_score}/{review.process_max}."))
    if body.get("close"):
        transition(d, "closed")
        d.closed_at = utcnow()
        db.add(DecisionEvent(decision_id=d.id, at=utcnow(), kind="closed", summary="Decision closed after review."))
    audit.record(db, "decision.reviewed", actor=principal, object_type="decision", object_id=d.id)
    return review


def quadrant(review: DecisionReview) -> dict:
    process_good = review.process_score >= 0.6 * review.process_max
    outcome = review.outcome_return_pct
    bench = review.benchmark_return_pct or Decimal(0)
    outcome_good = None if outcome is None else outcome >= bench
    return {"process_good": process_good, "outcome_good": outcome_good}


def insights(db: Session) -> dict:
    cells = {"good_process_good_outcome": [], "good_process_bad_outcome": [], "bad_process_good_outcome": [],
             "bad_process_bad_outcome": [], "outcome_pending": []}
    for review, d in db.execute(select(DecisionReview, Decision).join(Decision, Decision.id == DecisionReview.decision_id)
                                .order_by(DecisionReview.created_at.desc())):
        q = quadrant(review)
        item = {"decision_id": str(d.id), "title": d.title, "process": f"{review.process_score}/{review.process_max}",
                "return_pct": float(review.outcome_return_pct) if review.outcome_return_pct is not None else None,
                "benchmark_pct": float(review.benchmark_return_pct) if review.benchmark_return_pct is not None else None}
        if q["outcome_good"] is None:
            cells["outcome_pending"].append(item)
        else:
            key = f"{'good' if q['process_good'] else 'bad'}_process_{'good' if q['outcome_good'] else 'bad'}_outcome"
            cells[key].append(item)
    tags = db.execute(select(func.jsonb_array_elements_text(Lesson.tags).label("t"), func.count())
                      .group_by("t").order_by(func.count().desc()).limit(20)).all()
    return {"cells": cells, "tags": [{"tag": t, "count": n} for t, n in tags],
            "note": "Process quality and outcome are graded separately: a good result does not prove good reasoning."}


def decision_summary(db: Session, d: Decision) -> dict:
    snap = latest_snapshot(db, d.id)
    return {"id": str(d.id), "title": d.title, "question": d.question, "status": d.status,
            "status_label": LABELS.get(d.status, d.status), "mode": d.mode, "outcome": d.outcome,
            "current_version": d.current_version, "created_at": d.created_at, "updated_at": d.updated_at,
            "decided_at": d.decided_at, "instrument_ids": d.instrument_ids, "blocked_reason": d.blocked_reason,
            "checks": {"passed": snap.checks_passed, "total": snap.checks_total} if snap else None,
            "integrity_status": snap.integrity_status if snap else None}


def validate_outcome(outcome: str) -> None:
    if outcome not in ("accept", "reject", "defer"):
        raise AppError("invalid_outcome", "Choose accept, reject or defer.", status_code=422)


def assumptions_for(db: Session, decision_id: uuid.UUID) -> list[dict]:
    return [{"code": a.code, "text": a.text, "metric": a.metric, "expected": a.expected}
            for a in db.scalars(select(Assumption).where(Assumption.decision_id == decision_id).order_by(Assumption.code))]


def proposals_for(db: Session, decision_id: uuid.UUID) -> list[dict]:
    return [{"id": str(p.id), "kind": p.kind, "payload": p.payload, "rationale": p.rationale,
             "output_label": p.output_label, "status": p.status, "created_at": p.created_at}
            for p in db.scalars(select(ProposedAction).where(ProposedAction.decision_id == decision_id)
                                .order_by(ProposedAction.created_at))]
