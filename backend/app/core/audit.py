"""Audit trail helper. Details must never contain secrets, document content or filenames."""

import uuid

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import utcnow
from app.core.logging import correlation_id, get_logger

log = get_logger("audit")


def record(db: Session, action: str, *, actor=None, object_type: str | None = None,
           object_id: uuid.UUID | str | None = None, details: dict | None = None) -> None:
    if get_settings().is_demo:
        return  # demo is read-only and has no audit writes
    from app.modules.audit.models import AuditEvent

    event = AuditEvent(
        at=utcnow(),
        actor_id=getattr(actor, "user_id", None),
        actor_role=getattr(actor, "role", None) or ("system" if actor is None else None),
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else None,
        correlation_id=correlation_id.get(),
        details=details or {},
    )
    db.add(event)
    log.info("audit", action=action, object_type=object_type, object_id=str(object_id) if object_id else None)
