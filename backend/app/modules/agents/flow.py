"""The decision workflow: a CrewAI Flow holds orchestration authority in BOTH modes.

deterministic — simulated/computed RoleExecutors (always available, no model).
model         — the same Flow, with real CrewAI Agents per role plus an optional advisory manager agent.

Steps write only their own outputs keyed (run, step, attempt). A restart resumes from the last succeeded step, so
nothing is duplicated; agents have no consequential side effects anyway (proposals are inert records).
"""

import time
import uuid
from datetime import timedelta

from crewai.flow.flow import Flow, listen, or_, router, start
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.clock import utcnow
from app.core.db import db_session, notify
from app.core.logging import get_logger
from app.modules.agents.contracts import ROLE_SCHEMAS, CriticOutput, RunPlan
from app.modules.agents.executors import DETERMINISTIC, StepContext, ToolCallFailed
from app.modules.agents.model_executors import (
    MODEL,
    AdvisoryManager,
    CrewRunner,
    ModelOutputInvalid,
    StepCancelled,
    StepTimeout,
)
from app.modules.decisions.checklist import run_checklist
from app.modules.decisions.evidence import freeze
from app.modules.decisions.models import Assumption, Decision, DecisionEvent, ProposedAction
from app.modules.mcp_tools.gateway import ToolGateway
from app.modules.orders.models import StopState
from app.modules.workflows.models import WorkflowRun, WorkflowStep

log = get_logger("flow")

STEP_STATUS = {"scope": "scoped", "manager_advice": "scoped", "research": "researching", "analysis": "analyzing",
               "scenarios": "scenarios", "critic": "quality_review", "research_followup": "researching",
               "critic_followup": "quality_review"}
STEP_ROLE = {"scope": "manager", "manager_advice": "manager", "research": "research", "analysis": "analysis",
             "scenarios": "scenario", "critic": "critic", "research_followup": "research",
             "critic_followup": "critic"}
SCHEMA_FOR = {"research_followup": "research", "critic_followup": "critic"}


