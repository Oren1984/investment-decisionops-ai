"""Clocks, sessions, calendar and the research timer. Informational only — no path to orders."""

import uuid
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from app.core.authz import Principal, perm
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import AppError, NotFound
from app.modules.calendar import sessions
from app.modules.calendar.models import CalendarEvent, ResearchTimer
from app.modules.markets.registry import VENUES
from app.modules.settings.service import home_timezone

router = APIRouter(tags=["calendar"])


@router.get("/api/time")
def server_time(_=Depends(perm("public"))):
    now = utcnow()
    return {"now_utc": now.isoformat(), "epoch_ms": int(now.timestamp() * 1000)}


def _venue_or_404(mic: str):
    if mic not in VENUES:
        raise NotFound("Venue")
    return VENUES[mic]


@router.get("/api/calendar/venues/{mic}/state")
def venue_state(mic: str, db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:sessions"))):
    v = _venue_or_404(mic)
    now = utcnow()
    home = home_timezone(db)
    state = sessions.session_state(mic, now)
    state["home_timezone"] = home
    state["date_difference_days"] = sessions.date_difference_days(home, v.timezone, now)
    state["venue"] = {"mic": v.mic, "name": v.name, "short": v.short, "currency": v.currency}
    return state


@router.get("/api/calendar/venues/{mic}/sessions")
def venue_sessions(mic: str, start: date, end: date, _=Depends(perm("read:sessions"))):
    v = _venue_or_404(mic)
    if (end - start).days > 120:
        raise AppError("range_too_large", "Choose a range of at most 120 days.", status_code=422)
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(v.timezone)
    return {"sessions": [s.as_dict(tz) for s in sessions.sessions_between(mic, start, end)],
            "holidays": sessions.holidays_between(mic, start, end),
            "source": sessions.library_info()}


@router.get("/api/calendar/events")
def events(start: datetime, end: datetime, venues: str = Query("", description="Comma-separated MICs"),
           db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("read:calendar"))):
    if (end - start).days > 62:
        raise AppError("range_too_large", "Choose a range of at most 62 days.", status_code=422)
    out: list[dict] = []
    lib = sessions.library_info()
    for mic in [m for m in venues.split(",") if m in VENUES]:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(VENUES[mic].timezone)
        for s in sessions.sessions_between(mic, start.date(), end.date()):
            out.append({"id": f"session-{mic}-{s.session_date}", "kind": "session", "title": f"{VENUES[mic].short} session"
                        + (" (shortened)" if s.early_close else ""), "starts_at": s.open.isoformat(),
                        "ends_at": s.close.isoformat(), "venue_mic": mic, "source": "computed",
                        "source_name": f"exchange_calendars {lib['version']}", "timezone": str(tz),
                        "break": s.as_dict(tz)["break_start"] is not None})
        for h in sessions.holidays_between(mic, start.date(), end.date()):
            out.append({"id": f"holiday-{mic}-{h['date']}", "kind": "holiday", "title": f"{VENUES[mic].short}: {h['name']}",
                        "starts_at": h["date"], "ends_at": None, "venue_mic": mic, "source": "computed",
                        "source_name": f"exchange_calendars {lib['version']}", "all_day": True})
    for e in db.scalars(select(CalendarEvent).where(CalendarEvent.starts_at >= start, CalendarEvent.starts_at < end)):
        out.append(event_out(e))
    from app.modules.meetings.models import Meeting
    for m in db.scalars(select(Meeting).where(Meeting.starts_at >= start, Meeting.starts_at < end)):
        out.append({"id": f"meeting-{m.id}", "kind": "meeting", "title": m.title, "starts_at": m.starts_at.isoformat(),
                    "ends_at": (m.starts_at + timedelta(minutes=m.duration_minutes)).isoformat(),
                    "source": "mock" if m.provider == "mock" else "user", "source_name": m.provider,
                    "meeting_id": str(m.id)})
    out.sort(key=lambda e: e["starts_at"])
    return out


def event_out(e: CalendarEvent) -> dict:
    return {"id": str(e.id), "kind": e.kind, "title": e.title, "notes": e.notes, "starts_at": e.starts_at.isoformat(),
            "ends_at": e.ends_at.isoformat() if e.ends_at else None, "timezone": e.timezone, "source": e.source,
            "source_name": e.source_name, "fetched_at": e.fetched_at, "venue_mic": e.venue_mic}


class EventIn(BaseModel):
    kind: Literal["reminder", "economic", "research_cycle"]
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    starts_at: datetime
    ends_at: datetime | None = None
    timezone: str = "UTC"
    venue_mic: str | None = None


@router.post("/api/calendar/events")
def create_event(body: EventIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:calendar"))):
    if body.starts_at.tzinfo is None:
        raise AppError("timezone_required", "Send times with a UTC offset (ISO 8601).", status_code=422)
    e = CalendarEvent(owner_id=principal.user_id, kind=body.kind, title=body.title, notes=body.notes,
                      starts_at=body.starts_at, ends_at=body.ends_at, timezone=body.timezone, source="user",
                      source_name="Entered by you", venue_mic=body.venue_mic)
    db.add(e)
    db.flush()
    return event_out(e)


@router.delete("/api/calendar/events/{event_id}")
def delete_event(event_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), _=Depends(perm("write:calendar"))):
    e = db.get(CalendarEvent, event_id)
    if e is None:
        raise NotFound("Event")
    db.delete(e)
    return {"ok": True}


# ---------- research timer (informational only) ----------

class TimerIn(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    duration_minutes: int = Field(ge=1, le=24 * 60)
    decision_id: uuid.UUID | None = None


def timer_out(t: ResearchTimer) -> dict:
    ends = t.started_at + timedelta(minutes=t.duration_minutes)
    return {"id": str(t.id), "label": t.label, "decision_id": str(t.decision_id) if t.decision_id else None,
            "started_at": t.started_at.isoformat(), "ends_at": ends.isoformat(), "duration_minutes": t.duration_minutes,
            "stopped_at": t.stopped_at.isoformat() if t.stopped_at else None,
            "note": "Informational only. A timer never authorizes or submits an order."}


@router.get("/api/timers")
def timers(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:calendar"))):
    rows = db.scalars(select(ResearchTimer).order_by(ResearchTimer.started_at.desc()).limit(20))
    return [timer_out(t) for t in rows]


@router.post("/api/timers")
def start_timer(body: TimerIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:calendar"))):
    t = ResearchTimer(owner_id=principal.user_id, label=body.label, decision_id=body.decision_id,
                      started_at=utcnow(), duration_minutes=body.duration_minutes)
    db.add(t)
    db.flush()
    return timer_out(t)


@router.post("/api/timers/{timer_id}/stop")
def stop_timer(timer_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), _=Depends(perm("write:calendar"))):
    t = db.get(ResearchTimer, timer_id)
    if t is None:
        raise NotFound("Timer")
    t.stopped_at = t.stopped_at or utcnow()
    return timer_out(t)
