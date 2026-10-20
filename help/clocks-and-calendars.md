---
title: Clocks, sessions and the calendar
category: Markets
summary: How venue clocks, countdowns, holidays and calendar sources work.
routes: /markets
---
The clock strip shows your **home clock** and the **selected venue's clock** side by side with timezone, UTC offset and the calendar-date difference (Tokyo is often already “+1 day”).

## How sessions are computed

- All instants are stored in UTC. Venue sessions (open, close, lunch breaks, early closes and holidays) are **computed on the server** from the offline `exchange_calendars` library, plus an in-house FX calendar (Sunday 17:00 to Friday 17:00 New York).
- Daylight-saving changes are handled through IANA timezones (for example `Asia/Jerusalem`, `America/New_York`).
- The Tel Aviv Stock Exchange moved to a Monday–Friday week on 5 January 2026, with a shortened Friday session (closes 13:50). Earlier dates follow the old Sunday–Thursday schedule.
- Accuracy depends on the installed library version, shown in Settings → System. Update the library to pick up new holidays.

## Countdowns and timers

Countdowns use the server clock. **No countdown or timer can trigger an order** — the code has no path from timers to order submission, and a test enforces this.

## Calendar sources

- **Computed** — exchange sessions and holidays.
- **You** — reminders and events you enter.
- **Mock** — synthetic economic events.
- **External** — a confirmed external feed. None is configured by default. A feed shows *Not configured*, *Stale since …* (last data kept and labelled) or *Error* — never invented data.

Meetings show every participant's local time with day-shift markers.
