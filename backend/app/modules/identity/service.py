import secrets
import time
import uuid
from datetime import timedelta

import pyotp
from fastapi import Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DB

from app.config import get_settings
from app.core import audit
from app.core.authz import CSRF_COOKIE, DEMO_COOKIE, SESSION_COOKIE, Principal
from app.core.clock import utcnow
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.security import (
    decrypt,
    encrypt,
    hash_password,
    new_token,
    sha256_hex,
    sign,
    validate_password,
    verify_password,
)
from app.modules.identity.models import LoginAttempt, RecoveryCode, Session, SetupToken, User

log = get_logger("identity")

MAX_FAILURES_PER_ACCOUNT = 5
MAX_FAILURES_PER_CLIENT = 20
LOCKOUT_WINDOW = timedelta(minutes=15)
GENERIC_LOGIN_ERROR = "Email or password is incorrect."


# ---------- setup token ----------

def owner_exists(db: DB) -> bool:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "owner")) > 0


def issue_setup_token(db: DB, *, force: bool = False) -> str | None:
    """Create a single-use, 24-hour setup token when no owner exists. Returns the plain token (printed to logs)."""
    if owner_exists(db):
        return None
    now = utcnow()
    active = db.scalar(select(SetupToken).where(SetupToken.used_at.is_(None), SetupToken.expires_at > now))
    configured = get_settings().initial_setup_token
    if active is not None and not force and not configured:
        return None
    if active is not None:
        active.expires_at = now
    token = configured or new_token(18)
    db.add(SetupToken(token_hash=sha256_hex(token), expires_at=now + timedelta(hours=24)))
    db.flush()
    return token


def consume_setup_token(db: DB, token: str) -> None:
    row = db.scalar(select(SetupToken).where(SetupToken.token_hash == sha256_hex(token)))
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        raise AppError("invalid_setup_token",
                       "The setup token is invalid or expired. Print a new one with: "
                       "docker compose exec api python -m app.cli setup-token", status_code=400,
                       help_slug="first-run-and-recovery")
    row.used_at = utcnow()


# ---------- read-only demo sign-in ----------

DEMO_SESSION_HOURS = 12
_demo_failures: dict[str, list[float]] = {}  # in-process: the demo database role cannot record attempts


def bootstrap_owner(db: DB) -> bool:
    """Create the owner from OWNER_EMAIL/OWNER_PASSWORD on first run. Never touches an existing owner."""
    s = get_settings()
    if not (s.owner_email and s.owner_password) or owner_exists(db):
        return False
    user = create_user(db, email=s.owner_email, display_name=s.owner_display_name, password=s.owner_password,
                       role="owner", timezone=s.owner_timezone)
    from app.modules.settings.service import get_setting, put_setting

    prefs = get_setting(db, "preferences")
    prefs["home_timezone"] = s.owner_timezone
    put_setting(db, "preferences", prefs)
    audit.record(db, "auth.owner_created", object_type="user", object_id=user.id, details={"via": "env_bootstrap"})
    return True


def ensure_demo_user(db: DB) -> None:
    """Seed (or re-key) the one read-only demo account in the isolated demo database."""
    s = get_settings()
    user = db.scalar(select(User).where(User.role == "demo"))
    if user is None:
        db.add(User(email=s.demo_user_email, display_name="Demo user (read-only)", role="demo",
                    timezone="Asia/Jerusalem", password_hash=hash_password(s.demo_user_password)))
    elif user.email != s.demo_user_email or not verify_password(user.password_hash, s.demo_user_password):
        user.email, user.password_hash = s.demo_user_email, hash_password(s.demo_user_password)


def demo_login(db: DB, request: Request, response: Response, email: str, password: str) -> User:
    key = _client_key(request)
    now = time.monotonic()
    recent = [t for t in _demo_failures.get(key, []) if now - t < LOCKOUT_WINDOW.total_seconds()]
    if len(recent) >= MAX_FAILURES_PER_CLIENT:
        raise AppError("rate_limited", "Too many attempts. Wait 15 minutes and try again.", status_code=429)
    user = db.scalar(select(User).where(User.role == "demo", func.lower(User.email) == email.lower()))
    if user is None or user.disabled_at is not None or not verify_password(user.password_hash, password):
        _demo_failures[key] = [*recent, now]
        raise AppError("invalid_credentials", GENERIC_LOGIN_ERROR, status_code=401)
    exp = utcnow() + timedelta(hours=DEMO_SESSION_HOURS)
    response.set_cookie(DEMO_COOKIE, sign({"kind": "demo", "uid": str(user.id), "exp": exp.timestamp()}),
                        max_age=DEMO_SESSION_HOURS * 3600, httponly=True, samesite="strict",
                        secure=get_settings().cookie_secure, path="/demo")
    return user