class RunAborted(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def publish(db: Session, kind: str, object_type: str, object_id) -> None:
    notify(db, "events", f"{kind}:{object_type}:{object_id}")


def latest_outputs(db: Session, run_id: uuid.UUID) -> dict:
    rows = db.scalars(select(WorkflowStep).where(WorkflowStep.run_id == run_id, WorkflowStep.status == "succeeded")
                      .order_by(WorkflowStep.attempt)).all()
    return {r.step: r.output for r in rows}


def assemble_package(db: Session, run: WorkflowRun) -> dict:
    out = latest_outputs(db, run.id)
    research = out.get("research_followup") or out.get("research") or {}
    critic = out.get("critic_followup") or out.get("critic") or {}
    scen = out.get("scenarios") or {}
    return {
        "scope": out.get("scope") or {}, "sources": research.get("sources", []),
        "research_summary": research.get("summary"), "research_summary_label": research.get("summary_label"),
        "analysis": out.get("analysis") or {}, "scenarios": scen.get("table", {}),
        "scenario_commentary": scen.get("commentary"), "scenario_commentary_label": scen.get("commentary_label"),
        "assumptions": scen.get("assumptions", []), "findings": critic.get("findings", []),
        "counterarguments": critic.get("counterarguments", []), "citation_checks": critic.get("citation_checks", []),
        "critic_label": critic.get("label"), "advice": out.get("manager_advice"),
    }


class FlowRunner:
    def __init__(self, run_id: uuid.UUID, gateway: ToolGateway, crew_runner: CrewRunner | None = None):
        self.run_id = run_id
        self.gateway = gateway
        self.crew_runner = crew_runner
        self.aborted: RunAborted | None = None
        self._last_cancel_check = 0.0
        self._cancel_cached = False
        with db_session() as db:
            run = db.get(WorkflowRun, run_id)
            self.mode = run.mode

    # ----- guards -----
    def _guard(self, db: Session, run: WorkflowRun) -> None:
        stop = db.get(StopState, 1)
        if stop is not None and stop.engaged:
            raise RunAborted("interrupted", "Stop is engaged: agent actions are blocked. Resume after releasing Stop.")
        if run.cancel_requested:
            raise RunAborted("cancelled", "Cancelled by the owner.")
        if run.deadline_at and utcnow() > run.deadline_at:
            raise RunAborted("failed", "The run deadline was exceeded.")

    def cancel_requested(self) -> bool:
        now = time.monotonic()
        if now - self._last_cancel_check < 1.0:
            return self._cancel_cached
        self._last_cancel_check = now
        with db_session() as db:
            run = db.get(WorkflowRun, self.run_id)
            stop = db.get(StopState, 1)
            self._cancel_cached = bool(run.cancel_requested or (stop is not None and stop.engaged))
        return self._cancel_cached

    # ----- steps -----
    def _executor(self, step: str):
        base = SCHEMA_FOR.get(step, step)
        if step == "manager_advice":
            return AdvisoryManager(self.crew_runner)
        if self.mode == "model" and base in MODEL:
            return MODEL[base](self.crew_runner)
        return DETERMINISTIC[base]()

    def run_step(self, step: str, extra_outputs: dict | None = None) -> dict | None:
        if self.aborted:
            return None
        try:
            return self._run_step(step, extra_outputs or {})
        except RunAborted as exc:
            self.aborted = exc
            return None

    def _run_step(self, step: str, extra: dict) -> dict:
        with db_session() as db:
            run = db.get(WorkflowRun, self.run_id)
            self._guard(db, run)
            done = db.scalar(select(WorkflowStep).where(WorkflowStep.run_id == run.id, WorkflowStep.step == step,
                                                        WorkflowStep.status == "succeeded"))
            if done is not None:
                return done.output  # resume: never re-execute a succeeded step
            attempt = (db.scalar(select(func.max(WorkflowStep.attempt)).where(
                WorkflowStep.run_id == run.id, WorkflowStep.step == step)) or 0) + 1
            row = WorkflowStep(run_id=run.id, step=step, attempt=attempt, status="running", started_at=utcnow())
            db.add(row)
            run.current_step = step
            decision = db.get(Decision, run.decision_id)
            decision.status = STEP_STATUS[step]
            publish(db, "run", "decision", decision.id)
            db.flush()
            step_id = row.id

        started = time.monotonic()
        executor = self._executor(step)
        with db_session() as db:
            run = db.get(WorkflowRun, self.run_id)
            decision = db.get(Decision, run.decision_id)
            ctx = StepContext(db=db, run_id=run.id, decision=decision, gateway=self.gateway, role=STEP_ROLE[step],
                              outputs={**latest_outputs(db, run.id), **extra}, cancel_check=self.cancel_requested)
            try:
                output = executor.execute(ctx)
                schema = ROLE_SCHEMAS[SCHEMA_FOR.get(step, step)]
                output = schema.model_validate(output.model_dump())  # contract enforced for every implementation
                status, error = "succeeded", None
            except StepCancelled:
                status, error = "cancelled", "Cancelled during the step"
            except (StepTimeout, TimeoutError) as exc:
                status, error = "failed", f"timeout: {exc}"
            except ToolCallFailed as exc:
                status = "cancelled" if exc.code == "run_not_active" else "failed"
                error = f"{exc.code}: {exc}"
            except ModelOutputInvalid as exc:
                status, error = "failed", f"invalid model output: {exc}"
            except Exception as exc:  # noqa: BLE001 - recorded as a defined failure state
                log.exception("step_failed", step=step, run_id=str(self.run_id))
                status, error = "failed", f"{exc.__class__.__name__}: {str(exc)[:300]}"
            notes = list(ctx.notes)
            tool_calls = ctx.tool_calls
            doc_ids = sorted(ctx.source_document_ids)

        with db_session() as db:
            row = db.get(WorkflowStep, step_id)
            row.status = status
            row.finished_at = utcnow()
            row.duration_ms = int((time.monotonic() - started) * 1000)
            row.tool_calls = tool_calls
            row.notes = notes
            row.error = error
            row.source_document_ids = doc_ids
            if status == "succeeded":
                row.output = output.model_dump(mode="json")
                row.output_kind = executor.kind if not notes or "fallback" not in " ".join(notes) else "computed"
                meta = getattr(executor, "meta", {}) or {}
                if executor.kind == "model":
                    run = db.get(WorkflowRun, self.run_id)
                    row.model_name, row.model_digest = run.model_name, run.model_digest
                    row.prompt_version, row.prompt_hash = meta.get("prompt_version"), meta.get("prompt_hash")
                    row.tokens_in, row.tokens_out = meta.get("tokens_in"), meta.get("tokens_out")
            run = db.get(WorkflowRun, self.run_id)
            publish(db, "run", "decision", run.decision_id)
            result = row.output
        if status == "cancelled":
            with db_session() as db:
                run = db.get(WorkflowRun, self.run_id)
                stop = db.get(StopState, 1)
                if stop is not None and stop.engaged and not run.cancel_requested:
                    raise RunAborted("interrupted", "Stop is engaged: the run was paused. Resume after releasing Stop.")
            raise RunAborted("cancelled", "Cancelled by the owner.")
        if status == "failed":
            hint = " Completed steps are preserved; resume to retry from this step." if "timeout" in (error or "") else ""
            raise RunAborted("failed", f"Step '{step}' failed ({error}).{hint}")
        return result

    # ----- flow-level operations -----
    def run_scope(self) -> None:
        plan = self.run_step("scope")
        if plan is None:
            return
        if not plan["instruments"]:
            self._block("blocked_missing_input: no instrument identified. Edit the question or select an instrument, "
                        "then restart the run.")
            return
        if self.mode == "model":
            advice = self._run_advisory_manager()
            if advice and advice.get("extra_queries"):
                self._extend_queries([q for q in advice["extra_queries"] if isinstance(q, str) and 3 <= len(q) <= 120])

    def _run_advisory_manager(self) -> dict | None:
        """The advisory manager is optional: its failure is ignored and the Flow continues (plan §9.2). A failed
        attempt is not retried on resume. Cancel and Stop still abort the run."""
        with db_session() as db:
            failed_before = db.scalar(select(WorkflowStep.id).where(
                WorkflowStep.run_id == self.run_id, WorkflowStep.step == "manager_advice",
                WorkflowStep.status == "failed").limit(1))
        if failed_before is not None:
            return None
        try:
            return self._run_step("manager_advice", {})
        except RunAborted as exc:
            if exc.status != "failed":
                self.aborted = exc
                return None
        with db_session() as db:
            row = db.scalar(select(WorkflowStep).where(WorkflowStep.run_id == self.run_id,
                                                       WorkflowStep.step == "manager_advice",
                                                       WorkflowStep.status == "failed")
                            .order_by(WorkflowStep.attempt.desc()).limit(1))
            row.notes = [*(row.notes or []), "Advisory step failed; ignored. The Flow continued with its own scope."]
            run = db.get(WorkflowRun, self.run_id)
            db.add(DecisionEvent(decision_id=run.decision_id, at=utcnow(), kind="advice_ignored",
                                 summary=f"The advisory manager failed ({row.error}); the run continued without it."))
        return None

    def _extend_queries(self, queries: list[str]) -> None:
        with db_session() as db:
            row = db.scalar(select(WorkflowStep).where(WorkflowStep.run_id == self.run_id, WorkflowStep.step == "scope",
                                                       WorkflowStep.status == "succeeded"))
            plan = RunPlan.model_validate(row.output)
            merged = (plan.search_queries + [q for q in queries if q not in plan.search_queries])[:6]
            plan.search_queries = merged
            plan.notes.append(f"Advisory manager suggested {len(queries)} extra quer(ies); validated and accepted by the Flow.")
            row.output = plan.model_dump(mode="json")

    def after_research(self) -> None:
        if self.aborted:
            return
        with db_session() as db:
            out = latest_outputs(db, self.run_id).get("research")
        if out and out.get("failure") == "no_sources":
            self._block("no_sources: research found no sources. Add documents to the Library or adjust the question.")

    def needs_more(self) -> bool:
        if self.aborted:
            return False
        with db_session() as db:
            critic = latest_outputs(db, self.run_id).get("critic")
            run = db.get(WorkflowRun, self.run_id)
            return bool(critic and critic.get("needs_more_research") and run.research_loops < 1)

    def run_follow_up(self) -> None:
        if self.aborted:
            return
        with db_session() as db:
            critic = CriticOutput.model_validate(latest_outputs(db, self.run_id)["critic"])
            run = db.get(WorkflowRun, self.run_id)
            run.research_loops += 1
            db.add(DecisionEvent(decision_id=run.decision_id, at=utcnow(), kind="critic_request",
                                 summary="The critic requested missing work; one follow-up research pass runs."))
        self.run_step("research_followup", {"research_hint": critic.research_hint})
        self.run_step("critic_followup", {"research_hint": critic.research_hint,
                                          "research": self._latest("research_followup")})

    def _latest(self, step: str) -> dict | None:
        with db_session() as db:
            return latest_outputs(db, self.run_id).get(step)

    def _block(self, reason: str) -> None:
        with db_session() as db:
            run = db.get(WorkflowRun, self.run_id)
            decision = db.get(Decision, run.decision_id)
            decision.status, decision.blocked_reason = "blocked", reason
            db.add(DecisionEvent(decision_id=decision.id, at=utcnow(), kind="blocked", summary=reason))
        self.aborted = RunAborted("blocked", reason)

    def assemble(self) -> None:
        if self.aborted:
            return
        with db_session() as db:
            run = db.get(WorkflowRun, self.run_id)
            self._guard(db, run)
            decision = db.get(Decision, run.decision_id)
            package = assemble_package(db, run)
            blocking = [f for f in package["findings"] if f["severity"] == "blocking"]
            if blocking:
                decision.status = "blocked"
                decision.blocked_reason = "; ".join(f"{f['title']}: {f['detail']}" for f in blocking)
                db.add(DecisionEvent(decision_id=decision.id, at=utcnow(), kind="blocked",
                                     summary=decision.blocked_reason))
                self.aborted = RunAborted("blocked", decision.blocked_reason)
                return
            checks = run_checklist(package, utcnow())
            proposals = self._proposals(package)
            items = build_items(decision, package, checks, proposals, run)
            snap = freeze(db, decision.id, run.id, items, sum(c["passed"] for c in checks), len(checks))
            for a in package["assumptions"]:
                existing = db.scalar(select(Assumption).where(Assumption.decision_id == decision.id,
                                                              Assumption.code == a["code"]))
                if existing is None:
                    db.add(Assumption(decision_id=decision.id, code=a["code"], text=a["text"], metric=a.get("metric"),
                                      expected=a.get("expected"), run_id=run.id))
            for p in proposals:
                db.add(ProposedAction(decision_id=decision.id, run_id=run.id, kind=p["kind"], payload=p["payload"],
                                      rationale=p["rationale"], output_label=p["label"]))
            decision.status = "ready_for_decision"
            decision.blocked_reason = None
            db.add(DecisionEvent(decision_id=decision.id, at=utcnow(), kind="snapshot_frozen",
                                 summary=f"Evidence package frozen: {snap.item_count} items, "
                                         f"{snap.checks_passed} of {snap.checks_total} checks passed.",
                                 details={"snapshot_id": str(snap.id), "snapshot_hash": snap.snapshot_hash}))
            run.current_step = "assemble"

    def _proposals(self, package: dict) -> list[dict]:
        plan = package["scope"]
        out = []
        syms = [i["symbol"] for i in plan.get("instruments", [])]
        if plan.get("side_hint") and syms:
            out.append({"kind": "order_intent", "label": "computed",
                        "payload": {"symbol": syms[0], "side": plan["side_hint"]},
                        "rationale": "The question suggests a trade. If you decide to act, create an order ticket "
                                     "yourself; it then needs preview, step-up approval and submission."})
        if any(f["severity"] == "warning" for f in package["findings"]):
            out.append({"kind": "follow_up_research", "label": "computed",
                        "payload": {"topics": [f["title"] for f in package["findings"] if f["severity"] == "warning"][:4]},
                        "rationale": "The critic raised warnings worth checking before deciding."})
        out.append({"kind": "reminder", "label": "computed", "payload": {"in_days": 30},
                    "rationale": "Review this decision against what happened in 30 days."})
        advice = package.get("advice") or {}
        for p in advice.get("proposed_actions", [])[:3]:
            if p.get("kind") in {"follow_up_research", "order_intent", "share", "reminder"}:
                out.append({"kind": p["kind"], "label": "model", "payload": p.get("payload") or {},
                            "rationale": str(p.get("rationale", ""))[:600]})
        return out

    # ----- entry point -----
    def execute(self) -> str:
        with db_session() as db:
            run = db.get(WorkflowRun, self.run_id)
            if run.status in ("succeeded", "cancelled"):
                return run.status
            run.status = "running"
            run.started_at = run.started_at or utcnow()
            run.error = None
            if run.deadline_at is None:
                run.deadline_at = utcnow() + timedelta(minutes=15 if run.mode == "deterministic" else 45)
            publish(db, "run", "decision", run.decision_id)
        flow = DecisionFlow(runner=self)
        try:
            flow.kickoff()
        except RunAborted as exc:
            self.aborted = exc
        except Exception as exc:  # noqa: BLE001
            log.exception("flow_failed", run_id=str(self.run_id))
            self.aborted = self.aborted or RunAborted("failed", f"{exc.__class__.__name__}: {str(exc)[:300]}")
        return self._finish()

    def _finish(self) -> str:
        with db_session() as db:
            run = db.get(WorkflowRun, self.run_id)
            decision = db.get(Decision, run.decision_id)
            if self.aborted is None:
                run.status, run.error = "succeeded", None
            else:
                run.status, run.error = self.aborted.status, str(self.aborted)
                if self.aborted.status == "cancelled" and decision.status not in ("blocked", "ready_for_decision"):
                    decision.status = "cancelled"
                    db.add(DecisionEvent(decision_id=decision.id, at=utcnow(), kind="cancelled",
                                         summary="Run cancelled by the owner. Completed steps are kept."))
                elif self.aborted.status in ("interrupted", "failed"):
                    db.add(DecisionEvent(decision_id=decision.id, at=utcnow(), kind=f"run_{self.aborted.status}",
                                         summary=str(self.aborted)))
            run.finished_at = utcnow() if run.status != "interrupted" else None
            run.current_step = None if run.status == "succeeded" else run.current_step
            audit.record(db, f"workflow.run_{run.status}", object_type="workflow_run", object_id=run.id,
                         details={"mode": run.mode})
            publish(db, "run", "decision", run.decision_id)
            return run.status


class DecisionFlowState(BaseModel):
    run_id: str = ""


class DecisionFlow(Flow[DecisionFlowState]):
    """Orchestration authority. Routing, progress, missing-work detection and package assembly live here."""

    def __init__(self, runner: FlowRunner, **kwargs):
        super().__init__(suppress_flow_events=True, **kwargs)
        object.__setattr__(self, "runner", runner)  # Flow is a Pydantic model; keep the runner out of its fields

    @start()
    def scope(self):
        self.runner.run_scope()

    @listen(scope)
    def research(self):
        self.runner.run_step("research")
        self.runner.after_research()

    @listen(research)
    def analysis(self):
        self.runner.run_step("analysis")

    @listen(analysis)
    def scenarios(self):
        self.runner.run_step("scenarios")

    @router(scenarios)
    def critic(self):
        self.runner.run_step("critic")
        return "needs_more" if self.runner.needs_more() else "complete"

    @listen("needs_more")
    def follow_up(self):
        self.runner.run_follow_up()

    @listen(or_("complete", follow_up))
    def assemble(self):
        self.runner.assemble()


def build_items(decision: Decision, package: dict, checks: list[dict], proposals: list[dict], run: WorkflowRun) -> list[dict]:
    model = {"model": run.model_name, "digest": run.model_digest} if run.mode == "model" else None
    items: list[dict] = [
        {"kind": "question", "title": "Question", "output_label": "user",
         "content": {"question": decision.question, "title": decision.title},
         "provenance": {"entered_by": "owner", "decision_id": str(decision.id)}},
        {"kind": "scope", "title": "Scope and run plan", "output_label": "computed",
         "content": package["scope"], "provenance": {"run_id": str(run.id), "step": "scope"}},
        {"kind": "portfolio_context", "title": "Portfolio context", "output_label": "computed",
         "content": {k: package["analysis"].get(k) for k in ("total_home", "home_currency", "exposure",
                                                             "instrument_weights")},
         "provenance": {"run_id": str(run.id), "step": "analysis", "label": "Synthetic" if decision.mode == "mock"
                        else "Broker data"}},
    ]
    for s in package["sources"]:
        items.append({"kind": "source_" + s["kind"], "title": f"[{s['id']}] {s['title']}", "output_label": s["label"],
                      "content": s["content"], "source_document_id": uuid.UUID(s["document_id"]) if s.get("document_id") else None,
                      "provenance": {"location": s["location"], "retrieved_at": s["retrieved_at"], "as_of": s["as_of"],
                                     "freshness": s["freshness"], "document_id": s.get("document_id"),
                                     "chunk_id": s.get("chunk_id")}})
    items += [
        {"kind": "research_summary", "title": "Research summary", "output_label": package["research_summary_label"] or "simulated",
         "content": {"text": package["research_summary"]}, "provenance": {"run_id": str(run.id), "model": model}},
        {"kind": "analysis_notes", "title": "Portfolio and market analysis", "output_label": package["analysis"].get("notes_label", "computed"),
         "content": {"notes": package["analysis"].get("notes", []), "history": package["analysis"].get("history", [])},
         "provenance": {"run_id": str(run.id), "model": model}},
        {"kind": "scenarios", "title": "Scenario results", "output_label": "computed", "content": package["scenarios"],
         "provenance": {"run_id": str(run.id), "engine": "deterministic scenario engine v1"}},
        {"kind": "scenario_commentary", "title": "Scenario commentary",
         "output_label": package["scenario_commentary_label"] or "computed",
         "content": {"text": package["scenario_commentary"]}, "provenance": {"run_id": str(run.id), "model": model}},
        {"kind": "assumptions", "title": "Assumptions", "output_label": "computed",
         "content": {"assumptions": package["assumptions"]}, "provenance": {"run_id": str(run.id)}},
        {"kind": "counterarguments", "title": "Counterarguments", "output_label": package["critic_label"] or "computed",
         "content": {"items": package["counterarguments"]}, "provenance": {"run_id": str(run.id), "model": model}},
        {"kind": "findings", "title": "Critic findings and unresolved issues", "output_label": package["critic_label"] or "computed",
         "content": {"findings": package["findings"]}, "provenance": {"run_id": str(run.id), "model": model}},
        {"kind": "checks", "title": "Evidence checklist", "output_label": "computed",
         "content": {"checks": checks, "citation_checks": package["citation_checks"],
                     "note": "Passing checks means the process was complete, not that the idea is good."},
         "provenance": {"run_id": str(run.id)}},
        {"kind": "proposed_actions", "title": "Suggestions (not executed)", "output_label": "computed",
         "content": {"proposals": proposals}, "provenance": {"run_id": str(run.id)}},
    ]
    return items
