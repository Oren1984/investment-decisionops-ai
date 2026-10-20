import uuid
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from app.core import audit
from app.core.authz import Principal, can_access_object, perm
from app.core.db import get_db
from app.core.errors import AppError, Forbidden, NotFound
from app.modules.collaboration.models import ActionItem, Note
from app.modules.decisions.models import Decision
from app.modules.identity.models import User
from app.modules.meetings.models import Meeting, MeetingParticipant
from app.modules.meetings.providers import (
    LINK_PROVIDERS,
    ProviderUnavailable,
    ZoomProvider,
    validate_meeting_link,
)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])
_ZONES = available_timezones()


def local_view(at: datetime, tz: str, ref_tz: str) -> dict:
    local = at.astimezone(ZoneInfo(tz))
    ref = at.astimezone(ZoneInfo(ref_tz))
    shift = (local.date() - ref.date()).days
    return {"timezone": tz, "local": local.isoformat(), "label": local.strftime("%a %d %b %H:%M"),
            "utc_offset": local.strftime("%z"), "day_shift": shift}


def _provider_note(m: Meeting) -> str:
    if m.provider == "mock":
        return "Simulated – no real meeting exists."
    if m.provider == "manual":
        if m.link_provider in (None, "other"):
            return "Meeting link pasted by the owner. Open meeting opens it in a new browser tab, outside this app."
        label = LINK_PROVIDERS[m.link_provider][0]
        return f"{label} link pasted by the owner. Open meeting opens {label} in a new browser tab, outside this app."
    return "Scheduled through the Zoom API (Server-to-Server OAuth). Open meeting opens Zoom in a new browser tab."


def meeting_out(db: DB, m: Meeting, viewer_tz: str) -> dict:
    parts = db.scalars(select(MeetingParticipant).where(MeetingParticipant.meeting_id == m.id))
    link_label = LINK_PROVIDERS[m.link_provider][0] if m.link_provider in LINK_PROVIDERS else None
    return {
        "id": str(m.id), "title": m.title, "starts_at": m.starts_at.isoformat(), "duration_minutes": m.duration_minutes,
        "ends_at": (m.starts_at + timedelta(minutes=m.duration_minutes)).isoformat(),
        "timezone": m.timezone, "provider": m.provider, "provider_status": m.provider_status,
        "link_provider": m.link_provider, "link_provider_label": link_label,
        "provider_error": m.provider_error, "join_url": m.join_url, "agenda": m.agenda,
        "decision_id": str(m.decision_id) if m.decision_id else None,
        "owner_time": local_view(m.starts_at, m.timezone, viewer_tz),
        "viewer_time": local_view(m.starts_at, viewer_tz, viewer_tz),
        "participants": [{"id": str(p.id), "name": p.name, "user_id": str(p.user_id) if p.user_id else None,
                          "time": local_view(m.starts_at, p.timezone, m.timezone)} for p in parts],
        "simulated": m.provider == "mock",
        "provider_note": _provider_note(m),
        "recording": "Not recorded or transcribed by this app.",
    }


class ParticipantIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str
    user_id: uuid.UUID | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if v not in _ZONES:
            raise ValueError("Unknown IANA timezone")
        return v


class MeetingIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    duration_minutes: int = Field(default=30, ge=5, le=480)
    timezone: str = "Asia/Jerusalem"
    provider: Literal["mock", "manual", "zoom"] = "mock"
    # For manual links: which service the link belongs to. Omitted = detected from the link (default 'other').
    link_provider: Literal["zoom", "google_meet", "teams", "other"] | None = None
    join_url: str | None = Field(default=None, max_length=4096)
    agenda: str = Field(default="", max_length=4000)
    decision_id: uuid.UUID | None = None
    participants: list[ParticipantIn] = []

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if v not in _ZONES:
            raise ValueError("Unknown IANA timezone")
        return v


def _schedule(m: Meeting, body: MeetingIn, zoom: ZoomProvider | None = None) -> None:
    m.provider_error = None
    if body.provider == "mock":
        m.provider_status, m.join_url, m.link_provider = "simulated", None, None
    elif body.provider == "manual":
        try:
            m.join_url, m.link_provider = validate_meeting_link(body.join_url or "", body.link_provider)
        except ValueError as exc:
            raise AppError("invalid_link", str(exc), status_code=422, help_slug="zoom-meetings") from exc
        m.provider_status = "linked"
    else:
        m.link_provider = "zoom"
        zoom = zoom or ZoomProvider()
        if not zoom.configured:
            m.provider_status = "not_configured"
            m.provider_error = "Zoom scheduling is not configured. Paste a manual link or configure a Zoom app."
            return
        try:
            if m.provider_meeting_id:
                zoom.update(m.provider_meeting_id, m.title, m.starts_at, m.duration_minutes, m.timezone, m.agenda)
            else:
                res = zoom.create(m.title, m.starts_at, m.duration_minutes, m.timezone, m.agenda)
                m.provider_meeting_id, m.join_url = res["provider_meeting_id"], res["join_url"]
            m.provider_status = "scheduled"
        except ProviderUnavailable as exc:
            m.provider_status = "unavailable"
            m.provider_error = f"{exc}. The draft is kept; retry later or paste a manual link."


