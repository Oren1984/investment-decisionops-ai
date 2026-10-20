"""Model-mode Flow with a fake CrewAI runner (no model needed): advisory-manager failure is ignored (plan §9.2),
model notes are labelled, and invalid output falls back to computed with a visible note."""

import json
import uuid

from app.modules.agents.model_executors import FALLBACK_NOTE, StepTimeout
from tests.conftest import instrument_id

ANSWERS = {
    "research": {"summary": "Export controls are the main risk; the library covers them.", "relevant_source_ids": [],
                 "counterargument_hints": ["Valuation already prices in growth."]},
    "analysis": {"notes": ["NVDA is the largest single-name weight."]},
    "scenario": {"commentary": "The downside scenario dominates the risk budget.", "extra_assumptions": []},
    "critic": {"additional_findings": [], "counterarguments": ["Demand could normalise."]},
}


class FakeCrew:
    def __init__(self, manager_error: Exception | None = None, invalid: set[str] = frozenset()):
        self.manager_error = manager_error
        self.invalid = invalid
        self.calls: list[str] = []

    def run(self, ctx, prompt, description, tools, schema=None):
        role = ctx.role
        self.calls.append(role)
        if role == "manager":
            if self.manager_error:
                raise self.manager_error
            return json.dumps({"extra_queries": ["export controls data center"], "focus": "Export risk",
                               "proposed_actions": []}), {"tokens_in": 10, "tokens_out": 5}
        if role in self.invalid:
            return "not json at all", {}
        return json.dumps(ANSWERS[role]), {"tokens_in": 100, "tokens_out": 50}


def _model_run(owner, symbol="NVDA") -> str:
    r = owner.post("/api/decisions", {"title": "Model test", "question": f"Should I add to {symbol} given export risks?",
                                      "instrument_ids": [instrument_id(owner, symbol)], "start_run": True})
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    from app.core.db import db_session
    from app.modules.workflows.models import WorkflowRun

    with db_session() as db:  # the readiness gate is covered elsewhere; force model mode for the Flow
        run = db.get(WorkflowRun, uuid.UUID(run_id))
        run.mode, run.model_name, run.model_digest = "model", "fake-model", "sha256:fake"
    return run_id


def _execute(run_id: str, crew: FakeCrew) -> str:
    from app.modules.agents.flow import FlowRunner
    from app.modules.mcp_tools.gateway import LocalGateway

    return FlowRunner(uuid.UUID(run_id), LocalGateway(), crew_runner=crew).execute()


def test_advisory_manager_failure_is_ignored(owner):
    run_id = _model_run(owner)
    crew = FakeCrew(manager_error=StepTimeout("Model step exceeded 120s"))
    assert _execute(run_id, crew) == "succeeded"
    run = owner.get(f"/api/runs/{run_id}").json()
    steps = {s["step"]: s for s in run["steps"]}
    assert steps["manager_advice"]["status"] == "failed"
    assert any("ignored" in n for n in steps["manager_advice"]["notes"])
    assert steps["research"]["output_kind"] == "model" and steps["critic"]["output_kind"] == "model"
    detail = owner.get(f"/api/decisions/{run['decision_id']}").json()
    assert detail["status"] == "ready_for_decision"

    # Resume/re-execute does not retry the ignored advisory step.
    crew2 = FakeCrew()
    _execute(run_id, crew2)
    assert "manager" not in crew2.calls


def test_manager_advice_extends_queries_and_invalid_output_falls_back(owner):
    run_id = _model_run(owner)
    assert _execute(run_id, FakeCrew(invalid={"analysis"})) == "succeeded"
    run = owner.get(f"/api/runs/{run_id}").json()
    steps = {s["step"]: s for s in run["steps"]}
    assert steps["manager_advice"]["status"] == "succeeded"
    assert "export controls data center" in steps["scope"]["output"]["search_queries"]
    assert any("Advisory manager suggested" in n for n in steps["scope"]["output"]["notes"])
    assert steps["analysis"]["output_kind"] == "computed"
    assert FALLBACK_NOTE in steps["analysis"]["notes"]
