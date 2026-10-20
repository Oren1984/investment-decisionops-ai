"""Collaboration revocation and SSE access re-checks, meetings across timezones (DST mismatch, day shift) with a
fake Zoom API (httpx MockTransport), ops alerts, and the DB guards that keep evidence and audit immutable."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import psycopg
import pytest
from sqlalchemy import select, text

from app.core.clock import Clock, FrozenClock, set_clock, utcnow
from app.core.db import db_session
from tests.conftest import instrument_id, make_collaborator, run_workflow_inline


def _decision(owner, symbol="MSFT"):
    r = owner.post("/api/decisions", {"title": f"Shared {symbol}", "question": f"Should I add to {symbol}?",
                                      "instrument_ids": [instrument_id(owner, symbol)], "start_run": True})
    d = r.json()
    run_workflow_inline(d["run_id"])
    return d["id"]


def _principal(user_id: str):
    from app.core.authz import Principal
    from app.modules.identity.models import Session, User

    with db_session() as db:
        u = db.get(User, uuid.UUID(user_id))
        s = db.scalar(select(Session).where(Session.user_id == u.id).order_by(Session.created_at.desc()))
        return Principal(user_id=u.id, role=u.role, email=u.email, display_name=u.display_name, timezone=u.timezone,
                         session_id=s.id)


# ---------- collaboration + SSE ----------

def test_share_revocation_applies_to_api_and_event_stream(owner):
    from app.modules.ops.events import _still_allowed

    decision_id = _decision(owner)
    collab, collab_id = make_collaborator(owner)
    assert collab.get(f"/api/shared/decisions/{decision_id}").status_code in (403, 404)
    p = _principal(collab_id)
    assert _still_allowed(p, "decision", "decision", decision_id) == (True, False)

    share = owner.post("/api/shares", {"object_type": "decision", "object_id": decision_id, "grantee_id": collab_id})
    assert share.status_code == 200, share.text
    assert collab.get(f"/api/shared/decisions/{decision_id}").status_code == 200
    assert _still_allowed(p, "decision", "decision", decision_id) == (True, True)
    assert _still_allowed(p, "order", "order", str(uuid.uuid4())) == (True, False)  # owner-only event kinds
    assert _still_allowed(p, "run", "decision", decision_id) == (True, False)

    owner.delete(f"/api/shares/{share.json()['id']}")
    assert collab.get(f"/api/shared/decisions/{decision_id}").status_code in (403, 404)
    assert _still_allowed(p, "decision", "decision", decision_id) == (True, False)

    # Revoking the collaborator ends their sessions: open streams receive session_ended.
    assert owner.post(f"/api/people/{collab_id}/revoke").status_code == 200
    assert _still_allowed(p, "ping", "none", "none") == (False, False)
    assert collab.get("/api/auth/me").status_code == 401


def test_expired_share_is_not_visible(owner):
    decision_id = _decision(owner, "AAPL")
    collab, collab_id = make_collaborator(owner)
    soon = (utcnow() + timedelta(minutes=5)).isoformat()
    owner.post("/api/shares", {"object_type": "decision", "object_id": decision_id, "grantee_id": collab_id,
                               "expires_at": soon})
    assert collab.get(f"/api/shared/decisions/{decision_id}").status_code == 200
    set_clock(FrozenClock(utcnow() + timedelta(minutes=10)))
    try:
        assert collab.get(f"/api/shared/decisions/{decision_id}").status_code in (403, 404)
    finally:
        set_clock(Clock())


# ---------- meetings ----------

def test_meeting_times_across_dst_mismatch_and_day_shift(owner):
    # 20 Mar 2026: the US is on DST (since 8 Mar), Europe not yet (29 Mar), Israel not yet (27 Mar).
    r = owner.post("/api/meetings", {"title": "Broker call", "starts_at": "2026-03-20T13:00:00Z",
                                     "timezone": "Asia/Jerusalem", "provider": "mock",
                                     "participants": [{"name": "NY broker", "timezone": "America/New_York"},
                                                      {"name": "London analyst", "timezone": "Europe/London"},
                                                      {"name": "Tokyo desk", "timezone": "Asia/Tokyo"}]})
    assert r.status_code == 200, r.text
    m = r.json()
    times = {p["name"]: p["time"] for p in m["participants"]}
    assert m["owner_time"]["local"].startswith("2026-03-20T15:00") and m["owner_time"]["utc_offset"] == "+0200"
    assert times["NY broker"]["local"].startswith("2026-03-20T09:00")  # UTC-4 during the mismatch window
    assert times["London analyst"]["local"].startswith("2026-03-20T13:00")  # still UTC+0
    assert m["simulated"] is True and m["provider_status"] == "simulated"

    late = owner.post("/api/meetings", {"title": "Late call", "starts_at": "2026-10-19T22:30:00Z",
                                        "timezone": "Asia/Jerusalem", "provider": "mock",
                                        "participants": [{"name": "Tokyo desk", "timezone": "Asia/Tokyo"},
                                                         {"name": "NY broker", "timezone": "America/New_York"}]}).json()
    shifts = {p["name"]: p["time"]["day_shift"] for p in late["participants"]}
    assert shifts == {"Tokyo desk": 0, "NY broker": -1}  # relative to the meeting timezone (01:30 Tue Jerusalem)


def _link(owner, join_url, link_provider=None, method="post", path="/api/meetings"):
    body = {"title": "Link check", "starts_at": "2026-11-02T10:00:00Z", "provider": "manual", "join_url": join_url}
    if link_provider is not None:
        body["link_provider"] = link_provider
    return getattr(owner, method)(path, body)


@pytest.mark.parametrize(("link_provider", "url", "stored"), [
    ("zoom", "https://us02web.zoom.us/j/123456789?pwd=abc", "zoom"),
    ("zoom", "https://zoomgov.com/j/123", "zoom"),
    ("google_meet", "https://meet.google.com/abc-defg-hij", "google_meet"),
    ("teams", "https://teams.microsoft.com/l/meetup-join/19%3ameeting_x%40thread.v2/0", "teams"),
    ("teams", "https://teams.live.com/meet/9876543210", "teams"),
    ("other", "https://meet.jit.si/DecisionOpsReview", "other"),
    ("other", "https://meet.google.com/abc-defg-hij", "google_meet"),  # a known host is recognised
    (None, "https://zoom.us/j/1", "zoom"),  # older clients that send no provider: detected
])
def test_meeting_links_for_each_provider(owner, link_provider, url, stored):
    r = _link(owner, url, link_provider)
    assert r.status_code == 200, r.text
    m = r.json()
    assert (m["provider_status"], m["join_url"], m["link_provider"]) == ("linked", url, stored)
    assert "new browser tab" in m["provider_note"]


@pytest.mark.parametrize(("link_provider", "url"), [
    ("zoom", "https://evil.example.com/j/123"),  # wrong host for the chosen provider
    ("google_meet", "https://meet.google.com.evil.example/abc"),  # look-alike suffix
    ("teams", "https://zoom.us/j/1"),
    ("other", "http://meet.jit.si/x"),  # not https
    ("other", "javascript:alert(1)"),
    ("other", "data:text/html,<script>alert(1)</script>"),
    ("other", "https://user:secret@meet.jit.si/x"),  # embedded credentials
    ("other", "https://meet.jit.si@evil.example/x"),
    ("other", "https://127.0.0.1/meeting"),  # IP literal
    ("other", "https://[::1]/meeting"),
    ("other", "https://localhost/meeting"),
    ("other", "https://intranet/meeting"),  # not a public DNS name
    ("other", "https://meet.jit.si:8443/x"),  # non-standard port
    ("other", "https://meet.jit.si/a b"),  # whitespace
    ("other", "https://meet.jit.si/\x00"),
    ("other", ""),
    ("other", "https://meet.jit.si/" + "a" * 2100),
])
def test_unsafe_or_mismatched_meeting_links_are_rejected(owner, link_provider, url):
    r = _link(owner, url, link_provider)
    assert r.status_code == 422 and r.json()["code"] in ("invalid_link", "validation_error"), r.text


def test_meeting_link_can_be_edited_and_collaborators_cannot_change_it(owner):
    m = _link(owner, "https://zoom.us/j/111", "zoom").json()
    path = f"/api/meetings/{m['id']}"
    edited = _link(owner, "https://meet.google.com/xyz-abcd-efg", "google_meet", method="put", path=path)
    assert edited.status_code == 200 and edited.json()["link_provider"] == "google_meet"
    assert edited.json()["join_url"] == "https://meet.google.com/xyz-abcd-efg"
    bad = _link(owner, "https://evil.example.com/x", "teams", method="put", path=path)
    assert bad.status_code == 422
    listed = {x["id"]: x for x in owner.get("/api/meetings").json()}
    assert listed[m["id"]]["join_url"] == "https://meet.google.com/xyz-abcd-efg"  # a rejected edit changes nothing
    back = owner.put(path, {"title": "Link check", "starts_at": "2026-11-02T10:00:00Z", "provider": "mock"}).json()
    assert back["join_url"] is None and back["link_provider"] is None and back["simulated"] is True

    collab, _ = make_collaborator(owner)
    assert _link(collab, "https://meet.google.com/xyz-abcd-efg", "google_meet").status_code == 403
    assert _link(collab, "https://meet.google.com/xyz-abcd-efg", "google_meet", method="put", path=path).status_code == 403
    assert collab.delete(path).status_code == 403



def test_meeting_companion_shows_collaborators_only_notes_shared_with_them(owner):
    """A meeting share does not expose the meeting's notes: each note needs its own grant (same rule as /shared)."""
    m = _link(owner, "https://zoom.us/j/222", "zoom").json()
    private = owner.post("/api/notes", {"title": "Owner-only note", "body": "private body", "meeting_id": m["id"]}).json()
    shared = owner.post("/api/notes", {"title": "Shared note", "body": "shared body", "meeting_id": m["id"]}).json()
    collab, collab_id = make_collaborator(owner)
    assert collab.get(f"/api/meetings/{m['id']}/companion").status_code == 403  # no meeting grant yet

    owner.post("/api/shares", {"object_type": "meeting", "object_id": m["id"], "grantee_id": collab_id})
    assert collab.get(f"/api/meetings/{m['id']}/companion").json()["notes"] == []

    owner.post("/api/shares", {"object_type": "note", "object_id": shared["id"], "grantee_id": collab_id})
    notes = collab.get(f"/api/meetings/{m['id']}/companion").json()["notes"]
    assert [n["id"] for n in notes] == [shared["id"]]
    assert "private body" not in collab.get(f"/api/meetings/{m['id']}/companion").text
    # The owner still sees every note on the meeting.
    assert {n["id"] for n in owner.get(f"/api/meetings/{m['id']}/companion").json()["notes"]} == {private["id"], shared["id"]}

