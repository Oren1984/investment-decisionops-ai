"""Authentication (session cookies + CSRF) and the single authorization model.

Every route declares exactly one permission via `Depends(perm("..."))`. A route-inventory test fails if any
API route lacks one. Object-level checks for collaborators live in `can_access_object`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.config import get_settings
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import AppError, Forbidden
from app.core.security import sha256_hex, verify_signed

SESSION_COOKIE = "dops_session"
DEMO_COOKIE = "dops_demo"  # signed, stateless: the demo database role is read-only
CSRF_COOKIE = "dops_csrf"
CSRF_HEADER = "x-csrf-token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

COLLABORATOR_PERMISSIONS = {
    "any", "read:time", "read:sessions", "read:help", "read:shared", "write:comment", "write:self",
    "read:meetings", "write:action_item",
}


def role_has(role: str, permission: str) -> bool:
    if permission in ("public", "any"):
        return True
    if role == "owner":
        return True
    if role == "demo":
        return permission.startswith("read:")
    if role == "collaborator":
        return permission in COLLABORATOR_PERMISSIONS
    return False


@dataclass
class Principal:
    user_id: uuid.UUID
    role: str  # owner | collaborator | demo
    email: str
    display_name: str
    timezone: str
    session_id: str | None = None
    stepped_up_at: datetime | None = None
    totp_enabled: bool = False

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def is_demo(self) -> bool:
        return self.role == "demo"

    @property
    def sees_owner_data(self) -> bool:
        """Owner, or the demo visitor (who sees the synthetic owner's data read-only)."""
        return self.role in ("owner", "demo")


class Unauthenticated(AppError):
    def __init__(self, message: str = "Please sign in.", code: str = "unauthenticated"):
        super().__init__(code, message, status_code=401)


def _demo_principal(db: DBSession, request: Request) -> Principal | None:
    """The demo user signs in with published credentials and sees the synthetic demo owner's data read-only."""
    from app.modules.identity.models import User

    payload = verify_signed(request.cookies.get(DEMO_COOKIE) or "")
    if not payload or payload.get("kind") != "demo" or payload.get("exp", 0) < utcnow().timestamp():
        return None
    user = db.get(User, uuid.UUID(payload["uid"]))
    if user is None or user.role != "demo" or user.disabled_at is not None:
        return None
    owner = db.scalar(select(User).where(User.role == "owner"))
    if owner is None:
        raise AppError("demo_not_seeded", "The demo workspace has not been seeded yet.", status_code=503)
    return Principal(user_id=owner.id, role="demo", email=user.email, display_name=user.display_name,
                     timezone=owner.timezone)


def resolve_principal(request: Request, db: DBSession) -> Principal | None:
    if get_settings().is_demo:
        return _demo_principal(db, request)
    from app.modules.identity.models import Session, User

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.get(Session, sha256_hex(token))
    if session is None:
        return None
    now = utcnow()
    settings = get_settings()
    if session.expires_at <= now or session.last_seen_at + timedelta(minutes=settings.session_idle_minutes) <= now:
        db.delete(session)
        db.flush()
        return None
    user = db.get(User, session.user_id)
    if user is None or user.disabled_at is not None:
        return None
    if request.method in UNSAFE_METHODS:
        header = request.headers.get(CSRF_HEADER)
        if not header or header != session.csrf_token:
            raise AppError("csrf_failed", "Security check failed. Reload the page and try again.", status_code=403)
    if (now - session.last_seen_at).total_seconds() > 30:
        session.last_seen_at = now
    request.state.session = session
    return Principal(user_id=user.id, role=user.role, email=user.email, display_name=user.display_name,
                     timezone=user.timezone, session_id=session.id, stepped_up_at=session.stepped_up_at,
                     totp_enabled=user.totp_enabled)


def perm(permission: str):
    """Route dependency enforcing `permission` and returning the Principal (None only for 'public')."""

    def dependency(request: Request, db: DBSession = Depends(get_db, scope="function")) -> Principal | None:
        if permission == "public":
            return None
        principal = resolve_principal(request, db)
        # Commit the session touch (or expired-session deletion) now: it must not wait for the end of the response.
        # A streaming response (SSE) keeps this dependency open for its whole life, and an uncommitted last_seen
        # update would hold the session row lock and a pooled connection, blocking every other request of that
        # session until the stream ends. The endpoint's own work starts a new transaction on this session.
        db.commit()
        if principal is None:
            raise Unauthenticated()
        if principal.is_demo and request.method in UNSAFE_METHODS:
            raise Forbidden("The demo is read-only.", code="demo_read_only")
        if not role_has(principal.role, permission):
            raise Forbidden()
        request.state.principal = principal
        return principal

    dependency.__permission__ = permission  # type: ignore[attr-defined]
    return dependency


def require_step_up(principal: Principal) -> None:
    window = timedelta(minutes=get_settings().step_up_minutes)
    if principal.stepped_up_at is None or principal.stepped_up_at + window < utcnow():
        raise AppError("step_up_required", "Confirm it's you: re-enter your password (and code, if enabled).",
                       status_code=401, help_slug="approvals-and-stop")


def can_access_object(db: DBSession, principal: Principal, object_type: str, object_id: uuid.UUID,
                      need: str = "view") -> bool:
    """One authorization function for every path (API, RAG, SSE, downloads)."""
    if principal.sees_owner_data:
        return need == "view" or principal.is_owner
    from app.modules.collaboration.models import ShareGrant

    now = utcnow()
    grants = db.scalars(
        select(ShareGrant).where(
            ShareGrant.grantee_id == principal.user_id,
            ShareGrant.object_type == object_type,
            ShareGrant.object_id == object_id,
            ShareGrant.revoked_at.is_(None),
        )
    ).all()
    for grant in grants:
        if grant.expires_at is not None and grant.expires_at <= now:
            continue
        if need == "view" or (need == "comment" and grant.permission == "comment"):
            return True
    return False


def granted_object_ids(db: DBSession, principal: Principal, object_type: str) -> list[uuid.UUID]:
    from app.modules.collaboration.models import ShareGrant

    now = utcnow()
    rows = db.scalars(
        select(ShareGrant).where(
            ShareGrant.grantee_id == principal.user_id,
            ShareGrant.object_type == object_type,
            ShareGrant.revoked_at.is_(None),
        )
    ).all()
    return [g.object_id for g in rows if g.expires_at is None or g.expires_at > now]
