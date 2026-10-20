import uuid
from datetime import timedelta
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from app.config import get_settings
from app.core import audit
from app.core.authz import Principal, perm, require_step_up, resolve_principal
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import AppError, NotFound
from app.core.security import new_token, sha256_hex
from app.modules.identity import service
from app.modules.identity.models import Invitation, Session, User

router = APIRouter(prefix="/api/auth", tags=["auth"])
invites = APIRouter(prefix="/api/invitations", tags=["collaboration"])

_ZONES = available_timezones()


def _check_zone(value: str) -> str:
    if value not in _ZONES:
        raise ValueError("Unknown IANA timezone, e.g. Asia/Jerusalem or America/New_York")
    return value


class SetupIn(BaseModel):
    setup_token: str
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str
    timezone: str = "Asia/Jerusalem"

    _tz = field_validator("timezone")(_check_zone)


class LoginIn(BaseModel):
    email: str
    password: str
    totp_code: str | None = None
    recovery_code: str | None = None


class StepUpIn(BaseModel):
    password: str
    totp_code: str | None = None


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


class CodeIn(BaseModel):
    code: str


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        return _check_zone(v) if v else v


def _me(principal: Principal) -> dict:
    return {
        "id": str(principal.user_id), "email": principal.email, "display_name": principal.display_name,
        "role": principal.role, "timezone": principal.timezone, "totp_enabled": principal.totp_enabled,
        "stepped_up_until": (principal.stepped_up_at + timedelta(minutes=get_settings().step_up_minutes)).isoformat()
        if principal.stepped_up_at else None,
    }


@router.get("/status")
def status(request: Request, db: DB = Depends(get_db, scope="function"), _=Depends(perm("public"))):
    settings = get_settings()
    principal = resolve_principal(request, db) if request.method == "GET" else None
    return {
        "profile": settings.app_profile,
        "setup_required": (not settings.is_demo) and not service.owner_exists(db),
        "authenticated": principal is not None,
        "user": _me(principal) if principal else None,
    }


@router.post("/setup")
def setup(body: SetupIn, request: Request, response: Response, db: DB = Depends(get_db, scope="function"), _=Depends(perm("public"))):
    if get_settings().is_demo:
        raise AppError("demo_read_only", "The demo is read-only.", status_code=403)
    if service.owner_exists(db):
        raise AppError("already_set_up", "The owner account already exists. Sign in instead.", status_code=409)
    service.consume_setup_token(db, body.setup_token)
    user = service.create_user(db, email=body.email, display_name=body.display_name, password=body.password,
                               role="owner", timezone=body.timezone)
    from app.modules.settings.service import get_setting, put_setting
    prefs = get_setting(db, "preferences")
    prefs["home_timezone"] = body.timezone
    put_setting(db, "preferences", prefs)
    service.create_session(db, user, request, response)
    audit.record(db, "auth.owner_created", object_type="user", object_id=user.id)
    return {"ok": True}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: DB = Depends(get_db, scope="function"), _=Depends(perm("public"))):
    if get_settings().is_demo:
        user = service.demo_login(db, request, response, body.email, body.password)
        return {"ok": True, "role": user.role}
    user = service.login(db, request, response, body.email, body.password, body.totp_code, body.recovery_code)
    return {"ok": True, "role": user.role}


@router.post("/logout")
def logout(request: Request, response: Response, db: DB = Depends(get_db, scope="function"), _=Depends(perm("public"))):
    # Resolved here rather than via perm("any"): demo principals may not use unsafe methods, but must be able to
    # sign out. Real sessions still pass the CSRF check inside resolve_principal.
    principal = resolve_principal(request, db)
    if principal is not None and principal.session_id:
        service.end_session(db, principal.session_id)
        audit.record(db, "auth.logout", actor=principal, object_type="user", object_id=principal.user_id)
    service.clear_cookies(response)
    return {"ok": True}


@router.post("/logout-all")
def logout_all(response: Response, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("any"))):
    count = service.end_all_sessions(db, principal.user_id)
    audit.record(db, "auth.logout_all", actor=principal, object_type="user", object_id=principal.user_id,
                 details={"sessions": count})
    service.clear_cookies(response)
    return {"ok": True, "sessions_ended": count}


@router.get("/me")
def me(principal: Principal = Depends(perm("any"))):
    return _me(principal)


