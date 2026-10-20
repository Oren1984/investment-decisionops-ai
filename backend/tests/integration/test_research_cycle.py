"""J3/J5: deterministic research cycle → evidence package → owner decision → replay unaffected by later data."""

from tests.conftest import instrument_id, run_workflow_inline


def _new_decision(owner, question, symbols, start_run=True):
    ids = [instrument_id(owner, s) for s in symbols]
    r = owner.post("/api/decisions", {"title": f"Test: {question[:40]}", "question": question,
                                      "instrument_ids": ids, "start_run": start_run})
    assert r.status_code == 200, r.text
    return r.json()


def test_deterministic_cycle_freezes_evidence_and_replays(owner):
    d = _new_decision(owner, "Should I add to NVDA after the latest data-center growth?", ["NVDA"])
    assert d["status"] == "draft" and d["run_id"]
    assert run_workflow_inline(d["run_id"]) == "succeeded"

    detail = owner.get(f"/api/decisions/{d['id']}").json()
    assert detail["status"] == "ready_for_decision"
    assert detail["snapshot"]["integrity_status"] == "verified"
    run = owner.get(f"/api/runs/{d['run_id']}").json()
    kinds = {s["step"]: s["output_kind"] for s in run["steps"]}
    assert kinds["research"] == "simulated" and kinds["analysis"] == "computed"
    assert all(s["status"] == "succeeded" for s in run["steps"])

    ev = owner.get(f"/api/decisions/{d['id']}/evidence").json()
    assert ev["verification"]["ok"] is True
    labels = {i["output_label"] for i in ev["items"]}
    assert {"computed", "simulated", "user"} <= labels
    passages = [i for i in ev["items"] if i["kind"] == "source_passage"]
    assert passages, "library passages should be cited"
    assert any(i["kind"] == "proposed_actions" for i in ev["items"])

    # Proposals are inert: an order intent exists but no order was created.
    assert any(p["kind"] == "order_intent" for p in detail["proposals"])
    assert owner.get("/api/orders").json() == [] or all(o["decision_id"] != d["id"] for o in owner.get("/api/orders").json())

    r = owner.post(f"/api/decisions/{d['id']}/decide", {"outcome": "accept", "rationale": "Thesis and sizing fit the policy."})
    assert r.status_code == 200, r.text
    replay1 = owner.get(f"/api/decisions/{d['id']}/replay").json()

    # Later market data must not change the historical record.
    from app.core.db import db_session
    from app.modules.markets.models import QuoteSnapshot

    with db_session() as db:
        for q in db.query(QuoteSnapshot).all():
            q.price = q.price * 2
    replay2 = owner.get(f"/api/decisions/{d['id']}/replay").json()
    assert replay1["items"] == replay2["items"]
    assert replay2["verification"]["ok"]


def test_correction_creates_new_version(owner):
    d = _new_decision(owner, "Should I trim AAPL to fund other positions?", ["AAPL"])
    run_workflow_inline(d["run_id"])
    owner.post(f"/api/decisions/{d['id']}/decide", {"outcome": "defer", "rationale": "Wait for the next quarter."})
    r = owner.post(f"/api/decisions/{d['id']}/corrections",
                   {"outcome": "reject", "rationale": "Keep the position.", "explanation": "Misread the policy limit."})
    assert r.status_code == 200 and r.json()["version_no"] == 2
    v1 = owner.get(f"/api/decisions/{d['id']}/replay?version=1").json()
    v2 = owner.get(f"/api/decisions/{d['id']}/replay?version=2").json()
    assert v1["version"]["outcome"] == "defer" and v2["version"]["outcome"] == "reject"
    assert v1["snapshot_id"] == v2["snapshot_id"]


def test_missing_instrument_blocks(owner):
    r = owner.post("/api/decisions", {"title": "Vague idea", "question": "Is it a good time to invest more money?",
                                      "instrument_ids": [], "start_run": True})
    d = r.json()
    assert run_workflow_inline(d["run_id"]) == "blocked"
    detail = owner.get(f"/api/decisions/{d['id']}").json()
    assert detail["status"] == "blocked" and "no instrument" in detail["blocked_reason"]


def test_review_separates_process_and_outcome(owner):
    d = _new_decision(owner, "Should I add to MSFT given cloud growth?", ["MSFT"])
    run_workflow_inline(d["run_id"])
    owner.post(f"/api/decisions/{d['id']}/decide", {"outcome": "accept", "rationale": "Cloud thesis intact."})
    rubric = {"evidence_quality": 2, "alternatives_considered": 2, "risk_sizing": 1, "followed_plan": 2,
              "timing_discipline": 2}
    r = owner.post(f"/api/decisions/{d['id']}/reviews", {
        "process_rubric": rubric, "outcome_return_pct": -4.0, "benchmark_return_pct": 1.0,
        "assumption_observations": [{"assumption_code": "A1", "observation": "Moved -4%", "held": True}],
        "lessons": [{"text": "Good process can still lose money.", "tags": ["process"]}], "close": True})
    assert r.status_code == 200, r.text
    assert r.json()["quadrant"] == {"process_good": True, "outcome_good": False}
    ins = owner.get("/api/decisions/insights").json()
    assert any(x["decision_id"] == d["id"] for x in ins["cells"]["good_process_bad_outcome"])
