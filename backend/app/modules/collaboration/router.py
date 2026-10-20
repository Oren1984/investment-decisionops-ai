"""Owner-controlled collaboration. Collaborators see only explicitly shared objects; every path (API, RAG, SSE,
downloads) uses the same `can_access_object` check. Revocation is immediate."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from app.core import audit
from app.core.authz import Principal, can_access_object, granted_object_ids, perm
from app.core.clock import utcnow
from app.core.db import get_db, notify
from app.core.errors import AppError, Forbidden, NotFound
from app.modules.collaboration.models import SHAREABLE_TYPES, ActionItem, Comment, Note, ShareGrant
from app.modules.decisions.models import Decision, DecisionVersion, EvidenceSnapshot
from app.modules.decisions.service import latest_snapshot, snapshot_view
from app.modules.identity.models import User
from app.modules.identity.service import end_all_sessions
from app.modules.knowledge.models import Chunk, Document
from app.modules.meetings.models import Meeting

router = APIRouter(prefix="/api", tags=["collaboration"])

OBJECT_MODELS = {"decision": Decision, "document": Document, "note": Note, "meeting": Meeting}


def _title(obj) -> str:
    return getattr(obj, "title", None) or "Untitled"


# ---------- people ----------

@router.get("/people")
def people(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:collaboration"))):
    out = []
    for u in db.scalars(select(User).where(User.role == "collaborator").order_by(User.created_at)):
        grants = db.scalars(select(ShareGrant).where(ShareGrant.grantee_id == u.id, ShareGrant.revoked_at.is_(None)))
        out.append({"id": str(u.id), "email": u.email, "display_name": u.display_name, "timezone": u.timezone,
                    "active": u.disabled_at is None, "created_at": u.created_at, "active_shares": len(list(grants))})
    return out


@router.post("/people/{user_id}/revoke")
def revoke_person(user_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:collaboration"))):
    u = db.get(User, user_id)
    if u is None or u.role != "collaborator":
        raise NotFound("Collaborator")
    u.disabled_at = utcnow()
    ended = end_all_sessions(db, u.id)
    now = utcnow()
    count = 0
    for g in db.scalars(select(ShareGrant).where(ShareGrant.grantee_id == u.id, ShareGrant.revoked_at.is_(None))):
        g.revoked_at = now
        count += 1
    audit.record(db, "collab.collaborator_revoked", actor=principal, object_type="user", object_id=u.id,
                 details={"sessions_ended": ended, "grants_revoked": count})
    notify(db, "events", f"share:user:{u.id}")
    return {"ok": True, "sessions_ended": ended, "grants_revoked": count}


# ---------- shares ----------

class ShareIn(BaseModel):
    object_type: Literal["decision", "document", "note", "meeting"]
    object_id: uuid.UUID
    grantee_id: uuid.UUID
    permission: Literal["view", "comment"] = "view"
    expires_at: datetime | None = None
    include_portfolio_context: bool = False


def share_out(db: DB, g: ShareGrant) -> dict:
    obj = db.get(OBJECT_MODELS[g.object_type], g.object_id)
    grantee = db.get(User, g.grantee_id)
    state = "revoked" if g.revoked_at else "expired" if g.expires_at and g.expires_at <= utcnow() else "active"
    return {"id": str(g.id), "object_type": g.object_type, "object_id": str(g.object_id),
            "object_title": _title(obj) if obj else "(deleted)", "grantee_id": str(g.grantee_id),
            "grantee_name": grantee.display_name if grantee else "?", "permission": g.permission,
            "include_portfolio_context": g.include_portfolio_context, "created_at": g.created_at,
            "expires_at": g.expires_at, "revoked_at": g.revoked_at, "state": state}


@router.get("/shares")
def list_shares(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:collaboration"))):
    return [share_out(db, g) for g in db.scalars(select(ShareGrant).order_by(ShareGrant.created_at.desc()))]


@router.post("/shares")
def create_share(body: ShareIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:collaboration"))):
    obj = db.get(OBJECT_MODELS[body.object_type], body.object_id)
    if obj is None:
        raise NotFound(body.object_type.capitalize())
    grantee = db.get(User, body.grantee_id)
    if grantee is None or grantee.role != "collaborator" or grantee.disabled_at:
        raise AppError("invalid_grantee", "Share only with an active collaborator.", status_code=422)
    g = ShareGrant(object_type=body.object_type, object_id=body.object_id, grantee_id=body.grantee_id,
                   permission=body.permission, expires_at=body.expires_at,
                   include_portfolio_context=body.include_portfolio_context and body.object_type == "decision",
                   created_by=principal.user_id)
    db.add(g)
    db.flush()
    audit.record(db, "collab.shared", actor=principal, object_type=body.object_type, object_id=body.object_id,
                 details={"grant_id": str(g.id), "permission": g.permission,
                          "portfolio_context": g.include_portfolio_context})
    return share_out(db, g)


@router.delete("/shares/{share_id}")
def revoke_share(share_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:collaboration"))):
    g = db.get(ShareGrant, share_id)
    if g is None:
        raise NotFound("Share")
    g.revoked_at = g.revoked_at or utcnow()
    audit.record(db, "collab.share_revoked", actor=principal, object_type=g.object_type, object_id=g.object_id,
                 details={"grant_id": str(g.id)})
    notify(db, "events", f"share:{g.object_type}:{g.object_id}")
    return share_out(db, g)


# ---------- notes ----------

class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=20000)
    decision_id: uuid.UUID | None = None
    meeting_id: uuid.UUID | None = None


def note_out(n: Note) -> dict:
    return {"id": str(n.id), "title": n.title, "body": n.body, "decision_id": str(n.decision_id) if n.decision_id else None,
            "meeting_id": str(n.meeting_id) if n.meeting_id else None, "created_at": n.created_at,
            "updated_at": n.updated_at, "redacted": n.redacted_at is not None}


@router.get("/notes")
def list_notes(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:collaboration"))):
    return [note_out(n) for n in db.scalars(select(Note).order_by(Note.updated_at.desc()))]


@router.post("/notes")
def create_note(body: NoteIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:collaboration"))):
    n = Note(owner_id=principal.user_id, **body.model_dump())
    db.add(n)
    db.flush()
    return note_out(n)


@router.put("/notes/{note_id}")
def update_note(note_id: uuid.UUID, body: NoteIn, db: DB = Depends(get_db, scope="function"), _=Depends(perm("write:collaboration"))):
    n = db.get(Note, note_id)
    if n is None:
        raise NotFound("Note")
    for k, v in body.model_dump().items():
        setattr(n, k, v)
    return note_out(n)


@router.delete("/notes/{note_id}")
def delete_note(note_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), _=Depends(perm("write:collaboration"))):
    n = db.get(Note, note_id)
    if n is None:
        raise NotFound("Note")
    db.delete(n)
    return {"ok": True}


# ---------- action items ----------

class ActionIn(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    meeting_id: uuid.UUID | None = None
    decision_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    due_at: datetime | None = None


class ActionStatusIn(BaseModel):
    status: Literal["open", "done"]


def action_out(db: DB, a: ActionItem) -> dict:
    assignee = db.get(User, a.assignee_id) if a.assignee_id else None
    return {"id": str(a.id), "title": a.title, "status": a.status, "due_at": a.due_at,
            "meeting_id": str(a.meeting_id) if a.meeting_id else None,
            "decision_id": str(a.decision_id) if a.decision_id else None,
            "assignee_id": str(a.assignee_id) if a.assignee_id else None,
            "assignee": assignee.display_name if assignee else None, "created_at": a.created_at}


def _can_touch_action(db: DB, principal: Principal, a: ActionItem, need: str) -> bool:
    if principal.sees_owner_data:
        return need == "view" or principal.is_owner
    if a.assignee_id == principal.user_id:
        return True
    return bool(a.meeting_id and can_access_object(db, principal, "meeting", a.meeting_id, need))


@router.get("/action-items")
def list_actions(db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("read:meetings"))):
    rows = db.scalars(select(ActionItem).order_by(ActionItem.created_at.desc()))
    return [action_out(db, a) for a in rows if _can_touch_action(db, principal, a, "view")]


@router.post("/action-items")
def create_action(body: ActionIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:collaboration"))):
    a = ActionItem(owner_id=principal.user_id, created_by=principal.user_id, **body.model_dump())
    db.add(a)
    db.flush()
    return action_out(db, a)


@router.patch("/action-items/{item_id}")
def update_action(item_id: uuid.UUID, body: ActionStatusIn, db: DB = Depends(get_db, scope="function"),
                  principal: Principal = Depends(perm("write:action_item"))):
    a = db.get(ActionItem, item_id)
    if a is None:
        raise NotFound("Action item")
    if not _can_touch_action(db, principal, a, "comment"):
        raise Forbidden()
    a.status = body.status
    audit.record(db, "collab.action_item_updated", actor=principal, object_type="action_item", object_id=a.id,
                 details={"status": body.status})
    return action_out(db, a)


# ---------- comments ----------

class CommentIn(BaseModel):
    object_type: Literal["decision", "document", "note", "meeting"]
    object_id: uuid.UUID
    body: str = Field(min_length=1, max_length=4000)


@router.get("/comments")
def list_comments(object_type: str, object_id: uuid.UUID, db: DB = Depends(get_db, scope="function"),
                  principal: Principal = Depends(perm("read:shared"))):
    if object_type not in SHAREABLE_TYPES or not can_access_object(db, principal, object_type, object_id):
        raise Forbidden()
    users = {u.id: u.display_name for u in db.scalars(select(User))}
    return [{"id": str(c.id), "author": users.get(c.author_id, "Former collaborator"), "body": c.body,
             "created_at": c.created_at, "redacted": c.redacted_at is not None}
            for c in db.scalars(select(Comment).where(Comment.object_type == object_type, Comment.object_id == object_id)
                                .order_by(Comment.created_at))]


@router.post("/comments")
def add_comment(body: CommentIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:comment"))):
    if not can_access_object(db, principal, body.object_type, body.object_id, need="comment"):
        raise Forbidden("You can view this item but not comment on it.")
    c = Comment(object_type=body.object_type, object_id=body.object_id, author_id=principal.user_id, body=body.body)
    db.add(c)
    db.flush()
    audit.record(db, "collab.comment_added", actor=principal, object_type=body.object_type, object_id=body.object_id)
    notify(db, "events", f"comment:{body.object_type}:{body.object_id}")
    return {"id": str(c.id)}


# ---------- collaborator's shared space ----------

@router.get("/shared")
def shared_with_me(db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("read:shared"))):
    out = []
    for object_type in SHAREABLE_TYPES:
        ids = granted_object_ids(db, principal, object_type) if not principal.sees_owner_data else []
        for oid in ids:
            obj = db.get(OBJECT_MODELS[object_type], oid)
            if obj is None:
                continue
            perm_ = "comment" if can_access_object(db, principal, object_type, oid, "comment") else "view"
            out.append({"object_type": object_type, "object_id": str(oid), "title": _title(obj), "permission": perm_})
    return out


def _require(db: DB, principal: Principal, object_type: str, object_id: uuid.UUID) -> None:
    if not can_access_object(db, principal, object_type, object_id):
        raise Forbidden()


@router.get("/shared/decisions/{decision_id}")
def shared_decision(decision_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("read:shared"))):
    _require(db, principal, "decision", decision_id)
    d = db.get(Decision, decision_id)
    if d is None:
        raise NotFound("Decision")
    include_portfolio = principal.sees_owner_data or any(
        g.include_portfolio_context for g in db.scalars(select(ShareGrant).where(
            ShareGrant.grantee_id == principal.user_id, ShareGrant.object_type == "decision",
            ShareGrant.object_id == decision_id, ShareGrant.revoked_at.is_(None))))
    version = db.scalar(select(DecisionVersion).where(DecisionVersion.decision_id == d.id)
                        .order_by(DecisionVersion.version_no.desc()))
    snap = db.get(EvidenceSnapshot, version.snapshot_id) if version and version.snapshot_id else latest_snapshot(db, d.id)
    return {"decision": {"id": str(d.id), "title": d.title, "question": d.question, "status": d.status,
                         "outcome": d.outcome},
            "version": {"version_no": version.version_no, "outcome": version.outcome, "rationale": version.rationale}
            if version else None,
            "evidence": snapshot_view(db, snap, share_mode=True, include_portfolio=include_portfolio) if snap else None,
            "can_comment": can_access_object(db, principal, "decision", decision_id, "comment")}


@router.get("/shared/documents/{document_id}")
def shared_document(document_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("read:shared"))):
    _require(db, principal, "document", document_id)
    d = db.get(Document, document_id)
    if d is None:
        raise NotFound("Document")
    chunks = db.scalars(select(Chunk).where(Chunk.document_id == d.id).order_by(Chunk.ordinal).limit(200))
    return {"id": str(d.id), "title": d.title, "file_type": d.file_type, "pages": d.pages,
            "chunks": [{"page": c.page, "section": c.section, "text": c.text} for c in chunks],
            "can_comment": can_access_object(db, principal, "document", document_id, "comment")}


@router.get("/shared/notes/{note_id}")
def shared_note(note_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("read:shared"))):
    _require(db, principal, "note", note_id)
    n = db.get(Note, note_id)
    if n is None:
        raise NotFound("Note")
    return {**note_out(n), "can_comment": can_access_object(db, principal, "note", note_id, "comment")}


@router.get("/shared/library/ask")
def shared_ask(q: str = Query(min_length=3, max_length=1000), db: DB = Depends(get_db, scope="function"),
               principal: Principal = Depends(perm("read:shared"))):
    """Retrieval over documents shared with the caller only (SQL-scoped)."""
    from app.modules.knowledge.answers import answer

    return answer(db, principal, q, use_model=False, record=False)
