"""RAG evaluation on the synthetic corpus (plan §10.4): retrieval recall@5 / MRR against a recorded baseline,
abstention, citation validity and quote fidelity (100%), the unsupported-claim heuristic (reported honestly) and
access scope for collaborators (100%). Hybrid retrieval is measured only when embeddings are enabled.

Record a new baseline deliberately with RAG_EVAL_RECORD=1 (it rewrites baseline.json)."""

import json
import os
from pathlib import Path

import pytest

from tests.conftest import make_collaborator

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rag_eval"
QUESTIONS = json.loads((FIXTURES / "questions.json").read_text(encoding="utf-8"))["questions"]
UNSUPPORTED = json.loads((FIXTURES / "unsupported.json").read_text(encoding="utf-8"))["statements"]
BASELINE = FIXTURES / "baseline.json"
TOLERANCE = 0.02


def _seed_docs(owner) -> dict[str, str]:
    """filename → document id, for the seed corpus only."""
    names = {p.name for p in (Path(__file__).resolve().parents[3] / "seed" / "docs").glob("*")} or None
    docs = owner.get("/api/library/documents").json()
    return {d["filename"]: d["id"] for d in docs if names is None or d["filename"] in names}


def _relevant(hit: dict, labels: list, ids: dict[str, str]) -> bool:
    return any(hit["document_id"] == ids.get(fn) and phrase in hit["text"] for fn, phrase in labels)


@pytest.fixture(scope="module")
def results(owner_setup):
    from tests.conftest import OWNER_EMAIL, OWNER_PASSWORD, Api, _client

    owner = Api(_client())
    owner.post("/api/auth/login", {"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    ids = _seed_docs(owner)
    out = []
    for item in QUESTIONS:
        r = owner.get("/api/library/ask", params={"q": item["q"]})
        assert r.status_code == 200, r.text
        out.append((item, r.json()))
    return owner, ids, out


def _metrics(ids, out) -> dict:
    answerable = [(i, r) for i, r in out if i.get("answerable", True)]
    recall_hits, rr = 0, 0.0
    misses = []
    for item, res in answerable:
        hits = res["retrieval"]["hits"][:5]
        rank = next((n for n, h in enumerate(hits, start=1) if _relevant(h, item["relevant"], ids)), None)
        recall_hits += rank is not None
        rr += 1 / rank if rank else 0.0
        if rank is None:
            misses.append(item["q"])
    unanswerable = [(i, r) for i, r in out if not i.get("answerable", True)]
    return {
        "method": out[0][1]["retrieval"]["method"],
        "answerable": len(answerable), "unanswerable": len(unanswerable),
        "recall_at_5": round(recall_hits / len(answerable), 4), "mrr": round(rr / len(answerable), 4),
        "abstained_when_unanswerable": round(sum(r["mode"] == "abstained" for _, r in unanswerable) / len(unanswerable), 4),
        "answered_when_answerable": round(sum(r["mode"] != "abstained" for _, r in answerable) / len(answerable), 4),
        "retrieval_misses": misses,
    }


def test_retrieval_and_abstention_against_baseline(results, capsys):
    _, ids, out = results
    assert len(ids) == 6, "seed corpus should be indexed"
    m = _metrics(ids, out)
    with capsys.disabled():
        print("\nRAG eval:", json.dumps(m))
    if os.environ.get("RAG_EVAL_RECORD") == "1" or not BASELINE.exists():
        BASELINE.write_text(json.dumps({k: v for k, v in m.items() if k != "retrieval_misses"}, indent=2) + "\n",
                            encoding="utf-8")
        if os.environ.get("RAG_EVAL_RECORD") != "1":
            pytest.fail("No baseline existed; one was recorded. Review baseline.json and re-run.")
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    if base["method"] == m["method"]:
        for key in ("recall_at_5", "mrr", "abstained_when_unanswerable", "answered_when_answerable"):
            assert m[key] >= base[key] - TOLERANCE, f"{key} regressed: {m[key]} < baseline {base[key]}"


def test_citations_valid_and_quotes_exact(results):
    _, _, out = results
    for item, res in out:
        retrieved = {h["chunk_id"]: h for h in res["retrieval"]["hits"]}
        for st in res["statements"]:
            assert st["citations"], f"uncited statement for {item['q']!r}"
            for cid in st["citations"]:
                assert cid in retrieved and res["citations"][cid]["location"], item["q"]
            if st["kind"] == "quote":
                source = " ".join(" ".join(retrieved[c]["text"].split()) for c in st["citations"])
                assert " ".join(st["text"].split()) in source, item["q"]
        checks = {c["key"]: c["passed"] for c in res["checks"]}
        assert checks["citation_presence"] and checks["citation_validity"] and checks["quote_fidelity"], item["q"]


def test_unsupported_claim_heuristic_flag_rate(results, capsys):
    from app.modules.knowledge.checks import lexical_support

    owner, ids, _ = results
    texts: dict[tuple, str] = {}
    for fn, phrase in {tuple(s["cite"]) for s in UNSUPPORTED}:
        doc = owner.get(f"/api/library/documents/{ids[fn]}").json()
        texts[(fn, phrase)] = next(c["text"] for c in doc["chunks"] if phrase in c["text"])
    flagged_bad = sum(not lexical_support(s["text"], [texts[tuple(s["cite"])]])[0]
                      for s in UNSUPPORTED if s["unsupported"])
    flagged_good = sum(not lexical_support(s["text"], [texts[tuple(s["cite"])]])[0]
                       for s in UNSUPPORTED if not s["unsupported"])
    bad = sum(s["unsupported"] for s in UNSUPPORTED)
    good = len(UNSUPPORTED) - bad
    with capsys.disabled():
        print(f"\nUnsupported-claim heuristic: flagged {flagged_bad}/{bad} unsupported, "
              f"{flagged_good}/{good} supported (false positives)")
    # Heuristic, not a guarantee: supported statements must not be flagged; most unsupported ones should be.
    assert flagged_good == 0
    assert flagged_bad / bad >= 0.5


def test_collaborator_without_grants_retrieves_nothing(results, owner):
    _, ids, out = results
    collab, collab_id = make_collaborator(owner)
    assert collab.get("/api/library/ask", params={"q": "NVIDIA risks"}).status_code == 403
    for item, _ in out:
        r = collab.get("/api/shared/library/ask", params={"q": item["q"]})
        assert r.status_code == 200 and r.json()["retrieval"]["hits"] == [], item["q"]

    # With one document shared, only that document's passages are retrievable.
    r = owner.post("/api/shares", {"object_type": "document", "object_id": ids["portfolio-policy.md"],
                                   "grantee_id": collab_id})
    assert r.status_code == 200, r.text
    seen = set()
    for item, _ in out:
        for h in collab.get("/api/shared/library/ask", params={"q": item["q"]}).json()["retrieval"]["hits"]:
            seen.add(h["document_id"])
    assert seen == {ids["portfolio-policy.md"]}
