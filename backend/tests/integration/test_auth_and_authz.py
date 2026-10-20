"""Identity, sessions, CSRF, step-up, TOTP, and the role × endpoint × foreign-ID authorization matrix."""

import uuid

import pyotp
import pytest
from fastapi.routing import APIRoute

from app.config import get_settings
from app.core.db import db_session
from tests.conftest import OWNER_EMAIL, OWNER_PASSWORD, Api, _client, make_collaborator


def test_every_route_declares_exactly_one_permission():
    from app.main import app

    def perms(dependant):
        found = []
        for dep in dependant.dependencies:
            if hasattr(dep.call, "__permission__"):
                found.append(dep.call.__permission__)
            found += perms(dep)
        return found

    missing = [r.path for r in app.routes if isinstance(r, APIRoute) and len(perms(r.dependant)) != 1]
    assert missing == [], f"routes without exactly one permission: {missing}"


def test_setup_token_is_single_use(owner_setup, anon):
    r = anon.post("/api/auth/setup", {"setup_token": "anything", "email": "x@example.com", "display_name": "X",
                                      "password": "another-long-password", "timezone": "UTC"})
    assert r.status_code == 409  # owner exists; setup is closed


def test_logout_invalidates_session_server_side(owner_setup):
    api = Api(_client())
    assert api.post("/api/auth/login", {"email": OWNER_EMAIL, "password": OWNER_PASSWORD}).status_code == 200
    stolen = dict(api.c.cookies)
    assert api.get("/api/portfolio").status_code == 200
    assert api.post("/api/auth/logout").status_code == 200
    replay = Api(_client())
    for k, v in stolen.items():
        replay.c.cookies.set(k, v)
    assert replay.get("/api/portfolio").status_code == 401  # the old cookie no longer works


def test_csrf_header_required_for_writes(owner):
    r = owner.c.post("/api/markets/watchlists", json={"name": "No CSRF"})
    assert r.status_code == 403 and r.json()["code"] == "csrf_failed"


def test_generic_login_error_and_rate_limit(owner_setup):
    api = Api(_client())
    email = f"nobody-{uuid.uuid4().hex[:6]}@example.com"
    for _ in range(5):
        r = api.post("/api/auth/login", {"email": email, "password": "wrong-password-123"})
        assert r.status_code == 401 and r.json()["message"] == "Email or password is incorrect."
    assert api.post("/api/auth/login", {"email": email, "password": "wrong-password-123"}).status_code == 429


def test_weak_passwords_rejected(owner):
    r = owner.post("/api/invitations", {"email": "weak@example.com", "display_name": "W", "timezone": "UTC"})
    token = r.json()["accept_path"].rsplit("/", 1)[1]
    api = Api(_client())
    assert api.post("/api/invitations/accept", {"token": token, "password": "short"}).status_code == 422
    assert api.post("/api/invitations/accept", {"token": token, "password": "password1234"}).status_code == 422


def test_step_up_required_for_sensitive_actions(owner):
    r = owner.put("/api/settings/limits", {"max_order_notional_home": 1000000, "max_position_pct": 50,
                                            "max_orders_per_day": 200, "price_collar_pct": 10})
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"
    owner.step_up()
    r = owner.put("/api/settings/limits", {"max_order_notional_home": 1000000, "max_position_pct": 50,
                                            "max_orders_per_day": 200, "price_collar_pct": 10})
    assert r.status_code == 200


def test_totp_enrolment_login_and_recovery_code(owner):
    collab, _ = make_collaborator(owner, password="synthetic-test-collab-pass")
    collab.step_up("synthetic-test-collab-pass")
    secret = collab.post("/api/auth/totp/setup").json()["secret"]
    codes = collab.post("/api/auth/totp/enable", {"code": pyotp.TOTP(secret).now()}).json()["recovery_codes"]
    assert len(codes) == 10
    email = collab.get("/api/auth/me").json()["email"]
    api = Api(_client())
    r = api.post("/api/auth/login", {"email": email, "password": "synthetic-test-collab-pass"})
    assert r.status_code == 401 and r.json()["code"] == "totp_required"
    assert api.post("/api/auth/login", {"email": email, "password": "synthetic-test-collab-pass",
                                        "recovery_code": codes[0]}).status_code == 200
    api2 = Api(_client())
    assert api2.post("/api/auth/login", {"email": email, "password": "synthetic-test-collab-pass",
                                         "recovery_code": codes[0]}).status_code == 401  # single use


def test_password_change_revokes_other_sessions(owner):
    collab, _ = make_collaborator(owner, password="synthetic-test-collab-pass")
    email = collab.get("/api/auth/me").json()["email"]
    other = Api(_client())
    other.post("/api/auth/login", {"email": email, "password": "synthetic-test-collab-pass"})
    assert collab.post("/api/auth/password", {"current_password": "synthetic-test-collab-pass",
                                              "new_password": "synthetic-test-collab-pass-2"}).status_code == 200
    assert other.get("/api/auth/me").status_code == 401
    assert collab.get("/api/auth/me").status_code == 200


OWNER_ONLY_GETS = ["/api/portfolio", "/api/orders", "/api/orders/broker", "/api/decisions", "/api/library/documents",
                   "/api/settings", "/api/audit", "/api/ops/summary", "/api/people", "/api/shares", "/api/notes",
                   "/api/markets/quotes", "/api/settings/integrations"]