@router.patch("/profile")
def update_profile(body: ProfileIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:self"))):
    user = db.get(User, principal.user_id)
    if body.display_name:
        user.display_name = body.display_name
    if body.timezone:
        user.timezone = body.timezone
    return {"ok": True}


@router.post("/step-up")
def step_up(body: StepUpIn, request: Request, response: Response, db: DB = Depends(get_db, scope="function"),
            principal: Principal = Depends(perm("write:self"))):
    service.step_up(db, principal, request, response, body.password, body.totp_code)
    return {"ok": True, "valid_minutes": get_settings().step_up_minutes}


@router.post("/password")
def change_password(body: PasswordIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:self"))):
    service.change_password(db, principal, body.current_password, body.new_password)
    return {"ok": True}


@router.post("/totp/setup")
def totp_setup(db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:self"))):
    require_step_up(principal)
    return service.begin_totp(db, principal)


@router.post("/totp/enable")
def totp_enable(body: CodeIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:self"))):
    codes = service.enable_totp(db, principal, body.code)
    return {"recovery_codes": codes, "note": "Store these codes somewhere safe. They are shown only once."}


@router.post("/totp/disable")
def totp_disable(db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:self"))):
    require_step_up(principal)
    service.disable_totp(db, principal)
    return {"ok": True}


@router.post("/recovery-codes")
def recovery_codes(db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:self"))):
    require_step_up(principal)
    return {"recovery_codes": service.regenerate_recovery_codes(db, principal)}


@router.get("/sessions")
def list_sessions(db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("any"))):
    rows = db.scalars(select(Session).where(Session.user_id == principal.user_id)
                      .order_by(Session.last_seen_at.desc())).all()
    return [{"id": s.id[:12], "current": s.id == principal.session_id, "created_at": s.created_at,
             "last_seen_at": s.last_seen_at, "expires_at": s.expires_at, "user_agent": s.user_agent} for s in rows]


# ---------- invitations ----------

class InviteIn(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    timezone: str = "UTC"
    expires_in_days: int = Field(default=7, ge=1, le=30)

    _tz = field_validator("timezone")(_check_zone)


class AcceptIn(BaseModel):
    token: str
    password: str


def _invite_out(inv: Invitation) -> dict:
    state = "accepted" if inv.accepted_at else "revoked" if inv.revoked_at else \
        "expired" if inv.expires_at <= utcnow() else "pending"
    return {"id": str(inv.id), "email": inv.email, "display_name": inv.display_name, "timezone": inv.timezone,
            "created_at": inv.created_at, "expires_at": inv.expires_at, "state": state}


@invites.get("")
def list_invitations(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:collaboration"))):
    return [_invite_out(i) for i in db.scalars(select(Invitation).order_by(Invitation.created_at.desc()))]


@invites.post("")
def create_invitation(body: InviteIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:collaboration"))):
    token = new_token(24)
    inv = Invitation(email=body.email.lower(), display_name=body.display_name, timezone=body.timezone,
                     token_hash=sha256_hex(token), created_by=principal.user_id,
                     expires_at=utcnow() + timedelta(days=body.expires_in_days))
    db.add(inv)
    db.flush()
    audit.record(db, "collab.invitation_created", actor=principal, object_type="invitation", object_id=inv.id)
    return {**_invite_out(inv), "accept_path": f"/invite/{token}",
            "note": "Send this link to the collaborator yourself. It is shown only once."}


@invites.delete("/{invitation_id}")
def revoke_invitation(invitation_id: uuid.UUID, db: DB = Depends(get_db, scope="function"),
                      principal: Principal = Depends(perm("write:collaboration"))):
    inv = db.get(Invitation, invitation_id)
    if inv is None:
        raise NotFound("Invitation")
    inv.revoked_at = utcnow()
    audit.record(db, "collab.invitation_revoked", actor=principal, object_type="invitation", object_id=inv.id)
    return _invite_out(inv)


def _valid_invite(db: DB, token: str) -> Invitation:
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == sha256_hex(token)))
    if inv is None or inv.revoked_at or inv.accepted_at or inv.expires_at <= utcnow():
        raise AppError("invalid_invitation", "This invitation link is invalid, expired or already used. "
                       "Ask the owner for a new one.", status_code=400)
    return inv


@invites.get("/accept/{token}")
def invitation_info(token: str, db: DB = Depends(get_db, scope="function"), _=Depends(perm("public"))):
    inv = _valid_invite(db, token)
    return {"email": inv.email, "display_name": inv.display_name, "timezone": inv.timezone}


@invites.post("/accept")
def accept_invitation(body: AcceptIn, request: Request, response: Response, db: DB = Depends(get_db, scope="function"),
                      _=Depends(perm("public"))):
    if get_settings().is_demo:
        raise AppError("demo_read_only", "The demo is read-only.", status_code=403)
    inv = _valid_invite(db, body.token)
    user = service.create_user(db, email=inv.email, display_name=inv.display_name, password=body.password,
                               role="collaborator", timezone=inv.timezone)
    inv.accepted_at = utcnow()
    inv.user_id = user.id
    service.create_session(db, user, request, response)
    audit.record(db, "collab.invitation_accepted", object_type="user", object_id=user.id)
    return {"ok": True}
