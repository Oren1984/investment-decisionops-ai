"""Document deletion: two explicit choices (owner decision D7).

Choice 1 'remove'  — remove from Library and retrieval; frozen quotations are kept and marked "Source removed".
Choice 2 'erase'   — fully erase content, including frozen quotations and derived copies; keep only a minimal
                     non-content audit record and an erasure-ledger entry that is re-applied after any restore.
"""

import json
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.authz import Principal
from app.core.clock import utcnow
from app.modules.audit.models import ErasureLedger
from app.modules.collaboration.models import Comment, Note, ShareGrant
from app.modules.decisions.evidence import redact_items
from app.modules.decisions.models import DecisionEvent, DecisionReview, EvidenceItem, EvidenceSnapshot, Lesson
from app.modules.knowledge.ingest import uploads_dir
from app.modules.knowledge.models import AnswerHistory, Chunk, Document
from app.modules.knowledge.text import normalize_ws, sentences
from app.modules.ops.models import ExportFile
from app.modules.workflows.models import WorkflowStep

ERASE_PHRASE = "ERASE"


def ledger_path():
    path = get_settings().data_dir / "ledger" / "erasure-ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _affected(db: Session, doc_id: uuid.UUID) -> dict:
    items = db.execute(select(EvidenceItem.id, EvidenceSnapshot.decision_id).join(
        EvidenceSnapshot, EvidenceSnapshot.id == EvidenceItem.snapshot_id).where(
        EvidenceItem.source_document_id == doc_id, EvidenceItem.redacted_at.is_(None))).all()
    steps = [s for s in db.scalars(select(WorkflowStep)) if str(doc_id) in (s.source_document_ids or [])
             and s.redacted_at is None]
    answers = [a for a in db.scalars(select(AnswerHistory)) if str(doc_id) in (a.document_ids or [])]
    exports = [e for e in db.scalars(select(ExportFile)) if str(doc_id) in (e.document_ids or [])]
    shares = db.scalars(select(ShareGrant).where(ShareGrant.object_type == "document", ShareGrant.object_id == doc_id,
                                                 ShareGrant.revoked_at.is_(None))).all()
    return {"items": items, "decision_ids": sorted({str(d) for _, d in items}), "steps": steps, "answers": answers,
            "exports": exports, "shares": shares}


def preview(db: Session, doc: Document) -> dict:
    a = _affected(db, doc.id)
    retention = get_settings().backup_retention_days
    return {
        "document_id": str(doc.id), "title": doc.title,
        "affected_decisions": len(a["decision_ids"]), "snapshot_items": len(a["items"]),
        "derived_records": len(a["steps"]) + len(a["answers"]), "active_shares": len(a["shares"]),
        "stored_exports": [{"id": str(e.id), "created_at": e.created_at} for e in a["exports"]],
        "backup_retention_days": retention,
        "backups_clear_after": (utcnow() + timedelta(days=retention)).date().isoformat(),
        "choices": {
            "remove": "Deletes the file, its passages and search index. Quotations already frozen in decision "
                      "evidence are kept and marked 'Source removed from Library'. Stored exports are kept.",
            "erase": "Deletes everything above AND erases quotations frozen in decision evidence, agent outputs, "
                     "answer history and review notes that contain this document's text. Affected decisions show "
                     "'Evidence incomplete'. Stored exports containing it are deleted.",
            "cannot_recall": "Exports you already downloaded and material collaborators already viewed cannot be "
                             "recalled.",
            "backups": f"Existing backups still contain the document until they rotate out (about {retention} days). "
                       "An erasure ledger is re-applied automatically after any restore, so erased content does "
                       "not come back.",
        },
    }


def _delete_file_and_index(db: Session, doc: Document) -> None:
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    try:
        (uploads_dir() / doc.storage_id).unlink(missing_ok=True)
    except OSError:
        pass


def _append_ledger(db: Session, kind: str, entry: dict) -> uuid.UUID:
    entry_id = uuid.uuid4()
    now = utcnow()
    db.add(ErasureLedger(id=entry_id, at=now, kind=kind, entry=entry))
    with ledger_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": str(entry_id), "at": now.isoformat(), "kind": kind, "entry": entry}) + "\n")
    return entry_id


def remove_from_library(db: Session, principal: Principal, doc: Document) -> dict:
    a = _affected(db, doc.id)
    now = utcnow()
    for item_id, _ in a["items"]:
        it = db.get(EvidenceItem, item_id)
        it.source_removed_at = now  # not part of the hash; allowed by the trigger
    for g in a["shares"]:
        g.revoked_at = now
    for ans in a["answers"]:
        db.delete(ans)  # live caches
    for did in a["decision_ids"]:
        db.add(DecisionEvent(decision_id=uuid.UUID(did), at=now, kind="source_removed",
                             summary="A source document was removed from the Library. Frozen quotations are kept.",
                             details={"document_id": str(doc.id)}))
    _delete_file_and_index(db, doc)
    counts = {"snapshot_items_marked": len(a["items"]), "decisions": len(a["decision_ids"]),
              "shares_removed": len(a["shares"])}
    _append_ledger(db, "document_remove", {"document_id": str(doc.id), "storage_id": doc.storage_id, **counts})
    db.delete(doc)
    audit.record(db, "library.document_removed", actor=principal, object_type="document", object_id=doc.id,
                 details=counts)
    return counts


