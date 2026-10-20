import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from app.config import get_settings
from app.core.authz import Principal, perm
from app.core.db import get_db
from app.core.errors import NotFound
from app.modules.decisions.models import Decision
from app.modules.mcp_tools.tools import ROLE_CALL_BUDGET, ROLE_TOOLS
from app.modules.workflows import service
from app.modules.workflows.models import ToolCallLog, WorkflowRun, WorkflowStep

router = APIRouter(tags=["workflows"])

STEP_LABELS = {"scope": "Scope (manager flow)", "manager_advice": "Advisory manager", "research": "Research",
               "analysis": "Portfolio & market analysis", "scenarios": "Scenario analysis",
               "critic": "Critic & quality review", "research_followup": "Follow-up research",
               "critic_followup": "Follow-up quality review"}


def run_out(run: WorkflowRun, steps: list[WorkflowStep] | None = None, tool_stats: dict | None = None) -> dict:
    out = {"id": str(run.id), "decision_id": str(run.decision_id), "mode": run.mode, "status": run.status,
           "current_step": run.current_step, "cancel_requested": run.cancel_requested,
           "created_at": run.created_at, "started_at": run.started_at, "finished_at": run.finished_at,
           "deadline_at": run.deadline_at, "error": run.error, "model_name": run.model_name,
           "model_digest": run.model_digest, "resume_count": run.resume_count, "correlation_id": run.correlation_id}
    if steps is not None:
        out["steps"] = [{
            "id": str(s.id), "step": s.step, "label": STEP_LABELS.get(s.step, s.step), "attempt": s.attempt,
            "status": s.status, "output_kind": s.output_kind, "output": s.output, "notes": s.notes,
            "started_at": s.started_at, "finished_at": s.finished_at, "duration_ms": s.duration_ms,
            "model_name": s.model_name, "model_digest": s.model_digest, "prompt_version": s.prompt_version,
            "tokens_in": s.tokens_in, "tokens_out": s.tokens_out, "tool_calls": s.tool_calls, "error": s.error,
            "redacted": s.redacted_at is not None,
        } for s in steps]
        out["tool_calls"] = tool_stats or {}
    return out


class RunIn(BaseModel):
    mode: Literal["deterministic", "model"] = "deterministic"


@router.post("/api/decisions/{decision_id}/runs")
def start(decision_id: uuid.UUID, body: RunIn, db: DB = Depends(get_db, scope="function"),
          principal: Principal = Depends(perm("write:decisions"))):
    d = db.get(Decision, decision_id)
    if d is None:
        raise NotFound("Decision")
    return run_out(service.start_run(db, principal, d, body.mode))


@router.get("/api/decisions/{decision_id}/runs")
def list_runs(decision_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:decisions"))):
    rows = db.scalars(select(WorkflowRun).where(WorkflowRun.decision_id == decision_id)
                      .order_by(WorkflowRun.created_at.desc()))
    return [run_out(r) for r in rows]


@router.get("/api/runs/recent")
def recent_runs(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:decisions"))):
    rows = db.execute(select(WorkflowRun, Decision.title).join(Decision, Decision.id == WorkflowRun.decision_id)
                      .order_by(WorkflowRun.created_at.desc()).limit(8)).all()
    return [{**run_out(r), "decision_title": title} for r, title in rows]


@router.get("/api/runs/{run_id}")
def get_run(run_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:decisions"))):
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise NotFound("Run")
    steps = list(db.scalars(select(WorkflowStep).where(WorkflowStep.run_id == run.id)
                            .order_by(WorkflowStep.started_at, WorkflowStep.attempt)))
    stats = {}
    for tool, ok, n in db.execute(select(ToolCallLog.tool, ToolCallLog.ok, func.count()).where(
            ToolCallLog.run_id == run.id).group_by(ToolCallLog.tool, ToolCallLog.ok)):
        stats.setdefault(tool, {"ok": 0, "failed": 0})["ok" if ok else "failed"] += n
    return run_out(run, steps, stats)


@router.post("/api/runs/{run_id}/cancel")
def cancel(run_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:decisions"))):
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise NotFound("Run")
    return run_out(service.cancel_run(db, principal, run))


@router.post("/api/runs/{run_id}/resume")
def resume(run_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:decisions"))):
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise NotFound("Run")
    return run_out(service.resume_run(db, principal, run))


@router.get("/api/agents/status")
def agents_status(probe: bool = False, _=Depends(perm("read:decisions"))):
    from app.modules.agents.llm import readiness

    s = get_settings()
    model = readiness(generate=probe, max_age=0 if probe else 60) if not s.is_demo else \
        {"ready": False, "model": s.model_name, "reason": "The demo shows pre-recorded runs only."}
    roles = [
        {"role": "Manager", "implementation": "CrewAI Flow (deterministic routing, budgets, assembly)",
         "model_mode": "Same Flow + optional advisory manager agent", "tools": [], "budget": "Run deadline 15 min "
         "(deterministic) / 45 min (model)"},
        {"role": "Research", "tools": sorted(ROLE_TOOLS["research"]), "budget": f"≤{ROLE_CALL_BUDGET['research']} tool calls"},
        {"role": "Portfolio & market analysis", "tools": sorted(ROLE_TOOLS["analysis"]),
         "budget": f"≤{ROLE_CALL_BUDGET['analysis']} tool calls"},
        {"role": "Scenario analysis", "tools": sorted(ROLE_TOOLS["scenario"]), "budget": f"≤{ROLE_CALL_BUDGET['scenario']} tool calls"},
        {"role": "Critic & quality review", "tools": sorted(ROLE_TOOLS["critic"]), "budget": f"≤{ROLE_CALL_BUDGET['critic']} tool calls"},
    ]
    return {"model": model, "modes": {"deterministic": True, "model": bool(model.get("ready"))}, "roles": roles,
            "step_timeout_seconds": s.model_step_timeout_seconds}
