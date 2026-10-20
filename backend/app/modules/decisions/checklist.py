"""Deterministic evidence checklist — replaces confidence percentages.

Passing checks means the PROCESS was complete, not that the idea is good. Each check's calculation is documented
here and in the Help article 'decision-checklist'.
"""

from datetime import datetime

FRESHNESS_LIMIT_HOURS = 72


def run_checklist(package: dict, now: datetime) -> list[dict]:
    sources = package.get("sources", [])
    passages = [s for s in sources if s.get("kind") == "passage"]
    scenarios = package.get("scenarios", {}).get("rows", [])
    findings = package.get("findings", [])
    citation_checks = package.get("citation_checks", [])

    def as_of(s):
        try:
            return datetime.fromisoformat(s["as_of"])
        except (KeyError, TypeError, ValueError):
            return None

    stale = [s for s in sources if as_of(s) and (now - as_of(s)).total_seconds() > FRESHNESS_LIMIT_HOURS * 3600
             and s.get("kind") != "passage"]
    blocking = [f for f in findings if f.get("severity") == "blocking"]

    checks = [
        ("scoped", "Question is scoped to identified instruments",
         bool(package.get("scope", {}).get("instruments")), "Instruments were identified for the question.",
         "Name at least one instrument."),
        ("sources", "At least two independent sources", len(sources) >= 2,
         f"{len(sources)} source(s) collected.", "Add documents to the Library or broaden the question."),
        ("provenance", "Every source has provenance and an as-of time",
         bool(sources) and all(s.get("as_of") and s.get("location") for s in sources),
         "All sources carry location and as-of time.", "Some sources lack an as-of time or location."),
        ("freshness", f"Market data is fresher than {FRESHNESS_LIMIT_HOURS} h", bool(sources) and not stale,
         "No stale market data.", f"{len(stale)} stale source(s)."),
        ("portfolio_context", "Portfolio context captured", bool(package.get("analysis", {}).get("exposure")),
         "Exposure and weights recorded.", "Portfolio context missing."),
        ("counterargument", "At least one counterargument recorded", bool(package.get("counterarguments")),
         "Counterarguments recorded.", "No counterargument recorded."),
        ("downside", "Scenarios include a downside case", any(r.get("shock_pct", 0) < 0 for r in scenarios),
         "A downside scenario was evaluated.", "No downside scenario."),
        ("assumptions", "Assumptions recorded with IDs for later review", bool(package.get("assumptions")),
         "Assumptions have IDs (A1, A2…).", "No assumptions recorded."),
        ("no_blocking_findings", "No blocking critic findings", not blocking,
         "The critic found no blocking issue.", f"{len(blocking)} blocking finding(s)."),
        ("citations", "Library citations pass the evidence checks (heuristic)",
         bool(passages) and all(c.get("passed") for c in citation_checks),
         "Citations valid and quotes exact; no obvious lexical mismatch.",
         "No library passages, or a citation check failed."),
    ]
    return [{"key": k, "name": name, "passed": bool(ok), "detail": good if ok else bad,
             "heuristic": k == "citations"} for k, name, ok, good, bad in checks]
