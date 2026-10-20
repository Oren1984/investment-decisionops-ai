"""Background worker (same codebase): workflow runs, ingestion, broker events and reconciliation, quote refresh,
alerts, retention purge. Postgres job queue with leases + heartbeats. Drains its current job on SIGTERM."""

import os
import signal
import socket
import threading
import time
import uuid

import psycopg
from sqlalchemy import select, text

from app.config import get_settings
from app.core.clock import utcnow
from app.core.db import db_session
from app.core.logging import configure_logging, correlation_id, get_logger
from app.modules.workflows import jobs
from app.modules.workflows.models import Job, WorkerHeartbeat

log = get_logger("worker")

PERIODIC = {  # name: seconds
    "quotes": 60,
    "broker_events": 3,
    "reconcile": 30,
    "alerts": 60,
    "lease_sweep": 15,
    "purge": 6 * 3600,
}


class Worker:
    def __init__(self):
        self.id = f"{socket.gethostname()}-{os.getpid()}"
        self.stopping = threading.Event()
        self.current_job: int | None = None
        self.last_run: dict[str, float] = {}
        self.started = utcnow()

    # ----- heartbeat -----
    def heartbeat_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                with db_session() as db:
                    hb = db.get(WorkerHeartbeat, self.id)
                    if hb is None:
                        db.add(WorkerHeartbeat(worker_id=self.id, last_seen=utcnow(), started_at=self.started))
                    else:
                        hb.last_seen, hb.current_job = utcnow(), self.current_job
                    if self.current_job:
                        jobs.extend_lease(db, self.current_job)
            except Exception as exc:  # noqa: BLE001
                log.warning("heartbeat_failed", error=exc.__class__.__name__)
            self.stopping.wait(10)

    # ----- job handlers -----
    def handle(self, job: Job) -> None:
        if job.kind == "workflow_run":
            self.run_workflow(uuid.UUID(job.payload["run_id"]))
        elif job.kind == "ingest_document":
            from app.modules.knowledge.ingest import ingest

            with db_session() as db:
                ingest(db, uuid.UUID(job.payload["document_id"]))
        else:
            raise ValueError(f"Unknown job kind {job.kind}")

    def run_workflow(self, run_id: uuid.UUID) -> None:
        from app.modules.agents.flow import FlowRunner
        from app.modules.mcp_tools.gateway import McpGateway
        from app.modules.workflows.models import WorkflowRun

        with db_session() as db:
            run = db.get(WorkflowRun, run_id)
            correlation_id.set(run.correlation_id or uuid.uuid4().hex[:16])
        gateway = McpGateway()
        try:
            status = FlowRunner(run_id, gateway).execute()
        finally:
            gateway.close()
        log.info("workflow_finished", run_id=str(run_id), status=status)
        if status == "succeeded":
            self.record_model_verification(run_id)

    def record_model_verification(self, run_id: uuid.UUID) -> None:
        from app.modules.ops.models import ModelVerification
        from app.modules.workflows.models import WorkflowRun, WorkflowStep

        with db_session() as db:
            run = db.get(WorkflowRun, run_id)
            if run.mode != "model":
                return
            kinds = {s.step: s.output_kind for s in db.scalars(select(WorkflowStep).where(
                WorkflowStep.run_id == run_id, WorkflowStep.status == "succeeded"))}
            model_steps = [k for k in ("research", "analysis", "scenarios", "critic") if kinds.get(k) == "model"]
            if model_steps:
                db.add(ModelVerification(at=utcnow(), model_name=run.model_name, model_digest=run.model_digest,
                                         run_id=run.id, summary=f"Model-mode run succeeded; model-generated steps: "
                                                                f"{', '.join(model_steps)}."))

    # ----- periodic tasks -----
    def due(self, name: str) -> bool:
        now = time.monotonic()
        if now - self.last_run.get(name, 0) >= PERIODIC[name]:
            self.last_run[name] = now
            return True
        return False

    def periodic(self) -> None:
        from app.modules.markets.quotes import refresh_mock_quotes
        from app.modules.ops.alerts import evaluate
        from app.modules.orders.service import reconcile
        from app.modules.settings.data import purge
        from app.modules.settings.service import trading_mode

        tasks = []
        if self.due("quotes"):
            tasks.append(("quotes", refresh_mock_quotes))
        if self.due("broker_events"):
            tasks.append(("broker_events", lambda db: reconcile(db, trading_mode(db), "events")))
        if self.due("reconcile"):
            tasks.append(("reconcile", lambda db: reconcile(db, trading_mode(db), "periodic")))
        if self.due("alerts"):
            tasks.append(("alerts", evaluate))
        if self.due("lease_sweep"):
            tasks.append(("lease_sweep", self.sweep_leases))
        if self.due("purge"):
            tasks.append(("purge", purge))
        for name, fn in tasks:
            try:
                with db_session() as db:
                    fn(db)
            except Exception as exc:  # noqa: BLE001
                log.warning("periodic_failed", task=name, error=f"{exc.__class__.__name__}: {str(exc)[:200]}")

    def sweep_leases(self, db) -> None:
        """A crashed worker's lease expires: workflow runs become 'interrupted' (owner-visible Resume); other jobs
        retry within their attempt budget. No silent unlimited replay."""
        from app.modules.workflows.service import mark_interrupted

        for job in jobs.expired_running_jobs(db):
            if job.kind == "workflow_run":
                mark_interrupted(db, uuid.UUID(job.payload["run_id"]),
                                 "The worker stopped during this run (lease expired). Completed steps are kept; "
                                 "press Resume to continue.")
                job.status, job.last_error = "failed", "lease expired"
            else:
                jobs.finish(db, job, error="lease expired")

    # ----- main loop -----
    def wait_for_jobs(self, conn, timeout: float) -> None:
        try:
            for _ in conn.notifies(timeout=timeout, stop_after=1):
                break
        except psycopg.Error:
            time.sleep(timeout)

    def run(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self.stopping.set())
        signal.signal(signal.SIGINT, lambda *_: self.stopping.set())
        threading.Thread(target=self.heartbeat_loop, name="heartbeat", daemon=True).start()
        dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
        conn = psycopg.connect(dsn, autocommit=True)
        conn.execute("LISTEN jobs")
        log.info("worker_started", worker_id=self.id)
        while not self.stopping.is_set():
            self.periodic()
            with db_session() as db:
                job = jobs.claim(db, self.id)
                job_id = job.id if job else None
            if job_id is None:
                self.wait_for_jobs(conn, 1.0)
                continue
            self.current_job = job_id
            error = None
            try:
                with db_session() as db:
                    job = db.get(Job, job_id)
                self.handle(job)
            except Exception as exc:  # noqa: BLE001
                log.exception("job_failed", job_id=job_id, kind=job.kind)
                error = f"{exc.__class__.__name__}: {str(exc)[:500]}"
            finally:
                with db_session() as db:
                    job = db.get(Job, job_id)
                    jobs.finish(db, job, error=error)
                self.current_job = None
        log.info("worker_stopped", worker_id=self.id)
        with db_session() as db:
            db.execute(text("DELETE FROM worker_heartbeat WHERE worker_id = :w"), {"w": self.id})
        conn.close()


def main() -> None:
    configure_logging(get_settings().log_level)
    Worker().run()


if __name__ == "__main__":
    main()
