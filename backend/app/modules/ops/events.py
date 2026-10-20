"""Server-Sent Events driven by Postgres LISTEN/NOTIFY. Access is re-checked for every event, so revocation and
logout take effect immediately on open streams."""

import asyncio
import json
import uuid

import psycopg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.core.authz import Principal, can_access_object, perm
from app.core.clock import utcnow
from app.core.db import db_session

router = APIRouter(tags=["events"])
HEARTBEAT_SECONDS = 15
OWNER_ONLY_KINDS = {"order", "stop", "run"}


def _dsn() -> str:
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


def _still_allowed(principal: Principal, kind: str, object_type: str, object_id: str) -> tuple[bool, bool]:
    """Returns (session_valid, may_see_event)."""
    from app.modules.identity.models import Session, User

    with db_session() as db:
        if principal.session_id is not None:
            s = db.get(Session, principal.session_id)
            u = db.get(User, principal.user_id)
            if s is None or s.expires_at <= utcnow() or u is None or u.disabled_at is not None:
                return False, False
        if principal.sees_owner_data:
            return True, True
        if kind in OWNER_ONLY_KINDS:
            return True, False
        try:
            return True, can_access_object(db, principal, object_type, uuid.UUID(object_id))
        except ValueError:
            return True, False


@router.get("/api/events")
async def events(request: Request, principal: Principal = Depends(perm("any"))):
    async def stream():
        yield "retry: 5000\n\n"
        try:
            conn = await psycopg.AsyncConnection.connect(_dsn(), autocommit=True)
        except psycopg.Error:
            yield "event: error\ndata: {\"message\": \"Live updates unavailable\"}\n\n"
            return
        try:
            await conn.execute("LISTEN events")
            while not await request.is_disconnected():
                got = False
                async for n in conn.notifies(timeout=HEARTBEAT_SECONDS):
                    got = True
                    try:
                        kind, object_type, object_id = n.payload.split(":", 2)
                    except ValueError:
                        continue
                    valid, visible = await run_in_threadpool(_still_allowed, principal, kind, object_type, object_id)
                    if not valid:
                        yield "event: session_ended\ndata: {}\n\n"
                        return
                    if visible:
                        yield f"event: change\ndata: {json.dumps({'kind': kind, 'type': object_type, 'id': object_id})}\n\n"
                    if await request.is_disconnected():
                        return
                if not got:
                    valid, _ = await run_in_threadpool(_still_allowed, principal, "ping", "none", "none")
                    if not valid:
                        yield "event: session_ended\ndata: {}\n\n"
                        return
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await conn.close()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