def test_collaborator_matrix_default_deny(owner):
    collab, _ = make_collaborator(owner)
    for path in OWNER_ONLY_GETS:
        assert collab.get(path).status_code == 403, path
    d = owner.get("/api/decisions").json()
    foreign = d[0]["id"] if d else str(uuid.uuid4())
    for path in (f"/api/decisions/{foreign}", f"/api/decisions/{foreign}/evidence", f"/api/shared/decisions/{foreign}"):
        assert collab.get(path).status_code == 403, path
    writes = [("post", "/api/orders", {}), ("post", "/api/decisions", {}), ("post", "/api/shares", {}),
              ("post", "/api/orders/stop", {"engaged": True}), ("put", "/api/settings/trading-mode", {"mode": "mock"})]
    for method, path, body in writes:
        assert getattr(collab, method)(path, body).status_code in (403, 422), path
    # What collaborators may use
    for path in ("/api/shared", "/api/help", "/api/time", "/api/markets/venues", "/api/calendar/venues/XNYS/state"):
        assert collab.get(path).status_code == 200, path


@pytest.fixture
def demo_profile(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_profile", "demo")
    yield
    monkeypatch.setattr(get_settings(), "app_profile", "test")


def test_demo_is_read_only_through_direct_api(owner_setup, demo_profile):
    from app.modules.identity.service import ensure_demo_user

    with db_session() as db:
        ensure_demo_user(db)
    s = get_settings()
    client = _client()
    signed_in = client.post("/api/auth/login", json={"email": s.demo_user_email, "password": s.demo_user_password})
    client.cookies.set("dops_demo", signed_in.cookies["dops_demo"])  # the browser scopes it to /demo
    demo = Api(client)
    assert demo.get("/api/auth/status").json()["user"]["role"] == "demo"
    for path in ("/api/portfolio", "/api/decisions", "/api/orders", "/api/library/documents"):
        assert demo.get(path).status_code == 200, path
    for method, path, body in [("post", "/api/orders", {}), ("post", "/api/decisions", {"title": "x"}),
                               ("post", "/api/library/documents", None), ("post", "/api/invitations", {}),
                               ("put", "/api/settings/preferences", {}), ("post", "/api/orders/stop", {"engaged": True}),
                               ("delete", "/api/shares/00000000-0000-0000-0000-000000000000", None),
                               ]:
        r = getattr(demo, method)(path, body) if body is not None else getattr(demo, method)(path)
        assert r.status_code == 403, (method, path, r.status_code)
    # Owner credentials never open the demo; only the demo account can sign in there.
    assert demo.post("/api/auth/login", {"email": OWNER_EMAIL, "password": OWNER_PASSWORD}).status_code == 401


def test_permission_check_does_not_hold_the_session_row_lock(owner):
    """Regression (E2E hang): a streaming response (SSE) keeps its dependencies open for the whole stream. The
    permission check's last_seen update must be committed at once, or the session row stays locked and every other
    request of that session blocks until the stream ends."""
    import psycopg
    from starlette.requests import Request

    from app.core.authz import SESSION_COOKIE, perm
    from app.core.db import session_factory
    from app.core.security import sha256_hex
    from tests.conftest import ADMIN_URL, DB_NAME

    session_id = sha256_hex(owner.c.cookies.get(SESSION_COOKIE))
    db_url = f"{ADMIN_URL.rsplit('/', 1)[0]}/{DB_NAME}"
    with psycopg.connect(db_url, autocommit=True) as conn:  # make the next request touch last_seen
        conn.execute("UPDATE user_session SET last_seen_at = now() - interval '60 seconds' WHERE id = %s", (session_id,))

    request = Request({"type": "http", "method": "GET", "path": "/api/events", "query_string": b"",
                       "headers": [(b"cookie", f"{SESSION_COOKIE}={owner.c.cookies.get(SESSION_COOKIE)}".encode())]})
    db = session_factory()()
    try:
        assert perm("any")(request, db).session_id == session_id  # dependency stays open, like during a stream
        assert not db.in_transaction()
        with psycopg.connect(db_url, autocommit=True) as conn:  # another request of the same session can proceed
            conn.execute("SET lock_timeout = '2s'")
            row = conn.execute("SELECT last_seen_at > now() - interval '30 seconds' FROM user_session WHERE id = %s "
                               "FOR UPDATE NOWAIT", (session_id,)).fetchone()
        assert row == (True,)  # the touch is committed and visible
    finally:
        db.close()


def test_writes_are_committed_before_the_response_is_sent(owner, monkeypatch):
    """Regression (J6 race): with FastAPI's default "request" scope, get_db committed only after the response had
    been sent, so the client could act on a 200 (e.g. "removed") before the change was visible."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.main import app

    events: list[str] = []
    real_commit = Session.commit

    def commit(self):
        events.append("commit")
        return real_commit(self)

    async def recording_app(scope, receive, send):
        async def recording_send(message):
            if message["type"] == "http.response.start":
                events.append("response")
            await send(message)

        await app(scope, receive, recording_send)

    api = Api(TestClient(recording_app))
    api.c.cookies = owner.c.cookies
    monkeypatch.setattr(Session, "commit", commit)
    for method, path, body in (("post", "/api/notes", {"title": "Commit order", "body": "x"}),
                               ("delete", "/api/meetings/" + str(uuid.uuid4()), None)):
        events.clear()
        r = api.post(path, body) if method == "post" else api.delete(path)
        assert r.status_code in (200, 404), r.text
        assert "commit" in events and events[-1] == "response", events  # nothing is committed after the response