# ---------- sessions ----------

def _set_cookies(response: Response, token: str, csrf: str) -> None:
    settings = get_settings()
    max_age = settings.session_absolute_hours * 3600
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="strict",
                        secure=settings.cookie_secure, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, samesite="strict",
                        secure=settings.cookie_secure, path="/")


def clear_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.delete_cookie(DEMO_COOKIE, path="/demo")


def create_session(db: DB, user: User, request: Request, response: Response, *, stepped_up: bool = False) -> Session:
    settings = get_settings()
    now = utcnow()
    token = new_token(32)
    csrf = new_token(24)
    session = Session(id=sha256_hex(token), user_id=user.id, csrf_token=csrf, last_seen_at=now,
                      expires_at=now + timedelta(hours=settings.session_absolute_hours),
                      stepped_up_at=now if stepped_up else None,
                      user_agent=(request.headers.get("user-agent") or "")[:200])
    db.add(session)
    db.flush()
    _set_cookies(response, token, csrf)
    return session


def rotate_session(db: DB, old: Session, request: Request, response: Response, *, stepped_up: bool) -> Session:
    user = db.get(User, old.user_id)
    new = create_session(db, user, request, response, stepped_up=stepped_up)
    new.expires_at = old.expires_at  # rotation never extends the absolute lifetime
    db.delete(old)
    return new


def end_session(db: DB, session_id: str) -> None:
    db.execute(delete(Session).where(Session.id == session_id))


def end_all_sessions(db: DB, user_id: uuid.UUID, *, except_id: str | None = None) -> int:
    stmt = delete(Session).where(Session.user_id == user_id)
    if except_id:
        stmt = stmt.where(Session.id != except_id)
    return db.execute(stmt).rowcount or 0


# ---------- login ----------

def _client_key(request: Request) -> str:
    client = request.client.host if request.client else "unknown"
    return sha256_hex("client:" + client)


def _check_rate_limit(db: DB, keys: list[tuple[str, int]]) -> None:
    since = utcnow() - LOCKOUT_WINDOW
    for key, limit in keys:
        failures = db.scalar(select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.key == key, LoginAttempt.at > since, LoginAttempt.success.is_(False)))
        if failures >= limit:
            raise AppError("too_many_attempts", "Too many sign-in attempts. Wait 15 minutes and try again.",
                           status_code=429, help_slug="first-run-and-recovery")


def _record_attempt(db: DB, keys: list[str], success: bool) -> None:
    for key in keys:
        db.add(LoginAttempt(key=key, at=utcnow(), success=success))


def _verify_second_factor(db: DB, user: User, totp_code: str | None, recovery_code: str | None) -> bool:
    if totp_code:
        secret = decrypt(user.totp_secret_enc) if user.totp_secret_enc else None
        return bool(secret) and pyotp.TOTP(secret).verify(totp_code.replace(" ", ""), valid_window=1)
    if recovery_code:
        normalized = recovery_code.strip().lower().replace(" ", "").replace("-", "")
        for code in db.scalars(select(RecoveryCode).where(RecoveryCode.user_id == user.id,
                                                          RecoveryCode.used_at.is_(None))):
            if verify_password(code.code_hash, normalized):
                code.used_at = utcnow()
                audit.record(db, "auth.recovery_code_used", object_type="user", object_id=user.id)
                return True
    return False


def login(db: DB, request: Request, response: Response, email: str, password: str,
          totp_code: str | None, recovery_code: str | None) -> User:
    account_key = sha256_hex("acct:" + email.strip().lower())
    client_key = _client_key(request)
    _check_rate_limit(db, [(account_key, MAX_FAILURES_PER_ACCOUNT), (client_key, MAX_FAILURES_PER_CLIENT)])
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    ok = user is not None and user.disabled_at is None and verify_password(user.password_hash, password)
    if not ok:
        _record_attempt(db, [account_key, client_key], False)
        db.commit()  # keep the failure even though we raise
        raise AppError("invalid_credentials", GENERIC_LOGIN_ERROR, status_code=401)
    if user.totp_enabled:
        if not totp_code and not recovery_code:
            raise AppError("totp_required", "Enter the 6-digit code from your authenticator app.", status_code=401)
        if not _verify_second_factor(db, user, totp_code, recovery_code):
            _record_attempt(db, [account_key, client_key], False)
            db.commit()
            raise AppError("invalid_credentials", "The code is not valid. Try again or use a recovery code.",
                           status_code=401)
    _record_attempt(db, [account_key, client_key], True)
    create_session(db, user, request, response)
    audit.record(db, "auth.login", actor=Principal(user.id, user.role, user.email, user.display_name, user.timezone),
                 object_type="user", object_id=user.id)
    return user


