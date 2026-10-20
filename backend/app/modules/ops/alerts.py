"""Actionable alerts (each with a Help article). Evaluated by the worker every minute."""

import json
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import utcnow
from app.modules.identity.models import LoginAttempt
from app.modules.markets.models import DataFeed
from app.modules.ops.models import Alert
from app.modules.orders.models import OrderTicket
from app.modules.workflows.models import WorkerHeartbeat, WorkflowRun

HEARTBEAT_LOST_SECONDS = 90


def raise_alert(db: Session, kind: str, key: str, severity: str, message: str, help_slug: str,
                details: dict | None = None) -> Alert:
    now = utcnow()
    a = db.scalar(select(Alert).where(Alert.kind == kind, Alert.key == key, Alert.resolved_at.is_(None)))
    if a is None:
        a = Alert(kind=kind, key=key, severity=severity, message=message, help_slug=help_slug, first_seen=now,
                  last_seen=now, details=json.loads(json.dumps(details or {}, default=str)))
        db.add(a)
    else:
        a.last_seen, a.count, a.message = now, a.count + 1, message
    return a


def resolve(db: Session, kind: str, keep_keys: set[str]) -> None:
    for a in db.scalars(select(Alert).where(Alert.kind == kind, Alert.resolved_at.is_(None))):
        if a.key not in keep_keys:
            a.resolved_at = utcnow()


def heartbeat_age_seconds(db: Session) -> float | None:
    last = db.scalar(select(func.max(WorkerHeartbeat.last_seen)))
    return None if last is None else (utcnow() - last).total_seconds()


def backup_age_hours() -> float | None:
    manifest = get_settings().backups_dir / "last-backup.json"
    try:
        data = json.loads(manifest.read_text())
        from datetime import datetime

        return (utcnow() - datetime.fromisoformat(data["completed_at"])).total_seconds() / 3600
    except (OSError, KeyError, ValueError):
        return None


def evaluate(db: Session) -> None:
    now = utcnow()
    # Worker heartbeat (evaluated by whoever runs this; the API also computes it live for the dashboard)
    age = heartbeat_age_seconds(db)
    if age is not None and age > HEARTBEAT_LOST_SECONDS:
        raise_alert(db, "worker_heartbeat_lost", "worker", "critical",
                    f"The background worker has not reported for {int(age)} s.", "alert-worker-heartbeat")
    else:
        resolve(db, "worker_heartbeat_lost", set())
    # Orders uncertain > 2 min
    keys = set()
    for t in db.scalars(select(OrderTicket).where(OrderTicket.status.in_(("uncertain", "reconciling")),
                                                  OrderTicket.updated_at < now - timedelta(minutes=2))):
        keys.add(str(t.id))
        raise_alert(db, "order_uncertain", str(t.id), "critical",
                    f"Order {t.client_order_id} has been uncertain for more than 2 minutes.", "alert-order-uncertain")
    resolve(db, "order_uncertain", keys)
    # Stale feeds
    keys = set()
    for f in db.scalars(select(DataFeed).where(DataFeed.state.in_(("fresh", "stale", "error")))):
        stale = f.state == "error" or (f.last_success_at and (now - f.last_success_at).total_seconds() > f.stale_after_seconds)
        if stale:
            keys.add(f.key)
            raise_alert(db, "stale_feed", f.key, "warning", f"Data feed '{f.name}' is stale or failing.",
                        "alert-stale-feed")
    resolve(db, "stale_feed", keys)
    # Backups
    bage = backup_age_hours()
    if bage is None or bage > 26:
        raise_alert(db, "backup_old", "backup", "warning",
                    "No backup in the last 26 hours." if bage is not None else "No backup has been recorded yet.",
                    "alert-backup-old")
    else:
        resolve(db, "backup_old", set())
    # Login failure spikes
    failures = db.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.success.is_(False), LoginAttempt.at > now - timedelta(minutes=10)))
    if failures >= 10:
        raise_alert(db, "login_failures", "login", "warning", f"{failures} failed sign-ins in 10 minutes.",
                    "alert-login-failures")
    else:
        resolve(db, "login_failures", set())
    # Model unavailable while runs are queued
    queued_model = db.scalar(select(func.count()).select_from(WorkflowRun).where(
        WorkflowRun.mode == "model", WorkflowRun.status == "queued"))
    if queued_model:
        from app.modules.agents.llm import readiness

        if not readiness(generate=False)["ready"]:
            raise_alert(db, "model_unavailable", "model", "warning",
                        "Model-mode runs are queued but the local model is unavailable.", "alert-model-unavailable")
    else:
        resolve(db, "model_unavailable", set())
