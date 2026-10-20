"""Postgres job queue: enqueue, claim (SKIP LOCKED + lease), heartbeat, finish."""

from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.db import notify
from app.modules.workflows.models import Job

LEASE_SECONDS = 60


def enqueue(db: Session, kind: str, payload: dict | None = None, *, delay_seconds: float = 0,
            dedupe_key: str | None = None, max_attempts: int = 3) -> Job | None:
    if dedupe_key:
        existing = db.scalar(select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_(("queued", "running"))))
        if existing is not None:
            return existing
    job = Job(kind=kind, payload=payload or {}, run_after=utcnow() + timedelta(seconds=delay_seconds),
              dedupe_key=dedupe_key, max_attempts=max_attempts, status="queued")
    db.add(job)
    db.flush()
    notify(db, "jobs", kind)
    return job


def claim(db: Session, worker_id: str, kinds: list[str] | None = None) -> Job | None:
    now = utcnow()
    kind_filter = "AND kind = ANY(:kinds)" if kinds else ""
    row = db.execute(
        text(
            f"""
            UPDATE job SET status = 'running', attempts = attempts + 1, lease_until = :lease,
                   locked_by = :worker, updated_at = now()
            WHERE id = (
                SELECT id FROM job WHERE status = 'queued' AND run_after <= :now {kind_filter}
                ORDER BY run_after, id FOR UPDATE SKIP LOCKED LIMIT 1
            )
            RETURNING id
            """
        ),
        {"lease": now + timedelta(seconds=LEASE_SECONDS), "worker": worker_id, "now": now, "kinds": kinds},
    ).first()
    if row is None:
        return None
    return db.get(Job, row[0])


def extend_lease(db: Session, job_id: int) -> None:
    db.execute(text("UPDATE job SET lease_until = :l WHERE id = :id AND status = 'running'"),
               {"l": utcnow() + timedelta(seconds=LEASE_SECONDS), "id": job_id})


def finish(db: Session, job: Job, *, error: str | None = None, retry_delay: float = 5) -> None:
    if error is None:
        job.status = "succeeded"
        job.last_error = None
    elif job.attempts < job.max_attempts:
        job.status = "queued"
        job.last_error = error[:2000]
        job.run_after = utcnow() + timedelta(seconds=retry_delay * job.attempts)
    else:
        job.status = "failed"
        job.last_error = error[:2000]
    job.lease_until = None
    job.locked_by = None


def expired_running_jobs(db: Session) -> list[Job]:
    return list(db.scalars(select(Job).where(Job.status == "running", Job.lease_until < utcnow())).all())