def step_up(db: DB, principal: Principal, request: Request, response: Response, password: str,
            totp_code: str | None) -> None:
    user = db.get(User, principal.user_id)
    if not verify_password(user.password_hash, password):
        raise AppError("invalid_credentials", "Password is incorrect.", status_code=401)
    if user.totp_enabled and not _verify_second_factor(db, user, totp_code, None):
        raise AppError("totp_required", "Enter a valid 6-digit authenticator code.", status_code=401)
    session = db.get(Session, principal.session_id)
    rotate_session(db, session, request, response, stepped_up=True)
    audit.record(db, "auth.step_up", actor=principal, object_type="user", object_id=user.id)


def create_user(db: DB, *, email: str, display_name: str, password: str, role: str, timezone: str) -> User:
    problem = validate_password(password)
    if problem:
        raise AppError("weak_password", problem, status_code=422)
    if db.scalar(select(User).where(func.lower(User.email) == email.strip().lower())):
        raise AppError("email_taken", "An account with this email already exists.", status_code=409)
    user = User(email=email.strip().lower(), display_name=display_name.strip(), role=role,
                password_hash=hash_password(password), timezone=timezone, password_changed_at=utcnow())
    db.add(user)
    db.flush()
    return user


def change_password(db: DB, principal: Principal, current: str, new: str) -> None:
    user = db.get(User, principal.user_id)
    if not verify_password(user.password_hash, current):
        raise AppError("invalid_credentials", "Current password is incorrect.", status_code=401)
    problem = validate_password(new)
    if problem:
        raise AppError("weak_password", problem, status_code=422)
    user.password_hash = hash_password(new)
    user.password_changed_at = utcnow()
    end_all_sessions(db, user.id, except_id=principal.session_id)
    audit.record(db, "auth.password_changed", actor=principal, object_type="user", object_id=user.id)


def reset_password_cli(db: DB, email: str | None) -> tuple[str, str]:
    """Owner recovery from inside the container (local machine access is the trust anchor)."""
    stmt = select(User).where(User.role == "owner")
    if email:
        stmt = select(User).where(func.lower(User.email) == email.lower())
    user = db.scalar(stmt)
    if user is None:
        raise SystemExit("No matching user.")
    temp = "-".join(secrets.token_hex(3) for _ in range(4))
    user.password_hash = hash_password(temp)
    user.password_changed_at = utcnow()
    end_all_sessions(db, user.id)
    audit.record(db, "auth.password_reset_cli", object_type="user", object_id=user.id)
    return user.email, temp


# ---------- TOTP and recovery codes ----------

def begin_totp(db: DB, principal: Principal) -> dict:
    user = db.get(User, principal.user_id)
    secret = pyotp.random_base32()
    user.totp_secret_enc = encrypt(secret)
    user.totp_enabled = False
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="DecisionOps")
    return {"secret": secret, "otpauth_uri": uri}


def _new_recovery_codes(db: DB, user_id: uuid.UUID) -> list[str]:
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    codes = ["-".join(secrets.token_hex(3) for _ in range(2)) for _ in range(10)]
    for code in codes:
        db.add(RecoveryCode(user_id=user_id, code_hash=hash_password(code.replace("-", ""))))
    return codes


def enable_totp(db: DB, principal: Principal, code: str) -> list[str]:
    user = db.get(User, principal.user_id)
    if not user.totp_secret_enc:
        raise AppError("totp_not_started", "Start authenticator setup first.")
    if not pyotp.TOTP(decrypt(user.totp_secret_enc)).verify(code.replace(" ", ""), valid_window=1):
        raise AppError("invalid_code", "That code didn't match. Check your device clock and try again.", status_code=422)
    user.totp_enabled = True
    codes = _new_recovery_codes(db, user.id)
    audit.record(db, "auth.totp_enabled", actor=principal, object_type="user", object_id=user.id)
    return codes


def disable_totp(db: DB, principal: Principal) -> None:
    user = db.get(User, principal.user_id)
    user.totp_enabled = False
    user.totp_secret_enc = None
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    audit.record(db, "auth.totp_disabled", actor=principal, object_type="user", object_id=user.id)


def regenerate_recovery_codes(db: DB, principal: Principal) -> list[str]:
    codes = _new_recovery_codes(db, principal.user_id)
    audit.record(db, "auth.recovery_codes_regenerated", actor=principal, object_type="user",
                 object_id=principal.user_id)
    return codes
