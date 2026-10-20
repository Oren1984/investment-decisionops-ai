"""Document deletion (plan §10.5, D7): 'remove' keeps frozen quotations marked as removed; 'erase' redacts frozen
evidence and derived copies, leaves no content in DB/files/FTS, keeps a non-content audit record, and is re-applied
by the erasure ledger after a restore. Each test uses its own uploaded document (the session DB is shared)."""

import json
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

from app.core.db import db_session
from tests.conftest import instrument_id, run_workflow_inline


def _doc_with_decision(owner):
    """A unique document cited by a frozen evidence package, an answer and a note."""
    from app.modules.knowledge.ingest import ingest_text

    word = "Zeph" + secrets.token_hex(3)
    sentence = f"Recurring revenue from {word} rises for Apple over the next three years."
    body = (f"# Apple {word} note\n\n## Contract\n\nThe {word} services contract was signed this quarter. "
            f"{sentence} Apple shares already price in most of it.\n")
    owner_id = uuid.UUID(owner.get("/api/auth/me").json()["id"])
    with db_session() as db:
        doc = ingest_text(db, owner_id, f"Apple {word} note", f"apple-{word}.md", body)
        doc_id, storage_id = doc.id, doc.storage_id
    r = owner.post("/api/decisions", {"title": f"AAPL {word}", "question": f"Should I buy AAPL given the {word} "
                                      "services contract?", "instrument_ids": [instrument_id(owner, "AAPL")],
                                      "start_run": True})
    d = r.json()
    assert run_workflow_inline(d["run_id"]) == "succeeded"
    ev = owner.get(f"/api/decisions/{d['id']}/evidence").json()
    cited = [i for i in ev["items"] if (i["provenance"] or {}).get("document_id") == str(doc_id)]
    assert cited, "the decision should cite the new document"
    assert owner.get("/api/library/ask", params={"q": f"{word} services contract"}).json()["mode"] == "extractive"
    assert owner.post("/api/notes", {"title": "Call notes", "body": f"Broker said: {sentence}"}).status_code == 200
    return {"word": word, "sentence": sentence, "needle": f"Recurring revenue from {word}", "doc_id": doc_id, "storage_id": storage_id, "decision_id": d["id"],
            "run_id": d["run_id"]}


def _content_hits(needle: str) -> dict[str, int]:
    queries = {
        "chunk": "SELECT count(*) FROM chunk WHERE text LIKE :n",
        "evidence_item": "SELECT count(*) FROM evidence_item WHERE content::text LIKE :n OR title LIKE :n",
        "workflow_step": "SELECT count(*) FROM workflow_step WHERE output::text LIKE :n",
        "answer_history": "SELECT count(*) FROM answer_history WHERE answer::text LIKE :n OR question LIKE :n",
        "note": "SELECT count(*) FROM note WHERE body LIKE :n",
        "audit": "SELECT count(*) FROM audit_event WHERE details::text LIKE :n",
    }
    with db_session() as db:
        return {k: db.execute(text(q), {"n": f"%{needle}%"}).scalar() for k, q in queries.items()}


def test_remove_keeps_frozen_quotes_marked(owner):
    s = _doc_with_decision(owner)
    preview = owner.get(f"/api/library/documents/{s['doc_id']}/deletion-preview").json()
    assert preview["affected_decisions"] >= 1 and preview["snapshot_items"] >= 1
    r = owner.post(f"/api/library/documents/{s['doc_id']}/delete", {"mode": "remove"})
    assert r.status_code == 200 and r.json()["snapshot_items_marked"] >= 1

    assert owner.get(f"/api/library/documents/{s['doc_id']}").status_code == 404
    assert owner.get("/api/library/ask", params={"q": f"{s['word']} services contract"}).json()["mode"] == "abstained"
    ev = owner.get(f"/api/decisions/{s['decision_id']}/evidence").json()
    cited = [i for i in ev["items"] if (i["provenance"] or {}).get("document_id") == str(s["doc_id"])]
    assert cited and all(i["source_removed_at"] and not i["redacted_at"] for i in cited)
    assert ev["verification"]["ok"] and ev["integrity_status"] == "verified"
    assert _content_hits(s["needle"])["evidence_item"] >= 1  # frozen quotation kept
    events = owner.get(f"/api/decisions/{s['decision_id']}").json()["events"]
    assert any(e["kind"] == "source_removed" for e in events)


