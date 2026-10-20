"""Health, metrics, the DB-derived ops dashboard, alerts and the audit viewer."""

import shutil
import uuid
from datetime import timedelta
from importlib.metadata import version as pkg_version

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session as DB

from app.config import get_settings
from app.core.authz import perm
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import NotFound
from app.modules.audit.models import AuditEvent
from app.modules.calendar.sessions import library_info
from app.modules.markets.models import DataFeed
from app.modules.markets.router import feed_out
from app.modules.ops.alerts import backup_age_hours, heartbeat_age_seconds
from app.modules.ops.models import Alert, RequestMetric
from app.modules.orders.models import OrderTicket, ReconciliationRun
from app.modules.workflows.models import Job, WorkflowRun, WorkflowStep

router = APIRouter(tags=["ops"])
APP_VERSION = "1.0.0"


@router.get("/health/live")
def live(_=Depends(perm("public"))):
    return {"status": "ok"}


def readiness_report(db: DB) -> dict:
    from app.modules.integrations import integration_statuses

    s = get_settings()
    components = {}
    try:
        rev = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        components["database"] = {"ok": True, "detail": f"migrations at {rev}"}
    except Exception as exc:  # noqa: BLE001
        components["database"] = {"ok": False, "detail": f"Database not ready: {exc.__class__.__name__}"}
        return {"ready": False, "components": components}
    if not s.is_demo:
        age = heartbeat_age_seconds(db)
        components["worker"] = {"ok": age is not None and age < 90,
                                "detail": "never seen" if age is None else f"last heartbeat {int(age)} s ago"}
    components["integrations"] = {"ok": True, "detail": "see list", "items": integration_statuses(db)}
    ready = components["database"]["ok"]
    return {"ready": ready, "profile": s.app_profile, "components": components}


@router.get("/health/ready")
def ready(db: DB = Depends(get_db, scope="function"), _=Depends(perm("public"))):
    report = readiness_report(db)
    # The public readiness answer omits integration detail.
    body = {"ready": report["ready"], "profile": report.get("profile"),
            "components": {k: {"ok": v["ok"], "detail": v["detail"]} for k, v in report["components"].items()
                           if k != "integrations"}}
    return JSONResponse(body, status_code=200 if report["ready"] else 503)


