"""Personal-data lifecycle: export (ZIP of JSON + original files), retention purge, delete-all."""

import io
import json
import uuid
import zipfile
from datetime import timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import utcnow
from app.core.db import Base
from app.modules.knowledge.ingest import uploads_dir
from app.modules.knowledge.models import Document
from app.modules.ops.models import ExportFile, RequestMetric

EXCLUDED_TABLES = {"user_session", "recovery_code", "setup_token", "login_attempt", "job", "worker_heartbeat",
                   "request_metric", "help_article", "chunk"}
SECRET_COLUMNS = {"password_hash", "totp_secret_enc", "token_hash", "embedding", "tsv"}
KEEP_ON_DELETE_ALL = {"alembic_version", "help_article", "instrument", "data_feed", "erasure_ledger", "quote_snapshot"}


def exports_dir():
    path = get_settings().data_dir / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_export(db: Session, created_by: uuid.UUID) -> ExportFile:
    buf = io.BytesIO()
    doc_ids = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in Base.metadata.sorted_tables:
            if table.name in EXCLUDED_TABLES:
                continue
            cols = [c for c in table.columns if c.name not in SECRET_COLUMNS]
            rows = [dict(r._mapping) for r in db.execute(select(*cols))]
            zf.writestr(f"data/{table.name}.json", json.dumps(rows, default=str, indent=1, ensure_ascii=False))
        for d in db.scalars(select(Document)):
            path = uploads_dir() / d.storage_id
            if path.exists():
                zf.write(path, f"documents/{d.id}-{d.filename}")
                doc_ids.append(str(d.id))
        zf.writestr("README.txt", "Investment DecisionOps AI export. JSON per table and original documents. "
                                  "Secrets (password hashes, MFA secrets, session tokens) are excluded.\n")
    name = f"export-{utcnow().strftime('%Y%m%d-%H%M%S')}.zip"
    path = exports_dir() / name
    path.write_bytes(buf.getvalue())
    row = ExportFile(created_at=utcnow(), created_by=created_by, path=str(path), size_bytes=path.stat().st_size,
                     document_ids=doc_ids)
    db.add(row)
    db.flush()
    return row


def purge(db: Session) -> dict:
    """Nightly retention purge."""
    from app.modules.audit.models import AuditEvent
    from app.modules.identity.models import LoginAttempt
    from app.modules.identity.models import Session as UserSession
    from app.modules.settings.service import get_setting
    from app.modules.workflows.models import Job, WorkflowStep

    r = get_setting(db, "retention")
    now = utcnow()
    out = {}
    out["sessions"] = db.execute(delete(UserSession).where(UserSession.expires_at < now)).rowcount
    out["login_attempts"] = db.execute(delete(LoginAttempt).where(
        LoginAttempt.at < now - timedelta(days=r["session_days"]))).rowcount
    out["request_metrics"] = db.execute(delete(RequestMetric).where(
        RequestMetric.at < now - timedelta(days=r["request_metrics_days"]))).rowcount
    out["jobs"] = db.execute(delete(Job).where(Job.status.in_(("succeeded", "failed")),
                                               Job.updated_at < now - timedelta(days=7))).rowcount
    old_steps = db.scalars(select(WorkflowStep).where(WorkflowStep.started_at < now - timedelta(days=365 * r["run_details_years"]),
                                                      WorkflowStep.output.is_not(None)))
    n = 0
    for s in old_steps:
        s.output = {"purged": True, "reason": "retention"}
        n += 1
    out["run_details"] = n
    db.execute(text("SET LOCAL app.allow_purge = 'on'"))
    out["audit_events"] = db.execute(delete(AuditEvent).where(
        AuditEvent.at < now - timedelta(days=365 * r["audit_years"]))).rowcount
    db.execute(text("SET LOCAL app.allow_purge = 'off'"))
    return out


def delete_all(db: Session) -> dict:
    """Erase all personal data. Keeps reference data, Help and the erasure ledger. The owner account is removed too;
    a new setup token is issued so the workspace can be set up again."""
    import shutil

    tables = [t.name for t in reversed(Base.metadata.sorted_tables) if t.name not in KEEP_ON_DELETE_ALL]
    db.execute(text("SET LOCAL app.allow_purge = 'on'"))
    db.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " CASCADE"))
    db.execute(text("SET LOCAL app.allow_purge = 'off'"))
    for d in (uploads_dir(), exports_dir()):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
    return {"tables_cleared": len(tables)}
