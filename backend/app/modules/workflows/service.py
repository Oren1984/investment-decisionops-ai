import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.authz import Principal
from app.core.clock import utcnow
from app.core.db import notify
from app.core.errors import AppError, Conflict
from app.core.logging import correlation_id
from app.modules.decisions.models import Decision, DecisionEvent
from app.modules.orders.models import StopState
from app.modules.workflows.jobs import enqueue
from app.modules.workflows.models import WorkflowRun

ACTIVE = ("queued", "running")
RUNNABLE_DECISION_STATES = {"draft", "blocked", "cancelled", "scoped", "researching", "analyzing", "scenarios",
                            "quality_review", "ready_for_decision"}


def stop_engaged(db: Session) -> bool:
    stop = db.get(StopState, 1)
    return bool(stop and stop.engaged)


def start_run(db: Session, principal: Principal, decision: Decision, mode: str) -> WorkflowRun:
    if stop_engaged(db):
        raise Conflict("stop_engaged", "Stop is engaged: new agent runs are blocked. Release Stop first.",
                       help_slug="approvals-and-stop")
    if decision.status not in RUNNABLE_DECISION_STATES:
        raise Conflict("decision_not_runnable", "This decision has already been decided. Record a correction or "
                       "start a new decision instead.")
    active = db.scalar(select(WorkflowRun).where(WorkflowRun.decision_id == decision.id,
                                                 WorkflowRun.status.in_(ACTIVE)))
    if active is not None:
        raise Conflict("run_active", "A run is already in progress for this decision.")
    model_name = model_digest = None
    if mode == "model":
        from app.modules.agents.llm import readiness

        ready = readiness(generate=False)
        if not ready["ready"]:
            raise AppError("model_unavailable", f"Model mode is not available: {ready['reason']}",
                           status_code=409, help_slug="local-model")
        model_name, model_digest = ready["model"], ready["digest"]
    run = WorkflowRun(decision_id=decision.id, mode=mode, status="queued", created_by=principal.user_id,
                      correlation_id=correlation_id.get(), model_name=model_name, model_digest=model_digest,
                      deadline_at=utcnow() + timedelta(minutes=15 if mode == "deterministic" else 45))
    db.add(run)
    db.flush()
    decision.blocked_reason = None
    db.add(DecisionEvent(decision_id=decision.id, at=utcnow(), kind="run_started",
                         summary=f"{'Model-enabled' if mode == 'model' else 'Deterministic'} research run started.",
                         details={"run_id": str(run.id)}))
    enqueue(db, "workflow_run", {"run_id": str(run.id)}, max_attempts=1)
    audit.record(db, "workflow.run_started", actor=principal, object_type="workflow_run", object_id=run.id,
                 details={"mode": mode})
    notify(db, "events", f"run:decision:{decision.id}")
    return run


def cancel_run(db: Session, principal: Principal, run: WorkflowRun) -> WorkflowRun:
    if run.status not in ACTIVE and run.status != "interrupted":
        raise Conflict("run_not_active", "This run is not active.")
    run.cancel_requested = True
    if run.status in ("queued", "interrupted"):
        run.status = "cancelled"
        run.finished_at = utcnow()
        decision = db.get(Decision, run.decision_id)
        if decision.status not in ("ready_for_decision", "blocked"):
            decision.status = "cancelled"
    audit.record(db, "workflow.cancel_requested", actor=principal, object_type="workflow_run", object_id=run.id)
    notify(db, "events", f"run:decision:{run.decision_id}")
    return run


def resume_run(db: Session, principal: Principal, run: WorkflowRun) -> WorkflowRun:
    if run.status not in ("interrupted", "failed", "cancelled"):
        raise Conflict("run_not_resumable", "Only interrupted, failed or cancelled runs can be resumed.")
    if stop_engaged(db):
        raise Conflict("stop_engaged", "Stop is engaged. Release Stop before resuming.", help_slug="approvals-and-stop")
    run.status, run.cancel_requested, run.error, run.finished_at = "queued", False, None, None
    run.resume_count += 1
    run.deadline_at = utcnow() + timedelta(minutes=15 if run.mode == "deterministic" else 45)
    enqueue(db, "workflow_run", {"run_id": str(run.id)}, max_attempts=1)
    audit.record(db, "workflow.run_resumed", actor=principal, object_type="workflow_run", object_id=run.id)
    notify(db, "events", f"run:decision:{run.decision_id}")
    return run


def mark_interrupted(db: Session, run_id: uuid.UUID, reason: str) -> None:
    run = db.get(WorkflowRun, run_id)
    if run is not None and run.status in ACTIVE:
        run.status, run.error = "interrupted", reason
        db.add(DecisionEvent(decision_id=run.decision_id, at=utcnow(), kind="run_interrupted", summary=reason))
        notify(db, "events", f"run:decision:{run.decision_id}")
