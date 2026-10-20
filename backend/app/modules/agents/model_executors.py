"""Model-enabled role executors: real CrewAI Agents on the local Ollama model, using MCP-backed tools.

Numbers stay Computed: each model executor first runs the computed implementation, then a CrewAI Agent interprets
and selects. Output is schema-validated; on failure there is one retry, then a computed fallback with a visible
note. Cancellation is cooperative: the crew runs in a helper thread and the step stops waiting when cancel is
requested (its result is discarded)."""

import hashlib
import json
import threading
import time
import tomllib
from typing import Any

import json_repair
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import get_settings
from app.core.logging import get_logger
from app.modules.agents.contracts import (
    AnalysisOutput,
    Assumption,
    CriticOutput,
    Finding,
    ManagerAdvice,
    ResearchOutput,
    RunPlan,
    ScenarioOutput,
)
from app.modules.agents.executors import (
    ComputedAnalysis,
    ComputedCritic,
    ComputedResearch,
    ComputedScenarios,
    StepContext,
    ToolCallFailed,
)
from app.modules.mcp_tools.tools import TOOLS

log = get_logger("agents")


class StepCancelled(Exception):
    pass


class StepTimeout(Exception):
    pass


class ModelOutputInvalid(Exception):
    pass


def load_prompt(name: str) -> tuple[dict, str, str]:
    path = get_settings().prompts_dir / f"{name}.v1.toml"
    raw = path.read_bytes()
    return tomllib.loads(raw.decode()), path.stem, hashlib.sha256(raw).hexdigest()


# ---------- schemas for model notes ----------

class ResearchNotes(BaseModel):
    summary: str = Field(min_length=10, max_length=2500)
    relevant_source_ids: list[str] = []
    counterargument_hints: list[str] = Field(default=[], max_length=3)


class AnalysisNotes(BaseModel):
    notes: list[str] = Field(min_length=1, max_length=5)


class ExtraAssumption(BaseModel):
    text: str = Field(max_length=300)
    metric: str | None = Field(default=None, max_length=120)
    expected: str | None = Field(default=None, max_length=120)


class ScenarioNotes(BaseModel):
    commentary: str = Field(min_length=10, max_length=1500)
    extra_assumptions: list[ExtraAssumption] = Field(default=[], max_length=2)


class CriticFinding(BaseModel):
    severity: str = Field(pattern="^(info|warning)$")
    title: str = Field(max_length=160)
    detail: str = Field(max_length=600)


class CriticNotes(BaseModel):
    additional_findings: list[CriticFinding] = Field(default=[], max_length=4)
    counterarguments: list[str] = Field(default=[], max_length=4)


# ---------- CrewAI plumbing ----------

def _crew_tool(ctx: StepContext, name: str):
    from crewai.tools import BaseTool

    schema, _, description = TOOLS[name]

    class McpBackedTool(BaseTool):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        step_ctx: Any = None

        def _run(self, **kwargs) -> str:
            try:
                result = self.step_ctx.tool(self.name, **kwargs)
            except ToolCallFailed as exc:
                return json.dumps({"error": exc.code, "message": str(exc)})
            return json.dumps(result, default=str)[:6000]

    return McpBackedTool(name=name, description=description, args_schema=schema, step_ctx=ctx)