def _zoom(handler):
    from app.modules.meetings.providers import ZoomProvider

    z = ZoomProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    z.account_id, z.client_id, z.secret = "acc", "cid", "sec"
    z.api, z.oauth = "https://api.zoom.test/v2", "https://zoom.test/oauth/token"
    return z


def test_zoom_server_to_server_flow_with_fake_api():
    from app.modules.meetings.models import Meeting
    from app.modules.meetings.router import MeetingIn, _schedule

    seen = []

    def ok(request: httpx.Request):
        seen.append(request)
        if request.url.path == "/oauth/token":
            assert request.url.params["grant_type"] == "account_credentials"
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if request.method == "POST":
            assert request.headers["Authorization"] == "Bearer tok"
            return httpx.Response(201, json={"id": 987, "join_url": "https://zoom.us/j/987"})
        return httpx.Response(204)

    jerusalem = datetime(2026, 11, 2, 12, 0, tzinfo=UTC).astimezone(ZoneInfo("Asia/Jerusalem"))  # 14:00 local
    body = MeetingIn(title="Review", starts_at=jerusalem, provider="zoom")
    m = Meeting(title="Review", starts_at=jerusalem, duration_minutes=30, timezone="Asia/Jerusalem", agenda="",
                provider="zoom")
    zoom = _zoom(ok)
    _schedule(m, body, zoom)
    assert m.provider_status == "scheduled" and m.provider_meeting_id == "987"
    sent = json.loads(seen[-1].content)
    assert sent["start_time"] == "2026-11-02T12:00:00Z" and sent["settings"]["auto_recording"] == "none"
    _schedule(m, body, zoom)  # update path reuses the cached token
    assert seen[-1].method == "PATCH" and sum(r.url.path == "/oauth/token" for r in seen) == 1

    def down(request):
        return httpx.Response(401 if request.url.path == "/oauth/token" else 500)

    m2 = Meeting(title="R", starts_at=jerusalem, duration_minutes=30, timezone="UTC", agenda="", provider="zoom")
    _schedule(m2, body, _zoom(down))
    assert m2.provider_status == "unavailable" and "draft is kept" in m2.provider_error


