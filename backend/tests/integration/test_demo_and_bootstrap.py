"""The read-only demo account (isolated demo instance) and the optional first-run owner bootstrap from .env."""

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.db import db_session


@pytest.fixture
def demo_profile(owner_setup):
    from app.modules.identity.service import ensure_demo_user

    s = get_settings()
    with db_session() as db:
        ensure_demo_user(db)
    s.app_profile = "demo"
    yield s
    s.app_profile = "test"


def _client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def test_demo_requires_sign_in_and_stays_read_only(demo_profile):
    c = _client()
    assert c.get("/api/auth/status").json()["authenticated"] is False
    assert c.get("/api/decisions").status_code == 401
    bad = c.post("/api/auth/login", json={"email": demo_profile.demo_user_email, "password": "wrong-password-x"})
    assert bad.status_code == 401
    ok = c.post("/api/auth/login", json={"email": demo_profile.demo_user_email,
                                         "password": demo_profile.demo_user_password})
    assert ok.status_code == 200 and ok.json()["role"] == "demo"
    cookie = ok.cookies.get("dops_demo")
    assert cookie and "Path=/demo" in ok.headers["set-cookie"] and "HttpOnly" in ok.headers["set-cookie"]

    signed = {"Cookie": f"dops_demo={cookie}"}  # the browser sends it under /demo; Caddy strips the prefix
    me = c.get("/api/auth/status", headers=signed).json()
    assert me["authenticated"] is True and me["user"]["role"] == "demo"
    assert c.get("/api/decisions", headers=signed).status_code == 200
    r = c.post("/api/decisions", json={"title": "x", "question": "Should I buy NVDA?", "instrument_ids": []},
               headers=signed)
    assert r.status_code == 403
    assert c.post("/api/orders/stop", json={"engaged": True}, headers=signed).status_code == 403
    meeting = {"title": "x", "starts_at": "2026-11-02T10:00:00Z", "provider": "manual", "link_provider": "google_meet",
               "join_url": "https://meet.google.com/abc-defg-hij"}
    for method, path in (("POST", "/api/meetings"), ("PUT", "/api/meetings/00000000-0000-0000-0000-000000000000"),
                         ("DELETE", "/api/meetings/00000000-0000-0000-0000-000000000000")):
        r = c.request(method, path, json=meeting if method != "DELETE" else None, headers=signed)
        assert r.status_code == 403 and r.json()["code"] == "demo_read_only", (method, r.text)
    tampered = {"Cookie": f"dops_demo={cookie[:-2]}xx"}
    assert c.get("/api/decisions", headers=tampered).status_code == 401
    out = c.post("/api/auth/logout", headers=signed)
    assert out.status_code == 200 and 'dops_demo=""' in out.headers["set-cookie"] and "Path=/demo" in out.headers["set-cookie"]


def test_owner_bootstrap_only_when_no_owner_exists(owner_setup):
    from app.modules.identity.models import User
    from app.modules.identity.service import bootstrap_owner

    s = get_settings()
    s.owner_email, s.owner_password = "someone-else@example.com", "a-long-local-admin-pass"
    try:
        with db_session() as db:
            assert bootstrap_owner(db) is False  # an owner already exists: never touched
            assert db.scalar(select(User).where(User.email == "someone-else@example.com")) is None
    finally:
        s.owner_email = s.owner_password = None
