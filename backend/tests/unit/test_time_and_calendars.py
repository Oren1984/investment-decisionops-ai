"""Controlled-time suite (PROJECT_PLAN §7.4, §17.3). Dates verified against the installed exchange_calendars
release and the official TASE/US schedules for 2025–2026."""

from datetime import UTC, date, datetime

import pytest

from app.modules.calendar.sessions import (
    date_difference_days,
    holidays_between,
    session_state,
    sessions_between,
)


def at(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


def test_israel_dst_start_shifts_offset():
    before = session_state("XTAE", at("2026-03-26T10:00:00+00:00"))
    after = session_state("XTAE", at("2026-03-30T10:00:00+00:00"))
    assert before["utc_offset_minutes"] == 120  # IST
    assert after["utc_offset_minutes"] == 180  # IDT from 27 Mar 2026


def test_us_eu_dst_mismatch_window():
    # US moved to EDT on 8 Mar 2026; Europe stays on CET until 29 Mar → NY–Berlin gap is 5 h, not 6.
    s = sessions_between("XNYS", date(2026, 3, 16), date(2026, 3, 16))[0]
    assert s.open == at("2026-03-16T13:30:00+00:00")
    x = sessions_between("XETR", date(2026, 3, 16), date(2026, 3, 16))[0]
    assert x.open == at("2026-03-16T08:00:00+00:00")
    assert (s.open - x.open).total_seconds() == 5.5 * 3600


def test_eu_and_us_dst_end():
    eu = sessions_between("XLON", date(2026, 10, 26), date(2026, 10, 26))[0]
    assert eu.open == at("2026-10-26T08:00:00+00:00")  # GMT after 25 Oct
    us = sessions_between("XNYS", date(2026, 10, 30), date(2026, 11, 2))
    assert us[0].open == at("2026-10-30T13:30:00+00:00")  # still EDT
    assert us[-1].open == at("2026-11-02T14:30:00+00:00")  # EST after 1 Nov


def test_tase_2025_sunday_to_thursday_vs_2026_monday_to_friday():
    days_2025 = {s.session_date.weekday() for s in sessions_between("XTAE", date(2025, 10, 5), date(2025, 10, 25))}
    days_2026 = {s.session_date.weekday() for s in sessions_between("XTAE", date(2026, 2, 1), date(2026, 2, 28))}
    assert 6 in days_2025 and 4 not in days_2025  # Sunday trades, Friday does not
    assert 6 not in days_2026 and 4 in days_2026  # Monday–Friday from 5 Jan 2026


def test_tase_friday_closes_1350_local():
    st = session_state("XTAE", at("2026-10-23T10:30:00+00:00"))  # Friday 13:30 IDT
    assert st["state"] == "open"
    assert st["today"]["close"]["local"] == "13:50"
    assert st["next_event"]["kind"] == "closes" and st["next_event"]["seconds"] == 20 * 60


def test_tase_holiday_eve_and_holiday():
    hol = {h["date"] for h in holidays_between("XTAE", date(2026, 9, 1), date(2026, 10, 10))}
    assert "2026-09-21" in hol  # Yom Kippur
    st = session_state("XTAE", at("2026-09-21T08:00:00+00:00"))
    assert st["state"] == "closed" and st["reason"].startswith("Holiday")


def test_tokyo_lunch_break_at_1145_jst():
    st = session_state("XTKS", at("2026-10-20T02:45:00+00:00"))
    assert st["state"] == "break"
    assert st["next_event"] == {"kind": "resumes", "at": "2026-10-20T03:30:00+00:00", "seconds": 2700}


def test_shanghai_lunch_break():
    assert session_state("XSHG", at("2026-10-20T04:00:00+00:00"))["state"] == "break"
    assert session_state("XSHG", at("2026-10-20T05:00:00+00:00"))["state"] == "open"


def test_us_early_close_day_after_thanksgiving():
    st = session_state("XNYS", at("2026-11-27T17:59:00+00:00"))
    assert st["state"] == "open" and st["today"]["close"]["local"] == "13:00" and st["today"]["early_close"]
    assert session_state("XNYS", at("2026-11-27T18:00:00+00:00"))["state"] == "closed"


def test_us_holiday_thanksgiving():
    assert {"date": "2026-11-26", "name": "Thanksgiving"} in holidays_between("XNYS", date(2026, 11, 20), date(2026, 11, 30))


@pytest.mark.parametrize("instant,expected", [
    ("2026-10-18T20:59:00+00:00", "closed"),  # Sunday 16:59 New York
    ("2026-10-18T21:00:00+00:00", "open"),    # Sunday 17:00 New York
    ("2026-10-23T20:59:00+00:00", "open"),    # Friday 16:59
    ("2026-10-23T21:00:00+00:00", "closed"),  # Friday 17:00
])
def test_fx_week_boundaries(instant, expected):
    assert session_state("FXSP", at(instant))["state"] == expected


def test_countdown_at_exact_boundary():
    st = session_state("XNYS", at("2026-10-19T13:30:00+00:00"))  # exactly 09:30 New York
    assert st["state"] == "open" and st["next_event"]["kind"] == "closes"
    st = session_state("XNYS", at("2026-10-19T13:29:59+00:00"))
    assert st["state"] == "closed" and st["next_event"] == {"kind": "opens", "at": "2026-10-19T13:30:00+00:00", "seconds": 1}


def test_date_difference_jerusalem_monday_0130():
    t = at("2026-10-18T22:30:00+00:00")  # Mon 01:30 Jerusalem
    assert date_difference_days("Asia/Jerusalem", "Asia/Tokyo", t) == 0  # Tokyo: Monday 07:30
    assert date_difference_days("Asia/Jerusalem", "America/New_York", t) == -1  # New York: Sunday 18:30


def test_session_spanning_utc_midnight_tokyo():
    s = sessions_between("XTKS", date(2026, 10, 20), date(2026, 10, 20))[0]
    assert s.open == at("2026-10-20T00:00:00+00:00")  # 09:00 JST = 00:00 UTC