class CrewRunner:
    def __init__(self, timeout: int | None = None):
        s = get_settings()
        self.model = s.model_name
        self.base_url = s.ollama_base_url
        self.timeout = timeout or s.model_step_timeout_seconds
        self.max_tokens = s.model_max_tokens

    def _kickoff(self, prompt: dict, description: str, tools: list,
                 schema: type[BaseModel] | None = None) -> tuple[str, dict]:
        from crewai import LLM, Agent, Crew, Process, Task

        # Measured on this machine (CPU): qwen3:4b writes ~1,000+ tokens of reasoning into the answer even with
        # thinking disabled (~150 s per call); schema-constrained JSON answers in seconds and keeps the shape.
        llm = LLM(model=f"ollama_chat/{self.model}", base_url=self.base_url, temperature=0.2, timeout=self.timeout,
                  max_tokens=self.max_tokens, response_format=schema or {"type": "json_object"},
                  reasoning_effort="none" if self.model.startswith("qwen3") else None)
        agent = Agent(role=prompt["role"], goal=prompt["goal"], backstory=prompt["backstory"], tools=tools, llm=llm,
                      allow_delegation=False, max_iter=4, verbose=False, max_execution_time=self.timeout)
        task = Task(description=description, expected_output=prompt["expected_output"], agent=agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        out = crew.kickoff()
        usage = getattr(out, "token_usage", None)
        return out.raw, {"tokens_in": getattr(usage, "prompt_tokens", None),
                         "tokens_out": getattr(usage, "completion_tokens", None)}

    def run(self, ctx: StepContext, prompt: dict, description: str, tools: list,
            schema: type[BaseModel] | None = None) -> tuple[str, dict]:
        box: dict = {}

        def target():
            try:
                box["result"] = self._kickoff(prompt, description, tools, schema)
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc

        thread = threading.Thread(target=target, name=f"crew-{ctx.role}", daemon=True)
        thread.start()
        deadline = time.monotonic() + self.timeout
        while thread.is_alive():
            thread.join(0.5)
            if ctx.cancel_check and ctx.cancel_check():
                raise StepCancelled()
            if time.monotonic() > deadline:
                raise StepTimeout(f"Model step exceeded {self.timeout}s")
        if "error" in box:
            raise box["error"]
        return box["result"]


def _parse(raw: str, schema: type[BaseModel]) -> BaseModel:
    try:
        data = json_repair.loads(raw)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            data = data[0]
        return schema.model_validate(data)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ModelOutputInvalid(str(exc)[:300]) from exc


def call_model(ctx: StepContext, prompt_name: str, fields: dict, schema: type[BaseModel], tool_names: list[str],
               runner: CrewRunner | None = None) -> tuple[BaseModel, dict]:
    runner = runner or CrewRunner()
    prompt, version, phash = load_prompt(prompt_name)
    description = prompt["task"].format(**fields)
    tools = [_crew_tool(ctx, n) for n in tool_names]
    usage_total = {"tokens_in": 0, "tokens_out": 0}
    last_error = None
    for attempt in range(2):  # one retry on invalid output
        text = description if attempt == 0 else (
            description + f"\n\nYour previous answer was invalid ({last_error}). Return ONLY the JSON object.")
        raw, usage = runner.run(ctx, prompt, text, tools, schema)
        for k in usage_total:
            usage_total[k] += usage.get(k) or 0
        try:
            parsed = _parse(raw, schema)
            return parsed, {"prompt_version": version, "prompt_hash": phash, **usage_total}
        except ModelOutputInvalid as exc:
            last_error = str(exc)[:200]
    raise ModelOutputInvalid(last_error or "invalid output")


FALLBACK_NOTE = "Model output invalid – computed fallback used"


class _ModelBase:
    kind = "model"

    def __init__(self, runner: CrewRunner | None = None):
        self.runner = runner
        self.meta: dict = {}

    def _model(self, ctx, prompt_name, fields, schema, tools):
        try:
            parsed, meta = call_model(ctx, prompt_name, fields, schema, tools, self.runner)
            self.meta = meta
            return parsed
        except ModelOutputInvalid:
            prompt, version, phash = load_prompt(prompt_name)
            self.meta = {"prompt_version": version, "prompt_hash": phash}
            ctx.notes.append(FALLBACK_NOTE)
            return None


class ModelResearch(_ModelBase):
    def execute(self, ctx: StepContext) -> ResearchOutput:
        base = ComputedResearch().execute(ctx)
        listing = "\n".join(f"[{s.id}] {s.kind} — {s.title} ({s.location}), as of {s.as_of}: "
                            f"{json.dumps(s.content, default=str)[:600]}" for s in base.sources)
        notes = self._model(ctx, "research", {"question": ctx.decision.question, "sources": listing}, ResearchNotes,
                            ["rag_search", "market_get_quotes", "instrument_lookup"])
        if notes is None:
            return base
        valid_ids = {s.id for s in base.sources}
        chosen = [i for i in notes.relevant_source_ids if i in valid_ids]
        if notes.relevant_source_ids and len(chosen) < len(notes.relevant_source_ids):
            ctx.notes.append("Model referenced unknown source IDs; they were ignored.")
        ctx.outputs["model_counter_hints"] = notes.counterargument_hints
        base.summary, base.summary_label = notes.summary, "model"
        if chosen:
            for s in base.sources:
                s.content = {**s.content, "selected_by_model": s.id in chosen}
        return base


class ModelAnalysis(_ModelBase):
    def execute(self, ctx: StepContext) -> AnalysisOutput:
        base = ComputedAnalysis().execute(ctx)
        facts = json.dumps({"total_home": base.total_home, "home_currency": base.home_currency,
                            "instrument_weights": base.instrument_weights, "history": base.history,
                            "exposure": base.exposure}, default=str)[:4000]
        notes = self._model(ctx, "analysis", {"question": ctx.decision.question, "facts": facts}, AnalysisNotes,
                            ["portfolio_get_exposure"])
        if notes is None:
            return base
        base.notes = base.notes + [f"Interpretation: {n}" for n in notes.notes]
        base.notes_label = "model"
        return base


class ModelScenarios(_ModelBase):
    def execute(self, ctx: StepContext) -> ScenarioOutput:
        base = ComputedScenarios().execute(ctx)
        notes = self._model(ctx, "scenarios", {"question": ctx.decision.question,
                                               "table": json.dumps(base.table["rows"])}, ScenarioNotes, [])
        if notes is None:
            return base
        base.commentary, base.commentary_label = notes.commentary, "model"
        for i, extra in enumerate(notes.extra_assumptions, start=len(base.assumptions) + 1):
            base.assumptions.append(Assumption(code=f"A{i}", text=extra.text, metric=extra.metric,
                                               expected=extra.expected))
        return base


class ModelCritic(_ModelBase):
    def execute(self, ctx: StepContext) -> CriticOutput:
        base = ComputedCritic().execute(ctx)
        package = json.dumps({"research_summary": ctx.outputs["research"]["summary"],
                              "findings": [f.model_dump() for f in base.findings],
                              "counterarguments": base.counterarguments,
                              "hints": ctx.outputs.get("model_counter_hints", [])}, default=str)[:4000]
        notes = self._model(ctx, "critic", {"question": ctx.decision.question, "package": package}, CriticNotes,
                            ["rag_search"])
        if notes is None:
            return base
        for f in notes.additional_findings:
            base.findings.append(Finding(severity=f.severity, title=f.title, detail=f.detail, kind="model_review"))
        base.counterarguments = base.counterarguments + [f"(Model) {c}" for c in notes.counterarguments]
        base.label = "model"
        return base


class AdvisoryManager(_ModelBase):
    """Optional advisory manager agent. Its proposals are validated against allowed task types; the Flow decides."""

    def __init__(self, runner: CrewRunner | None = None):
        super().__init__(runner or CrewRunner(timeout=get_settings().model_manager_timeout_seconds))

    def execute(self, ctx: StepContext) -> ManagerAdvice:
        plan = RunPlan.model_validate(ctx.outputs["scope"])
        advice = self._model(ctx, "manager", {"question": ctx.decision.question,
                                              "instruments": ", ".join(i.symbol for i in plan.instruments) or "none"},
                             ManagerAdvice, [])
        return advice or ManagerAdvice()


MODEL = {"research": ModelResearch, "analysis": ModelAnalysis, "scenarios": ModelScenarios, "critic": ModelCritic}
