"""Role executors for the no-model baseline: Simulated (fixture/template text) and Computed (deterministic
functions). All tool access goes through the MCP gateway with a per-step capability token."""

import re
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.modules.agents.contracts import (
    AnalysisOutput,
    Assumption,
    CriticOutput,
    Finding,
    InstrumentRef,
    ResearchOutput,
    RunPlan,
    ScenarioOutput,
    Source,
)
from app.modules.decisions.models import Decision
from app.modules.knowledge.checks import run_checks
from app.modules.knowledge.text import instruction_like, sentences
from app.modules.markets.models import Instrument
from app.modules.mcp_tools.gateway import ToolGateway
from app.modules.mcp_tools.tools import issue_capability
from app.modules.settings.service import get_setting

RISK_WORDS = re.compile(r"\b(risk|risks|decline|downside|headwind|uncertain|uncertainty|pressure|concern|volatil\w*|"
                        r"slowdown|competition|regulat\w*|weak\w*|overvalu\w*|drawdown)\b", re.I)
BUY = re.compile(r"\b(buy|add|increase|accumulate|initiate|open a position)\b", re.I)
SELL = re.compile(r"\b(sell|reduce|trim|exit|close the position|take profit)\b", re.I)


class ToolCallFailed(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class StepContext:
    db: Session
    run_id: uuid.UUID
    decision: Decision
    gateway: ToolGateway
    role: str
    outputs: dict = field(default_factory=dict)  # previous step outputs (dicts)
    notes: list[str] = field(default_factory=list)
    tool_calls: int = 0
    source_document_ids: set[str] = field(default_factory=set)
    cancel_check: object = None
    _cap: str | None = None

    def capability(self) -> str:
        if self._cap is None:
            self._cap = issue_capability(self.run_id, self.role)
        return self._cap

    def tool(self, name: str, **arguments) -> dict:
        self.tool_calls += 1
        res = self.gateway.call(name, self.capability(), arguments)
        if not res.get("ok"):
            err = res.get("error", {})
            raise ToolCallFailed(err.get("code", "tool_error"), err.get("message", "Tool call failed"))
        return res["result"]


class RoleExecutor(Protocol):
    kind: str

    def execute(self, ctx: StepContext): ...


# ---------- scope (manager flow logic) ----------

class ComputedScope:
    kind = "computed"

    def execute(self, ctx: StepContext) -> RunPlan:
        d = ctx.decision
        ids = [uuid.UUID(i) for i in d.instrument_ids or []]
        insts = list(ctx.db.scalars(select(Instrument).where(Instrument.id.in_(ids)))) if ids else []
        known = {i.symbol for i in insts}
        for inst in ctx.db.scalars(select(Instrument)):
            if inst.symbol not in known and re.search(rf"(?<![A-Za-z0-9]){re.escape(inst.symbol)}(?![A-Za-z0-9])",
                                                      d.question):
                insts.append(inst)
                known.add(inst.symbol)
        refs = [InstrumentRef(symbol=i.symbol, name=i.name, venue_mic=i.venue_mic, currency=i.currency, kind=i.kind,
                              tradable=i.tradable, not_tradable_reason=i.not_tradable_reason) for i in insts[:5]]
        side = "sell" if SELL.search(d.question) else "buy" if BUY.search(d.question) else None
        queries = [d.question[:300]]
        for r in refs[:2]:
            queries += [f"{r.symbol} {r.name}", f"{r.name} risks"]
        return RunPlan(question=d.question, instruments=refs, venues=sorted({r.venue_mic for r in refs}),
                       search_queries=queries[:6], side_hint=side,
                       notes=[f"Instruments identified: {', '.join(r.symbol for r in refs) or 'none'}"])


# ---------- research ----------

class ComputedResearch:
    """Sources are Computed (real retrieval and synthetic market data); the narrative summary is Simulated."""

    kind = "simulated"

    def execute(self, ctx: StepContext) -> ResearchOutput:
        plan = RunPlan.model_validate(ctx.outputs["scope"])
        now = utcnow().isoformat()
        sources: list[Source] = []
        seen_chunks: set[str] = set()
        queries = list(plan.search_queries)
        hint = ctx.outputs.get("research_hint")
        if hint:
            queries = [hint] + queries
        for q in queries[:6]:
            res = ctx.tool("rag_search", query=q, k=4)
            if res.get("abstain"):
                continue
            for h in res["hits"]:
                if h["chunk_id"] in seen_chunks:
                    continue
                seen_chunks.add(h["chunk_id"])
                ctx.source_document_ids.add(h["document_id"])
                sources.append(Source(
                    id=f"S{len(sources) + 1}", kind="passage", title=h["document_title"], location=h["location"],
                    retrieved_at=now, as_of=h.get("document_as_of") or now, freshness="library",
                    content={"quote": h["untrusted_text"][:1500], "coverage": h["coverage"],
                             "untrusted": True}, document_id=h["document_id"], chunk_id=h["chunk_id"]))
        symbols = [i.symbol for i in plan.instruments]
        stale = 0
        if symbols:
            for q in ctx.tool("market_get_quotes", symbols=symbols)["quotes"]:
                stale += q["freshness"] != "fresh"
                sources.append(Source(
                    id=f"S{len(sources) + 1}", kind="quote", title=f"{q['symbol']} quote ({q['label']})",
                    location=f"{q.get('venue_mic')} quote feed", retrieved_at=now, as_of=q["as_of"] or now,
                    freshness=q["freshness"], content={k: q.get(k) for k in ("symbol", "price", "change_pct",
                                                                               "currency", "label", "tradable")}))
        for mic in plan.venues[:3]:
            cal = ctx.tool("calendar_get_events", mic=mic, days=7)
            st = cal["state"]
            sources.append(Source(
                id=f"S{len(sources) + 1}", kind="calendar", title=f"{mic} session calendar", location=f"{mic} calendar",
                retrieved_at=now, as_of=now, freshness="computed",
                content={"state": st["state"], "reason": st["reason"], "next_event": st["next_event"],
                         "holidays": cal["holidays"]}))
        passages = [s for s in sources if s.kind == "passage"]
        docs = {s.document_id for s in passages}
        lead = ""
        if passages:
            from app.modules.knowledge.answers import _best_sentences
            from app.modules.knowledge.retrieval import Hit
            from app.modules.knowledge.text import key_terms

            top = passages[0]
            hit = Hit(top.chunk_id or "", top.document_id or "", top.title, top.content["quote"], None, None, 0, 0, None, 0)
            best = _best_sentences(hit, key_terms(plan.question), limit=1)
            lead = f" Most relevant passage ({top.title}, {top.location}): “{best[0][:300] if best else top.content['quote'][:160]}”"
        summary = (f"Simulated research summary (no language model): collected {len(passages)} library passage(s) "
                   f"from {len(docs)} document(s) and {len(sources) - len(passages)} market/calendar data point(s) "
                   f"for {', '.join(symbols) or 'the question'}.{lead}")
        missing = []
        if not passages:
            missing.append("No relevant passages in the Knowledge Library.")
        if stale:
            missing.append(f"{stale} quote(s) are stale.")
        failure = "no_sources" if not sources else ("stale_sources" if symbols and stale == len(symbols) else None)
        return ResearchOutput(sources=sources, summary=summary, summary_label="simulated", missing=missing,
                              failure=failure)


# ---------- portfolio & market analysis ----------

class ComputedAnalysis:
    kind = "computed"

    def execute(self, ctx: StepContext) -> AnalysisOutput:
        plan = RunPlan.model_validate(ctx.outputs["scope"])
        exp = ctx.tool("portfolio_get_exposure")
        pos = ctx.tool("portfolio_get_positions")
        symbols = {i.symbol for i in plan.instruments}
        weights = [{"symbol": p["symbol"], "weight_pct": p["weight_pct"], "value_home": p["value_home"],
                    "source": p.get("source")} for p in pos["positions"] if p["symbol"] in symbols]
        history = []
        for s in list(symbols)[:3]:
            try:
                history.append(ctx.tool("market_get_history", symbol=s, days=30))
            except ToolCallFailed:
                continue
        notes = []
        for s in sorted(symbols):
            w = next((x for x in weights if x["symbol"] == s), None)
            notes.append(f"{s} is {w['weight_pct']}% of the portfolio." if w else f"{s} is not currently held.")
        if exp["exposure"]["currency"]:
            top = exp["exposure"]["currency"][0]
            notes.append(f"Largest currency exposure: {top['key']} at {top['pct']}% of total value.")
        for h in history:
            if "change_pct" in h:
                notes.append(f"{h['symbol']}: {h['change_pct']}% over {h['days']} days (synthetic), daily volatility "
                             f"{h['daily_volatility_pct']}%.")
        return AnalysisOutput(total_home=exp["total_home"], home_currency=exp["home_currency"],
                              exposure=exp["exposure"], instrument_weights=weights, history=history, notes=notes,
                              notes_label="computed")


# ---------- scenarios ----------

class ComputedScenarios:
    kind = "computed"

    def execute(self, ctx: StepContext) -> ScenarioOutput:
        plan = RunPlan.model_validate(ctx.outputs["scope"])
        analysis = ctx.outputs["analysis"]
        symbols = [i.symbol for i in plan.instruments] or ["SPY"]
        proposed_value = round(analysis["total_home"] * 0.05, 2) if plan.side_hint else None
        table = ctx.tool("scenario_run", symbols=symbols, proposed_side=plan.side_hint,
                         proposed_value_home=proposed_value)
        sym = symbols[0]
        assumptions = [
            Assumption(code="A1", text=f"{sym} moves less than ±10% over the review horizon.", metric=f"{sym} price change",
                       expected="|Δ| ≤ 10%"),
            Assumption(code="A2", text=f"The home currency ({analysis['home_currency']}) moves less than 5% against USD.",
                       metric=f"USD/{analysis['home_currency']}", expected="|Δ| ≤ 5%"),
            Assumption(code="A3", text="The thesis in the cited sources remains valid (no contradicting news).",
                       metric="Thesis check at review", expected="Still valid"),
        ]
        severe = next((r for r in table["rows"] if r["shock_pct"] <= -20), table["rows"][0])
        commentary = (f"Computed: a {severe['shock_pct']}% move in {', '.join(symbols)} changes the portfolio by "
                      f"{severe['portfolio_change_home']:,.0f} {table['home_currency']} "
                      f"({severe['portfolio_change_pct']}%)."
                      + (f" Includes a simulated {plan.side_hint} of about {proposed_value:,.0f} "
                         f"{table['home_currency']}." if proposed_value else ""))
        return ScenarioOutput(table=table, assumptions=assumptions, commentary=commentary, commentary_label="computed")


# ---------- critic & quality review ----------

class ComputedCritic:
    kind = "computed"

    def execute(self, ctx: StepContext) -> CriticOutput:
        plan = RunPlan.model_validate(ctx.outputs["scope"])
        research = ResearchOutput.model_validate(ctx.outputs["research"])
        analysis = ctx.outputs["analysis"]
        scen = ctx.outputs["scenarios"]
        limits = get_setting(ctx.db, "limits")
        findings: list[Finding] = []
        counter: list[str] = []

        if not plan.instruments:
            findings.append(Finding(severity="blocking", title="No instrument identified", kind="missing_input",
                                    detail="Name at least one instrument (symbol) in the question or select one."))
        for inst in plan.instruments:
            if not inst.tradable:
                findings.append(Finding(severity="warning", title=f"{inst.symbol} is not tradable here",
                                        kind="tradability", detail=inst.not_tradable_reason or "Reference only."))
        passages = [s for s in research.sources if s.kind == "passage"]
        if not research.sources:
            findings.append(Finding(severity="blocking", title="No sources", kind="no_sources",
                                    detail="Research found no sources at all."))
        elif not passages:
            findings.append(Finding(severity="warning", title="No library evidence", kind="missing_evidence",
                                    detail="No relevant passages were found in your Knowledge Library."))
        for s in research.sources:
            if s.kind == "quote" and s.freshness != "fresh":
                findings.append(Finding(severity="warning", title=f"Stale quote: {s.title}", kind="stale_data",
                                        detail=f"Quote as of {s.as_of}. Refresh before acting."))
            if s.kind == "passage" and instruction_like(s.content.get("quote", "")):
                findings.append(Finding(severity="warning", title="Instruction-like text in a source", kind="injection",
                                        detail=f"{s.title} ({s.location}) contains text that looks like instructions. "
                                               "It was treated as data only and changed nothing."))
        for w in analysis.get("instrument_weights", []):
            if w["weight_pct"] > limits["max_position_pct"]:
                findings.append(Finding(severity="warning", title=f"Concentration: {w['symbol']}", kind="concentration",
                                        detail=f"{w['symbol']} is {w['weight_pct']}% of the portfolio, above your "
                                               f"{limits['max_position_pct']}% limit."))
                counter.append(f"{w['symbol']} already exceeds your position limit ({w['weight_pct']}% vs "
                               f"{limits['max_position_pct']}%); adding increases concentration risk.")
        for h in analysis.get("history", []):
            if h.get("daily_volatility_pct", 0) > 2.0:
                counter.append(f"{h['symbol']} daily volatility of {h['daily_volatility_pct']}% (synthetic) implies "
                               "wide short-term swings.")
        severe = min(scen["table"]["rows"], key=lambda r: r["portfolio_change_home"])
        counter.append(f"In the '{severe['name']}' scenario the portfolio changes by "
                       f"{severe['portfolio_change_pct']}% (Computed).")
        for p in passages:
            for sent in sentences(p.content.get("quote", "")):
                if RISK_WORDS.search(sent):
                    counter.append(f"{p.title} ({p.location}) notes: “{sent[:280]}”")
                    break
            if len(counter) >= 6:
                break
        statements = [{"text": p.content["quote"], "kind": "quote", "citations": [p.chunk_id]} for p in passages]
        retrieved = {p.chunk_id: {"text": p.content["quote"], "location": p.location} for p in passages}
        _, citation_checks = run_checks(statements, retrieved, set(retrieved), abstained=not passages)
        checks = ctx.tool("checks_run")["checks"]
        already_looped = bool(ctx.outputs.get("research_hint"))
        needs_more = (not passages) and not already_looped and bool(plan.instruments)
        hint = (" ".join(f"{i.symbol} {i.name}" for i in plan.instruments) + " outlook risks") if needs_more else None
        for m in research.missing:
            findings.append(Finding(severity="info", title="Open issue", kind="missing", detail=m))
        return CriticOutput(findings=findings, counterarguments=counter[:8], checks=checks,
                            citation_checks=citation_checks, needs_more_research=needs_more, research_hint=hint,
                            label="computed")


DETERMINISTIC = {"scope": ComputedScope, "research": ComputedResearch, "analysis": ComputedAnalysis,
                 "scenarios": ComputedScenarios, "critic": ComputedCritic}
