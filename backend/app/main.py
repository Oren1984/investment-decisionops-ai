"""FastAPI application (modular monolith). Same codebase serves the owner API and the isolated demo API."""

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.db import db_session
from app.core.errors import AppError, app_error_handler
from app.core.logging import configure_logging, correlation_id, get_logger

log = get_logger("app")


def announce_setup_token() -> None:
    from app.modules.identity.service import issue_setup_token

    try:
        with db_session() as db:
            token = issue_setup_token(db)
    except Exception as exc:  # noqa: BLE001 - DB may not be migrated yet; the CLI can issue one later
        log.warning("setup_token_unavailable", error=exc.__class__.__name__)
        return
    if token:
        banner = "=" * 72
        print(f"\n{banner}\n  FIRST-RUN SETUP TOKEN (single use, valid 24 h):\n\n      {token}\n\n"
              f"  Open the app and paste it on the setup page. Print a new one with:\n"
              f"  docker compose exec api python -m app.cli setup-token\n{banner}\n", flush=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.app_profile == "owner":
        announce_setup_token()
    log.info("startup", profile=settings.app_profile)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Investment DecisionOps AI", version="1.0.0", lifespan=lifespan,
                  docs_url=None if settings.is_demo else "/api/docs", redoc_url=None,
                  openapi_url=None if settings.is_demo else "/api/openapi.json")

    from app.modules.calendar.router import router as calendar_router
    from app.modules.collaboration.router import router as collaboration_router
    from app.modules.decisions.router import router as decisions_router
    from app.modules.help.router import router as help_router
    from app.modules.identity.router import invites as invites_router
    from app.modules.identity.router import router as auth_router
    from app.modules.knowledge.router import router as library_router
    from app.modules.markets.router import router as markets_router
    from app.modules.meetings.router import router as meetings_router
    from app.modules.ops.events import router as events_router
    from app.modules.ops.router import router as ops_router
    from app.modules.orders.router import router as orders_router
    from app.modules.portfolio.router import router as portfolio_router
    from app.modules.settings.router import router as settings_router
    from app.modules.workflows.router import router as workflows_router

    for r in (auth_router, invites_router, calendar_router, markets_router, portfolio_router, decisions_router,
              workflows_router, library_router, orders_router, collaboration_router, meetings_router, help_router,
              ops_router, settings_router, events_router):
        app.include_router(r)

    app.add_exception_handler(AppError, app_error_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        first = errors[0] if errors else {"field": "", "message": "Invalid input"}
        msg = f"{first['field']}: {first['message']}" if first["field"] else first["message"]
        return JSONResponse(status_code=422, content={"code": "validation_error", "message": msg, "errors": errors})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled_error", error=exc.__class__.__name__)
        return JSONResponse(status_code=500, content={
            "code": "internal_error", "message": "Something went wrong. The error was logged with reference "
            f"{correlation_id.get()}.", "help_slug": "troubleshooting"})

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        cid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = correlation_id.set(cid)
        started = time.perf_counter()
        try:
            if (settings.is_demo and request.method not in ("GET", "HEAD", "OPTIONS")
                    and request.url.path not in DEMO_WRITABLE_PATHS):
                response = JSONResponse(status_code=403, content={"code": "demo_read_only",
                                                                  "message": "The demo is read-only."})
            else:
                response = await call_next(request)
        finally:
            correlation_id.reset(token)
        duration = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = cid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        path = request.url.path
        if not settings.is_demo and path.startswith("/api/") and path != "/api/events":
            route = request.scope.get("route")
            _record_metric(request.method, getattr(route, "path", path)[:160], response.status_code, duration)
        return response

    return app


DEMO_WRITABLE_PATHS = {"/api/auth/login", "/api/auth/logout"}  # sign-in only; the demo DB role is read-only


def _record_metric(method: str, route: str, status: int, duration_ms: int) -> None:
    from app.core.clock import utcnow
    from app.modules.ops.models import RequestMetric

    try:
        with db_session() as db:
            db.add(RequestMetric(at=utcnow(), method=method, route=route, status=status, duration_ms=duration_ms))
    except Exception:  # noqa: BLE001, S110 - metrics must never break requests
        pass


app = create_app()
