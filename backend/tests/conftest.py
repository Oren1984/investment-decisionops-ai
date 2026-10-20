"""Test harness: a fresh PostgreSQL database per test session (real Postgres + pgvector, never production data).

Requires TEST_ADMIN_URL (a superuser URL to the 'postgres' database) — the check scripts start a throwaway
container and set it.
"""

import os
import secrets
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

ADMIN_URL = os.environ.get("TEST_ADMIN_URL", "postgresql://decisionops:devpass@localhost:55432/postgres")
DB_NAME = f"dops_test_{secrets.token_hex(4)}"
_base = ADMIN_URL.rsplit("/", 1)[0]
os.environ["DATABASE_URL"] = f"{_base.replace('postgresql://', 'postgresql+psycopg://')}/{DB_NAME}"
os.environ["APP_PROFILE"] = "test"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="dops-data-")
os.environ["BACKUPS_DIR"] = tempfile.mkdtemp(prefix="dops-backups-")
os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:9")  # unreachable unless a model test overrides it

OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "synthetic-test-owner-pass"


def _admin(sql: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(sql)


@pytest.fixture(scope="session", autouse=True)
def database():
    _admin(f'CREATE DATABASE "{DB_NAME}"')
    from app.config import get_settings

    get_settings.cache_clear()
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    command.upgrade(cfg, "head")
    from app.core.db import db_session
    from app.modules.help.service import index_articles
    from app.seed import seed_owner_samples, seed_reference

    with db_session() as db:
        seed_reference(db)
        seed_owner_samples(db)
        index_articles(db)
    yield
    from app.core.db import reset_engine

    reset_engine()
    _admin(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')


@pytest.fixture
def db():
    from app.core.db import session_factory

    s = session_factory()()
    try:
        yield s
        s.commit()
    finally:
        s.close()


class Api:
    """TestClient wrapper that sends the CSRF header like the SPA does."""

    def __init__(self, client):
        self.c = client

    def _headers(self, extra=None):
        h = dict(extra or {})
        csrf = self.c.cookies.get("dops_csrf")
        if csrf:
            h["X-CSRF-Token"] = csrf
        return h

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._headers(kw.pop("headers", None)), **kw)

    def put(self, url, json=None, **kw):
        return self.c.put(url, json=json, headers=self._headers(kw.pop("headers", None)), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(url, json=json, headers=self._headers(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._headers(kw.pop("headers", None)), **kw)

    def step_up(self, password=OWNER_PASSWORD):
        r = self.post("/api/auth/step-up", {"password": password})
        assert r.status_code == 200, r.text
        return r


def _client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture(scope="session")
def owner_setup(database):
    """Create the owner once through the real setup flow."""
    from app.core.db import db_session
    from app.modules.identity.service import issue_setup_token

    with db_session() as db:
        token = issue_setup_token(db, force=True)
    api = Api(_client())
    r = api.post("/api/auth/setup", {"setup_token": token, "email": OWNER_EMAIL, "display_name": "Owner",
                                     "password": OWNER_PASSWORD, "timezone": "Asia/Jerusalem"})
    assert r.status_code == 200, r.text
    return True


@pytest.fixture
def owner(owner_setup) -> Api:
    api = Api(_client())
    r = api.post("/api/auth/login", {"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert r.status_code == 200, r.text
    return api


@pytest.fixture
def anon() -> Api:
    return Api(_client())


def make_collaborator(owner: Api, email: str | None = None, password: str = "synthetic-test-collab-pass") -> tuple[Api, str]:
    email = email or f"collab-{uuid.uuid4().hex[:6]}@example.com"
    r = owner.post("/api/invitations", {"email": email, "display_name": "Broker", "timezone": "Europe/London"})
    assert r.status_code == 200, r.text
    token = r.json()["accept_path"].rsplit("/", 1)[1]
    api = Api(_client())
    r = api.post("/api/invitations/accept", {"token": token, "password": password})
    assert r.status_code == 200, r.text
    me = api.get("/api/auth/me").json()
    return api, me["id"]


def run_workflow_inline(run_id: str, gateway=None) -> str:
    """Execute a queued workflow run in-process (what the worker does)."""
    from app.modules.agents.flow import FlowRunner
    from app.modules.mcp_tools.gateway import LocalGateway

    return FlowRunner(uuid.UUID(run_id), gateway or LocalGateway()).execute()


def instrument_id(api: Api, symbol: str) -> str:
    rows = api.get("/api/markets/instruments").json()
    return next(i["id"] for i in rows if i["symbol"] == symbol)


def at(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


__all__ = ["Api", "make_collaborator", "run_workflow_inline", "instrument_id", "at", "timedelta"]