@router.get("")
def list_meetings(db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("read:meetings"))):
    rows = db.scalars(select(Meeting).order_by(Meeting.starts_at))
    out = []
    for m in rows:
        if principal.sees_owner_data or can_access_object(db, principal, "meeting", m.id):
            out.append(meeting_out(db, m, principal.timezone))
    return out


@router.post("")
def create_meeting(body: MeetingIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:meetings"))):
    if body.starts_at.tzinfo is None:
        raise AppError("timezone_required", "Send the start time with a UTC offset.", status_code=422)
    m = Meeting(owner_id=principal.user_id, title=body.title, starts_at=body.starts_at,
                duration_minutes=body.duration_minutes, timezone=body.timezone, provider=body.provider,
                provider_status="draft", agenda=body.agenda, decision_id=body.decision_id)
    db.add(m)
    db.flush()
    for p in body.participants:
        db.add(MeetingParticipant(meeting_id=m.id, name=p.name, timezone=p.timezone, user_id=p.user_id))
    _schedule(m, body)
    audit.record(db, "meeting.created", actor=principal, object_type="meeting", object_id=m.id,
                 details={"provider": m.provider, "status": m.provider_status})
    db.flush()
    return meeting_out(db, m, principal.timezone)


@router.put("/{meeting_id}")
def update_meeting(meeting_id: uuid.UUID, body: MeetingIn, db: DB = Depends(get_db, scope="function"),
                   principal: Principal = Depends(perm("write:meetings"))):
    m = db.get(Meeting, meeting_id)
    if m is None:
        raise NotFound("Meeting")
    for k in ("title", "starts_at", "duration_minutes", "timezone", "agenda", "decision_id", "provider"):
        setattr(m, k, getattr(body, k))
    for p in db.scalars(select(MeetingParticipant).where(MeetingParticipant.meeting_id == m.id)):
        db.delete(p)
    for p in body.participants:
        db.add(MeetingParticipant(meeting_id=m.id, name=p.name, timezone=p.timezone, user_id=p.user_id))
    _schedule(m, body)
    audit.record(db, "meeting.updated", actor=principal, object_type="meeting", object_id=m.id)
    db.flush()
    return meeting_out(db, m, principal.timezone)


@router.delete("/{meeting_id}")
def delete_meeting(meeting_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:meetings"))):
    m = db.get(Meeting, meeting_id)
    if m is None:
        raise NotFound("Meeting")
    db.delete(m)
    audit.record(db, "meeting.deleted", actor=principal, object_type="meeting", object_id=meeting_id)
    return {"ok": True}


@router.get("/{meeting_id}/companion")
def companion(meeting_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("read:meetings"))):
    """Meeting companion page: agenda, shared decision, notes and action items in one view."""
    m = db.get(Meeting, meeting_id)
    if m is None:
        raise NotFound("Meeting")
    if not (principal.sees_owner_data or can_access_object(db, principal, "meeting", m.id)):
        raise Forbidden()
    decision = None
    if m.decision_id and (principal.sees_owner_data or can_access_object(db, principal, "decision", m.decision_id)):
        d = db.get(Decision, m.decision_id)
        decision = {"id": str(d.id), "title": d.title, "status": d.status, "question": d.question}
    notes = [{"id": str(n.id), "title": n.title, "body": n.body, "updated_at": n.updated_at}
             for n in db.scalars(select(Note).where(Note.meeting_id == m.id).order_by(Note.created_at))]
    users = {u.id: u.display_name for u in db.scalars(select(User))}
    items = [{"id": str(a.id), "title": a.title, "status": a.status, "due_at": a.due_at,
              "assignee": users.get(a.assignee_id) if a.assignee_id else None,
              "assignee_id": str(a.assignee_id) if a.assignee_id else None}
             for a in db.scalars(select(ActionItem).where(ActionItem.meeting_id == m.id).order_by(ActionItem.created_at))]
    return {"meeting": meeting_out(db, m, principal.timezone), "decision": decision, "notes": notes,
            "action_items": items, "can_edit": principal.is_owner}