def test_erase_requires_phrase_and_step_up(owner, anon):
    s = _doc_with_decision(owner)
    r = owner.post(f"/api/library/documents/{s['doc_id']}/delete", {"mode": "erase", "confirm_phrase": "ERASE"})
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"
    owner.step_up()
    r = owner.post(f"/api/library/documents/{s['doc_id']}/delete", {"mode": "erase", "confirm_phrase": "erase it"})
    assert r.status_code == 422 and r.json()["code"] == "confirmation_required"
    assert owner.get(f"/api/library/documents/{s['doc_id']}").status_code == 200


def test_erase_removes_content_everywhere_and_ledger_replays(owner):
    from app.config import get_settings
    from app.modules.knowledge.deletion import ledger_path, replay_ledger

    s = _doc_with_decision(owner)
    owner.step_up()
    r = owner.post(f"/api/library/documents/{s['doc_id']}/delete", {"mode": "erase", "confirm_phrase": "ERASE"})
    assert r.status_code == 200, r.text
    counts = r.json()
    assert counts["snapshot_items_redacted"] >= 1 and counts["agent_outputs_redacted"] >= 1
    assert counts["derived_records"] >= 2  # answer history + the note

    leaks = _content_hits(s["needle"])  # document-only text (the question is user input and stays)
    assert leaks == dict.fromkeys(leaks, 0), leaks
    upload = get_settings().data_dir / "uploads" / s["storage_id"]
    assert not upload.exists()
    ev = owner.get(f"/api/decisions/{s['decision_id']}/evidence").json()
    assert ev["integrity_status"] == "redacted" and ev["banner"].startswith("Evidence incomplete")
    assert ev["verification"]["ok"] and ev["verification"]["items_redacted"] >= 1  # remaining items verify
    events = owner.get(f"/api/decisions/{s['decision_id']}").json()["events"]
    assert any(e["kind"] == "redaction" for e in events)
    with db_session() as db:
        audit = db.execute(text("SELECT details::text FROM audit_event WHERE action = 'library.document_erased' "
                                "AND object_id = :d"), {"d": str(s["doc_id"])}).scalars().all()
    assert audit and all(s["word"] not in a and "apple-" not in a for a in audit)  # non-content record only
    assert str(s["doc_id"]) in ledger_path().read_text(encoding="utf-8")

    # Simulate a restore from a backup taken before the erasure: the document, its chunk and file come back.
    from app.modules.knowledge.ingest import uploads_dir
    from app.modules.knowledge.models import Chunk, Document

    with db_session() as db:
        db.add(Document(id=s["doc_id"], owner_id=None, title="restored", filename="restored.md", file_type="md",
                        size_bytes=10, storage_id=s["storage_id"], status="ready"))
        db.flush()
        db.add(Chunk(document_id=s["doc_id"], ordinal=0, text=s["sentence"], token_count=20))
    (uploads_dir() / s["storage_id"]).write_bytes(s["sentence"].encode())
    with db_session() as db:
        applied = replay_ledger(db)
    assert applied["documents_deleted"] >= 1 and applied["files_deleted"] >= 1
    assert _content_hits(s["needle"])["chunk"] == 0
    assert not (uploads_dir() / s["storage_id"]).exists()
    with db_session() as db:
        assert replay_ledger(db)["documents_deleted"] == 0  # idempotent

    # The restore scripts run the CLI in a fresh process (only the models it imports are mapped): restore again
    # and replay through the real command.
    with db_session() as db:
        db.add(Document(id=s["doc_id"], owner_id=None, title="restored", filename="restored.md", file_type="md",
                        size_bytes=10, storage_id=s["storage_id"], status="ready"))
    cli = subprocess.run([sys.executable, "-m", "app.cli", "replay-erasure-ledger"], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parents[2], timeout=120)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout.strip().splitlines()[-1])["documents_deleted"] >= 1
