"""Exchange session math, computed server-side from the installed exchange_calendars library (plus an in-house
FX 24×5 calendar). All instants are UTC; venue-local labels are derived from the venue's IANA zone.

This module is informational only. It must never import from the orders or brokers modules: no countdown or
timer can trigger an order (enforced by a static test).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from importlib.metadata import version as pkg_version
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from app.modules.markets.registry import VENUES

CALENDAR_START = "2023-01-01"
NY = ZoneInfo("America/New_York")


@dataclass
class SessionWindow:
    session_date: date
    open: datetime
    close: datetime
    break_start: datetime | None = None
    break_end: datetime | None = None
    early_close: bool = False

    def as_dict(self, tz: ZoneInfo) -> dict:
        def fmt(dt: datetime | None):
            return None if dt is None else {"utc": dt.isoformat(), "local": dt.astimezone(tz).strftime("%H:%M")}

        return {"date": self.session_date.isoformat(), "open": fmt(self.open), "close": fmt(self.close),
                "break_start": fmt(self.break_start), "break_end": fmt(self.break_end),
                "early_close": self.early_close}


def library_info() -> dict:
    return {"package": "exchange_calendars", "version": pkg_version("exchange_calendars"),
            "note": "Session accuracy depends on this library's release. Update it to pick up new holidays "
                    "and schedule changes."}


@lru_cache(maxsize=16)
def _xcal(code: str):
    return xcals.get_calendar(code, start=CALENDAR_START)


def _to_dt(value) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    return value.to_pydatetime().astimezone(UTC)


def _fx_sessions(start: date, end: date) -> list[SessionWindow]:
    """FX spot trades 24×5: Sunday 17:00 New York to Friday 17:00 New York. Each Mon–Fri session runs from
    17:00 NY on the previous day. Market-wide holiday thinning (e.g. 25 Dec, 1 Jan) is not modelled."""
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            open_local = datetime.combine(d - timedelta(days=1), time(17, 0), NY)
            close_local = datetime.combine(d, time(17, 0), NY)
            out.append(SessionWindow(d, open_local.astimezone(UTC), close_local.astimezone(UTC)))
        d += timedelta(days=1)
    return out


def sessions_between(mic: str, start: date, end: date) -> list[SessionWindow]:
    v = VENUES[mic]
    if v.calendar == "FX24x5":
        return _fx_sessions(start, end)
    cal = _xcal(v.calendar)
    first, last = cal.first_session.date(), cal.last_session.date()
    start, end = max(start, first), min(end, last)
    if start > end:
        return []
    sched = cal.schedule.loc[pd.Timestamp(start):pd.Timestamp(end)]
    early = {ts.date() for ts in cal.early_closes}
    out = []
    for idx, row in sched.iterrows():
        out.append(SessionWindow(idx.date(), _to_dt(row["open"]), _to_dt(row["close"]),
                                 _to_dt(row.get("break_start")), _to_dt(row.get("break_end")),
                                 idx.date() in early))
    return out


def holidays_between(mic: str, start: date, end: date) -> list[dict]:
    """Weekdays that are normally trading days for this venue but have no session."""
    v = VENUES[mic]
    if v.calendar == "FX24x5":
        return []
    sessions = {s.session_date for s in sessions_between(mic, start - timedelta(days=7), end + timedelta(days=7))}
    names: dict[date, str] = {}
    try:
        cal = _xcal(v.calendar)
        hol = cal.regular_holidays.holidays(pd.Timestamp(start), pd.Timestamp(end), return_name=True)
        names = {ts.date(): str(name) for ts, name in hol.items()}
    except Exception:  # noqa: BLE001 - names are a nicety; dates are what matter
        names = {}
    out = []
    d = start
    while d <= end:
        if d not in sessions and (d - timedelta(days=7) in sessions or d + timedelta(days=7) in sessions):
            out.append({"date": d.isoformat(), "name": names.get(d, "Exchange holiday")})
        d += timedelta(days=1)
    return out


def session_state(mic: str, at: datetime) -> dict:
    """Current state at `at` (UTC) plus the next valid open/close for countdowns."""
    v = VENUES[mic]
    tz = ZoneInfo(v.timezone)
    local = at.astimezone(tz)
    windows = sessions_between(mic, local.date() - timedelta(days=10), local.date() + timedelta(days=21))
    state, reason, current, next_event = "closed", None, None, None

    for w in windows:
        if w.open <= at < w.close:
            current = w
            if w.break_start and w.break_end and w.break_start <= at < w.break_end:
                state, reason = "break", "Lunch break"
                next_event = {"kind": "resumes", "at": w.break_end}
            else:
                closes_local = w.close.astimezone(tz).strftime("%H:%M")
                state, reason = "open", f"Shortened session (closes {closes_local})" if w.early_close else None
                if w.break_start and at < w.break_start:
                    next_event = {"kind": "break_starts", "at": w.break_start}
                else:
                    next_event = {"kind": "closes", "at": w.close}
            break

    upcoming = [w for w in windows if w.open > at]
    next_open = upcoming[0].open if upcoming else None
    if state == "closed":
        today_sessions = [w for w in windows if w.session_date == local.date()]
        if v.calendar == "FX24x5":
            reason = "Weekend (FX reopens Sunday 17:00 New York)"
        elif today_sessions and today_sessions[0].close <= at:
            reason = "After close"
        elif today_sessions:
            reason = "Before open"
        else:
            holiday = holidays_between(mic, local.date(), local.date())
            reason = f"Holiday: {holiday[0]['name']}" if holiday else "Weekend"
        if next_open:
            next_event = {"kind": "opens", "at": next_open}

    if next_event and next_event["at"] is not None:
        seconds = int((next_event["at"] - at).total_seconds())
        next_event = {"kind": next_event["kind"], "at": next_event["at"].isoformat(), "seconds": seconds}

    today = current or next((w for w in windows if w.session_date == local.date()), None)
    offset = local.utcoffset() or timedelta(0)
    return {
        "mic": mic,
        "timezone": v.timezone,
        "local_time": local.isoformat(),
        "utc_offset_minutes": int(offset.total_seconds() // 60),
        "state": state,
        "reason": reason,
        "next_event": next_event,
        "today": today.as_dict(tz) if today else None,
        "next_open": next_open.isoformat() if next_open else None,
    }


def date_difference_days(home_tz: str, venue_tz: str, at: datetime) -> int:
    """Calendar-date difference between the venue and home (e.g. +1 when Tokyo is already 'tomorrow')."""
    home = at.astimezone(ZoneInfo(home_tz)).date()
    there = at.astimezone(ZoneInfo(venue_tz)).date()
    return (there - home).days


def is_open(mic: str, at: datetime) -> bool:
    return session_state(mic, at)["state"] == "open"