def _doc_sentences(db: Session, doc_id: uuid.UUID) -> list[str]:
    out = []
    for c in db.scalars(select(Chunk).where(Chunk.document_id == doc_id)):
        out.extend(normalize_ws(s) for s in sentences(c.text) if len(s) >= 30)
    return out


def _contains_any(text: str | None, needles: list[str]) -> bool:
    if not text:
        return False
    hay = normalize_ws(text)
    return any(n in hay for n in needles)


def erase(db: Session, principal: Principal, doc: Document) -> dict:
    a = _affected(db, doc.id)
    now = utcnow()
    redaction_event_id = uuid.uuid4()
    needles = _doc_sentences(db, doc.id)
    item_ids = [i for i, _ in a["items"]]
    redacted = redact_items(db, item_ids, "document_erased", redaction_event_id)

    steps = 0
    for s in a["steps"]:
        s.output = {"redacted": True, "reason_code": "document_erased", "redaction_event_id": str(redaction_event_id)}
        s.redacted_at = now
        steps += 1
    derived = 0
    for ans in a["answers"]:
        db.delete(ans)
        derived += 1
    for review in db.scalars(select(DecisionReview).where(DecisionReview.redacted_at.is_(None))):
        if _contains_any(review.notes, needles):
            review.notes, review.redacted_at = "[Erased: contained text from an erased document]", now
            derived += 1
    for lesson in db.scalars(select(Lesson).where(Lesson.redacted_at.is_(None))):
        if _contains_any(lesson.text, needles):
            lesson.text, lesson.redacted_at = "[Erased: contained text from an erased document]", now
            derived += 1
    for note in db.scalars(select(Note).where(Note.redacted_at.is_(None))):
        if _contains_any(note.body, needles):
            note.body, note.redacted_at = "[Erased: contained text from an erased document]", now
            derived += 1
    for comment in db.scalars(select(Comment).where(Comment.redacted_at.is_(None))):
        if _contains_any(comment.body, needles):
            comment.body, comment.redacted_at = "[Erased: contained text from an erased document]", now
            derived += 1
    exports_deleted = 0
    for e in a["exports"]:
        try:
            Path(e.path).unlink(missing_ok=True)
        except OSError:
            pass
        db.delete(e)
        exports_deleted += 1
    for g in a["shares"]:
        g.revoked_at = now
    for did in a["decision_ids"]:
        db.add(DecisionEvent(decision_id=uuid.UUID(did), at=now, kind="redaction",
                             summary="Evidence incomplete: items were erased at the owner's request.",
                             details={"redaction_event_id": str(redaction_event_id)}))
    _delete_file_and_index(db, doc)
    counts = {"snapshot_items_redacted": redacted, "agent_outputs_redacted": steps, "derived_records": derived,
              "exports_deleted": exports_deleted, "decisions": len(a["decision_ids"]),
              "shares_removed": len(a["shares"])}
    _append_ledger(db, "document_erase", {
        "document_id": str(doc.id), "storage_id": doc.storage_id, "redaction_event_id": str(redaction_event_id),
        "evidence_item_ids": [str(i) for i in item_ids], "workflow_step_ids": [str(s.id) for s in a["steps"]],
        **counts})
    db.delete(doc)
    # Minimal non-content audit record: no title, filename, hash or content.
    audit.record(db, "library.document_erased", actor=principal, object_type="document", object_id=doc.id,
                 details=counts)
    return counts


def replay_ledger(db: Session, path=None) -> dict:
    """Re-apply erasures after a restore so that a backup cannot resurrect erased content."""
    path = path or ledger_path()
    applied = {"entries": 0, "documents_deleted": 0, "items_redacted": 0, "files_deleted": 0}
    if not path.exists():
        return applied
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        entry = rec["entry"]
        applied["entries"] += 1
        if rec["kind"] == "delete_all":
            continue  # handled by the delete-all routine on its own
        doc_id = uuid.UUID(entry["document_id"])
        doc = db.get(Document, doc_id)
        if doc is not None:
            db.execute(delete(Chunk).where(Chunk.document_id == doc_id))
            db.delete(doc)
            applied["documents_deleted"] += 1
        f = uploads_dir() / entry.get("storage_id", "__none__")
        if f.exists():
            f.unlink()
            applied["files_deleted"] += 1
        if rec["kind"] == "document_erase":
            ids = [uuid.UUID(i) for i in entry.get("evidence_item_ids", [])]
            applied["items_redacted"] += redact_items(db, ids, "document_erased",
                                                      uuid.UUID(entry["redaction_event_id"]))
            for sid in entry.get("workflow_step_ids", []):
                step = db.get(WorkflowStep, uuid.UUID(sid))
                if step is not None and step.redacted_at is None:
                    step.output = {"redacted": True, "reason_code": "document_erased"}
                    step.redacted_at = utcnow()
            db.execute(delete(AnswerHistory).where(AnswerHistory.document_ids.contains([str(doc_id)])))
        if db.get(ErasureLedger, uuid.UUID(rec["id"])) is None:
            db.add(ErasureLedger(id=uuid.UUID(rec["id"]), at=rec["at"], kind=rec["kind"], entry=entry))
    db.flush()
    return applied
