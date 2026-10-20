"""Itemised evidence snapshots with salted item hashes, a snapshot hash, verification and honest redaction.

item_hash     = SHA-256(salt ‖ canonical(content, provenance))   (random per-item salt)
snapshot_hash = SHA-256(item_hash_1 ‖ item_hash_2 ‖ …)              (in ordinal order)

Redaction (full erasure) replaces content, provenance, title and salt with a tombstone and keeps item_hash, so the
remaining items still verify against snapshot_hash while the erased item can no longer be reconstructed.
"""

import hashlib
import secrets
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.security import canonical_json
from app.modules.decisions.models import EvidenceItem, EvidenceSnapshot


def item_hash(salt_hex: str, content, provenance) -> str:
    payload = canonical_json({"content": content, "provenance": provenance}).encode()
    return hashlib.sha256(bytes.fromhex(salt_hex) + payload).hexdigest()


def snapshot_hash(item_hashes: list[str]) -> str:
    return hashlib.sha256("".join(item_hashes).encode()).hexdigest()


def freeze(db: Session, decision_id: uuid.UUID, run_id: uuid.UUID | None, items: list[dict],
           checks_passed: int, checks_total: int) -> EvidenceSnapshot:
    """items: [{kind, title, content, provenance, output_label, source_document_id?}]"""
    snap = EvidenceSnapshot(decision_id=decision_id, run_id=run_id, frozen=False,
                            checks_passed=checks_passed, checks_total=checks_total)
    db.add(snap)
    db.flush()
    hashes = []
    for ordinal, it in enumerate(items):
        salt = secrets.token_hex(16)
        h = item_hash(salt, it["content"], it.get("provenance"))
        hashes.append(h)
        db.add(EvidenceItem(snapshot_id=snap.id, ordinal=ordinal, kind=it["kind"], title=it["title"][:240],
                            content=it["content"], provenance=it.get("provenance"),
                            output_label=it["output_label"], salt=salt, item_hash=h,
                            source_document_id=it.get("source_document_id")))
    db.flush()
    snap.snapshot_hash = snapshot_hash(hashes)
    snap.item_count = len(items)
    snap.frozen = True
    db.flush()
    return snap


def verify(db: Session, snap: EvidenceSnapshot) -> dict:
    items = db.scalars(select(EvidenceItem).where(EvidenceItem.snapshot_id == snap.id)
                       .order_by(EvidenceItem.ordinal)).all()
    verified = failed = redacted = 0
    for it in items:
        if it.redacted_at is not None or it.salt is None:
            redacted += 1
            continue
        if item_hash(it.salt, it.content, it.provenance) == it.item_hash:
            verified += 1
        else:
            failed += 1
    chain_ok = snapshot_hash([it.item_hash for it in items]) == snap.snapshot_hash
    return {"snapshot_hash_ok": chain_ok, "items_verified": verified, "items_failed": failed,
            "items_redacted": redacted, "integrity_status": snap.integrity_status,
            "ok": chain_ok and failed == 0}


def redact_items(db: Session, item_ids: list[uuid.UUID], reason: str, redaction_event_id: uuid.UUID) -> int:
    """The only path allowed to change frozen evidence content (the DB trigger checks the flag)."""
    if not item_ids:
        return 0
    db.execute(text("SET LOCAL app.allow_redaction = 'on'"))
    now = utcnow()
    count = 0
    snapshots: set[uuid.UUID] = set()
    for it in db.scalars(select(EvidenceItem).where(EvidenceItem.id.in_(item_ids))):
        if it.redacted_at is not None:
            continue
        tombstone = {"redacted": True, "redacted_at": now.isoformat(), "reason_code": reason,
                     "redaction_event_id": str(redaction_event_id)}
        it.content = tombstone
        it.provenance = {"redacted": True}
        it.title = "Erased evidence item"
        it.salt = None
        it.redacted_at = now
        it.redaction_reason = reason
        it.redaction_event_id = redaction_event_id
        snapshots.add(it.snapshot_id)
        count += 1
    db.flush()
    for sid in snapshots:
        snap = db.get(EvidenceSnapshot, sid)
        snap.integrity_status = "redacted"
    db.flush()
    db.execute(text("SET LOCAL app.allow_redaction = 'off'"))
    return count
