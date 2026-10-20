"""One input and one output schema per role. Simulated, computed and model implementations all satisfy the same
schemas; the Flow calls a RoleExecutor and does not know which implementation runs."""

from typing import Literal

from pydantic import BaseModel, Field

OutputLabel = Literal["simulated", "computed", "model", "user"]


class InstrumentRef(BaseModel):
    symbol: str
    name: str
    venue_mic: str
    currency: str
    kind: str
    tradable: bool
    not_tradable_reason: str | None = None


class RunPlan(BaseModel):
    question: str
    instruments: list[InstrumentRef]
    venues: list[str]
    search_queries: list[str] = Field(max_length=6)
    side_hint: Literal["buy", "sell"] | None = None
    notes: list[str] = []


class Source(BaseModel):
    id: str
    kind: Literal["passage", "quote", "calendar", "history"]
    title: str
    location: str
    retrieved_at: str
    as_of: str
    freshness: str
    content: dict
    document_id: str | None = None
    chunk_id: str | None = None
    label: OutputLabel = "computed"


class ResearchOutput(BaseModel):
    sources: list[Source]
    summary: str
    summary_label: OutputLabel
    missing: list[str] = []
    failure: Literal["no_sources", "stale_sources"] | None = None


class AnalysisOutput(BaseModel):
    total_home: float
    home_currency: str
    exposure: dict
    instrument_weights: list[dict]
    history: list[dict]
    notes: list[str]
    notes_label: OutputLabel


class Assumption(BaseModel):
    code: str
    text: str
    metric: str | None = None
    expected: str | None = None


class ScenarioOutput(BaseModel):
    table: dict
    assumptions: list[Assumption]
    commentary: str
    commentary_label: OutputLabel


class Finding(BaseModel):
    severity: Literal["info", "warning", "blocking"]
    title: str
    detail: str
    kind: str


class CriticOutput(BaseModel):
    findings: list[Finding]
    counterarguments: list[str]
    checks: list[dict]
    citation_checks: list[dict]
    needs_more_research: bool = False
    research_hint: str | None = None
    label: OutputLabel


class ProposedActionModel(BaseModel):
    kind: Literal["follow_up_research", "order_intent", "share", "reminder"]
    rationale: str = Field(max_length=600)
    payload: dict = {}


class ManagerAdvice(BaseModel):
    extra_queries: list[str] = Field(default=[], max_length=3)
    focus: str = Field(default="", max_length=400)
    proposed_actions: list[ProposedActionModel] = Field(default=[], max_length=5)


ROLE_SCHEMAS = {
    "scope": RunPlan, "research": ResearchOutput, "analysis": AnalysisOutput, "scenarios": ScenarioOutput,
    "critic": CriticOutput, "manager_advice": ManagerAdvice,
}