# ---------- ops alerts ----------

def test_uncertain_order_raises_and_resolves_alert(owner):
    from app.modules.ops.alerts import evaluate
    from app.modules.ops.models import Alert

    t = owner.post("/api/orders", {"instrument_id": instrument_id(owner, "SPY"), "side": "buy", "quantity": 1,
                                   "order_type": "market", "mock_scenario": "disconnect_after_send"}).json()
    from app.modules.orders.models import OrderTicket

    with db_session() as db:  # put the ticket straight into the uncertain state (the order flow is tested elsewhere)
        db.get(OrderTicket, uuid.UUID(t["id"])).status = "uncertain"

    def open_alerts():
        with db_session() as db:
            return {a.key for a in db.scalars(select(Alert).where(Alert.kind == "order_uncertain",
                                                                  Alert.resolved_at.is_(None)))}

    set_clock(FrozenClock(utcnow() + timedelta(minutes=3)))
    try:
        with db_session() as db:
            evaluate(db)
        assert t["id"] in open_alerts()
        with db_session() as db:
            db.get(OrderTicket, uuid.UUID(t["id"])).status = "not_found"
        with db_session() as db:
            evaluate(db)
        assert t["id"] not in open_alerts()
    finally:
        set_clock(Clock())
    r = owner.get("/api/ops/alerts")
    assert r.status_code == 200