@router.get("/api/ops/readiness")
def readiness_detail(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:ops"))):
    return readiness_report(db)


def _summary(db: DB) -> dict:
    now = utcnow()
    hour = now - timedelta(hours=1)
    day = now - timedelta(days=1)
    total = db.scalar(select(func.count()).select_from(RequestMetric).where(RequestMetric.at > hour)) or 0
    errors = db.scalar(select(func.count()).select_from(RequestMetric).where(RequestMetric.at > hour,
                                                                              RequestMetric.status >= 500)) or 0
    p50, p95 = db.execute(select(func.percentile_cont(0.5).within_group(RequestMetric.duration_ms),
                                 func.percentile_cont(0.95).within_group(RequestMetric.duration_ms))
                          .where(RequestMetric.at > hour)).one()
    slow_routes = db.execute(select(RequestMetric.route, func.count(), func.percentile_cont(0.95).within_group(
        RequestMetric.duration_ms)).where(RequestMetric.at > hour).group_by(RequestMetric.route)
        .order_by(func.percentile_cont(0.95).within_group(RequestMetric.duration_ms).desc()).limit(5)).all()
    queue = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    failed_jobs = db.scalar(select(func.count()).select_from(Job).where(Job.status == "failed", Job.updated_at > day))
    runs = db.execute(select(WorkflowRun.mode, WorkflowRun.status, func.count()).where(WorkflowRun.created_at > now - timedelta(days=7))
                      .group_by(WorkflowRun.mode, WorkflowRun.status)).all()
    durations = db.execute(select(WorkflowRun.mode, func.avg(func.extract("epoch", WorkflowRun.finished_at - WorkflowRun.started_at)))
                           .where(WorkflowRun.status == "succeeded").group_by(WorkflowRun.mode)).all()
    usage = db.execute(select(WorkflowStep.output_kind, WorkflowStep.model_name, func.count(), func.sum(WorkflowStep.tokens_in),
                              func.sum(WorkflowStep.tokens_out), func.avg(WorkflowStep.duration_ms), func.sum(WorkflowStep.tool_calls))
                       .where(WorkflowStep.started_at > now - timedelta(days=7))
                       .group_by(WorkflowStep.output_kind, WorkflowStep.model_name)).all()
    orders = dict(db.execute(select(OrderTicket.status, func.count()).group_by(OrderTicket.status)).all())
    backlog = db.scalar(select(func.count()).select_from(OrderTicket).where(
        OrderTicket.status.in_(("uncertain", "reconciling", "submitting"))))
    last_recon = db.scalar(select(ReconciliationRun).order_by(ReconciliationRun.started_at.desc()))
    disk = shutil.disk_usage(get_settings().data_dir) if get_settings().data_dir.exists() else None
    hb = heartbeat_age_seconds(db)
    return {
        "generated_at": now,
        "requests_last_hour": total, "error_rate_pct": round(errors / total * 100, 2) if total else 0.0,
        "latency_ms": {"p50": round(p50 or 0), "p95": round(p95 or 0)},
        "slowest_routes": [{"route": r, "count": c, "p95_ms": round(p or 0)} for r, c, p in slow_routes],
        "queue": queue, "failed_jobs_24h": failed_jobs,
        "worker_heartbeat_seconds": None if hb is None else int(hb),
        "runs_7d": [{"mode": m, "status": s, "count": c} for m, s, c in runs],
        "avg_run_seconds": {m: round(float(v or 0), 1) for m, v in durations},
        "agent_usage_7d": [{"output_kind": k, "model": m, "steps": c, "tokens_in": int(ti or 0), "tokens_out": int(to or 0),
                            "avg_step_ms": round(float(d or 0)), "tool_calls": int(tc or 0)}
                           for k, m, c, ti, to, d, tc in usage],
        "feeds": [feed_out(f) for f in db.scalars(select(DataFeed).order_by(DataFeed.key))],
        "orders_by_status": orders, "reconciliation_backlog": backlog,
        "last_reconciliation": {"at": last_recon.started_at, "checked": last_recon.checked,
                                "mismatches": last_recon.mismatches} if last_recon else None,
        "backup_age_hours": None if (b := backup_age_hours()) is None else round(b, 1),
        "data_volume": {"used_gb": round(disk.used / 1e9, 2), "free_gb": round(disk.free / 1e9, 2)} if disk else None,
    }


@router.get("/api/ops/summary")
def summary(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:ops"))):
    return _summary(db)


@router.get("/api/ops/alerts")
def alerts(include_resolved: bool = False, db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:ops"))):
    stmt = select(Alert).order_by(Alert.last_seen.desc()).limit(100)
    if not include_resolved:
        stmt = stmt.where(Alert.resolved_at.is_(None))
    out = [{"id": str(a.id), "kind": a.kind, "severity": a.severity, "message": a.message, "help_slug": a.help_slug,
            "first_seen": a.first_seen, "last_seen": a.last_seen, "resolved_at": a.resolved_at, "count": a.count}
           for a in db.scalars(stmt)]
    hb = heartbeat_age_seconds(db)
    if not get_settings().is_demo and (hb is None or hb > 90) and not any(a["kind"] == "worker_heartbeat_lost" for a in out):
        out.insert(0, {"id": "live-worker", "kind": "worker_heartbeat_lost", "severity": "critical",
                       "message": "The background worker is not reporting." if hb is None else
                       f"The background worker has not reported for {int(hb)} s.",
                       "help_slug": "alert-worker-heartbeat", "first_seen": utcnow(), "last_seen": utcnow(),
                       "resolved_at": None, "count": 1})
    return out


@router.post("/api/ops/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), _=Depends(perm("write:ops"))):
    a = db.get(Alert, alert_id)
    if a is None:
        raise NotFound("Alert")
    a.resolved_at = utcnow()
    return {"ok": True}


@router.get("/api/audit")
def audit_events(action: str | None = None, object_type: str | None = None, limit: int = Query(100, le=500),
                 db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:ops"))):
    stmt = select(AuditEvent).order_by(AuditEvent.at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditEvent.action.ilike(f"{action}%"))
    if object_type:
        stmt = stmt.where(AuditEvent.object_type == object_type)
    return [{"id": e.id, "at": e.at, "actor_role": e.actor_role, "action": e.action, "object_type": e.object_type,
             "object_id": e.object_id, "correlation_id": e.correlation_id, "details": e.details} for e in db.scalars(stmt)]


@router.get("/api/ops/system")
def system(_=Depends(perm("read:ops"))):
    def v(pkg):
        try:
            return pkg_version(pkg)
        except Exception:  # noqa: BLE001
            return "not installed"

    s = get_settings()
    return {"app_version": APP_VERSION, "profile": s.app_profile, "calendar_library": library_info(),
            "packages": {p: v(p) for p in ("crewai", "mcp", "fastapi", "sqlalchemy", "exchange_calendars", "pypdf",
                                           "fastembed", "ib_async", "litellm")},
            "model": {"name": s.model_name, "base_url": s.ollama_base_url},
            "embeddings": {"enabled": s.embeddings_enabled, "model": s.embedding_model}}


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:ops"))):
    s = _summary(db)
    lines = [
        "# TYPE decisionops_requests_last_hour gauge", f"decisionops_requests_last_hour {s['requests_last_hour']}",
        "# TYPE decisionops_error_rate_pct gauge", f"decisionops_error_rate_pct {s['error_rate_pct']}",
        "# TYPE decisionops_latency_p95_ms gauge", f"decisionops_latency_p95_ms {s['latency_ms']['p95']}",
        "# TYPE decisionops_reconciliation_backlog gauge", f"decisionops_reconciliation_backlog {s['reconciliation_backlog']}",
        "# TYPE decisionops_worker_heartbeat_seconds gauge",
        f"decisionops_worker_heartbeat_seconds {s['worker_heartbeat_seconds'] if s['worker_heartbeat_seconds'] is not None else -1}",
    ]
    for status, n in s["queue"].items():
        lines.append(f'decisionops_jobs{{status="{status}"}} {n}')
    for status, n in s["orders_by_status"].items():
        lines.append(f'decisionops_orders{{status="{status}"}} {n}')
    return "\n".join(lines) + "\n"