# ---------- DB guards ----------

def _raw():
    from tests.conftest import ADMIN_URL, DB_NAME

    return psycopg.connect(f"{ADMIN_URL.rsplit('/', 1)[0]}/{DB_NAME}", autocommit=True)


def test_frozen_evidence_and_audit_are_immutable_in_the_database(owner):
    _decision(owner, "NVDA")
    with _raw() as conn:
        item_id = conn.execute("SELECT i.id FROM evidence_item i JOIN evidence_snapshot s ON s.id = i.snapshot_id "
                               "WHERE s.frozen LIMIT 1").fetchone()[0]
        snap_id = conn.execute("SELECT id FROM evidence_snapshot WHERE frozen LIMIT 1").fetchone()[0]
        for sql in (f"UPDATE evidence_item SET title = 'x' WHERE id = '{item_id}'",
                    f"UPDATE evidence_item SET content = '{{}}' WHERE id = '{item_id}'",
                    f"DELETE FROM evidence_item WHERE id = '{item_id}'",
                    f"UPDATE evidence_snapshot SET snapshot_hash = 'x' WHERE id = '{snap_id}'",
                    f"UPDATE evidence_snapshot SET integrity_status = 'redacted' WHERE id = '{snap_id}'",
                    f"DELETE FROM evidence_snapshot WHERE id = '{snap_id}'",
                    "UPDATE audit_event SET action = 'x'",
                    "DELETE FROM audit_event"):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(sql)
        # Marking a source as removed is the one permitted non-content change.
        conn.execute(f"UPDATE evidence_item SET source_removed_at = now() WHERE id = '{item_id}'")
    with db_session() as db:
        assert db.execute(text("SELECT count(*) FROM audit_event")).scalar() > 0
