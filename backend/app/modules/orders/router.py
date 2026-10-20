import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from app.config import get_settings
from app.core.authz import Principal, perm
from app.core.db import get_db
from app.modules.brokers.mock import SCENARIOS
from app.modules.brokers.registry import get_adapter
from app.modules.orders import service
from app.modules.orders.models import CancelBatch, OrderTicket, ReconciliationRun
from app.modules.settings.service import trading_mode

router = APIRouter(prefix="/api/orders", tags=["orders"])

OrderType = Literal["market", "limit", "stop", "stop_limit"]
Scenario = Literal["success", "rejection", "partial_fill", "timeout", "disconnect_after_send", "duplicate_request",
                   "fill_after_cancel", "stale_quote"]


class TicketIn(BaseModel):
    instrument_id: uuid.UUID
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0, le=Decimal("1000000000"))
    order_type: OrderType = "limit"
    limit_price: Decimal | None = Field(default=None, gt=0)
    stop_price: Decimal | None = Field(default=None, gt=0)
    tif: Literal["DAY", "GTC"] = "DAY"
    decision_id: uuid.UUID | None = None
    mock_scenario: Scenario | None = None


class TicketEdit(BaseModel):
    side: Literal["buy", "sell"] | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    order_type: OrderType | None = None
    limit_price: Decimal | None = Field(default=None, gt=0)
    stop_price: Decimal | None = Field(default=None, gt=0)
    tif: Literal["DAY", "GTC"] | None = None
    mock_scenario: Scenario | None = None


@router.get("/broker")
def broker(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:orders"))):
    mode = trading_mode(db)
    s = get_settings()
    try:
        adapter = get_adapter(db, mode)
        status = adapter.connection_status()
        caps = adapter.capabilities()
    except Exception as exc:  # noqa: BLE001
        status, caps = {"status": "not_configured", "detail": getattr(exc, "message", str(exc))}, {}
    stop = service.stop_state(db)
    return {"mode": mode, "connection": status, "capabilities": caps,
            "scenarios": SCENARIOS if mode == "mock" else {},
            "stop": {"engaged": stop.engaged, "changed_at": stop.changed_at, "reason": stop.reason},
            "live": {"enabled": s.live_trading_enabled, "authorized": False, "message": service.LIVE_DISABLED_MESSAGE},
            "approval_expiry_minutes": s.approval_expiry_minutes}


@router.get("")
def list_orders(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:orders"))):
    mode = trading_mode(db)
    rows = db.scalars(select(OrderTicket).where(OrderTicket.mode == mode).order_by(OrderTicket.created_at.desc()).limit(200))
    return [service.ticket_out(db, t) for t in rows]


@router.post("")
def create(body: TicketIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:orders"))):
    t = service.create_ticket(db, principal, body.model_dump())
    return service.ticket_out(db, t, events=True)


@router.get("/{ticket_id}")
def get_order(ticket_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:orders"))):
    return service.ticket_out(db, service.get_ticket(db, ticket_id), events=True)


@router.patch("/{ticket_id}")
def edit(ticket_id: uuid.UUID, body: TicketEdit, db: DB = Depends(get_db, scope="function"),
         principal: Principal = Depends(perm("write:orders"))):
    t = service.get_ticket(db, ticket_id, lock=True)
    service.edit_ticket(db, principal, t, body.model_dump(exclude_unset=True))
    return service.ticket_out(db, t, events=True)


@router.post("/{ticket_id}/preview")
def preview(ticket_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:orders"))):
    t = service.get_ticket(db, ticket_id, lock=True)
    service.preview(db, principal, t)
    return service.ticket_out(db, t, events=True)


@router.post("/{ticket_id}/approve")
def approve(ticket_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:orders"))):
    t = service.get_ticket(db, ticket_id, lock=True)
    try:
        service.approve(db, principal, t)
    finally:
        db.commit()  # keep the 'pending_approval' event even when step-up is still required
    return service.ticket_out(db, t, events=True)


@router.post("/{ticket_id}/submit")
def submit(ticket_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:orders"))):
    t, duplicate = service.submit(db, principal, ticket_id)
    return {**service.ticket_out(db, t, events=True), "duplicate": duplicate,
            "note": "Duplicate request: the existing order was returned; nothing was sent again." if duplicate else None}


@router.post("/{ticket_id}/cancel")
def cancel(ticket_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:orders"))):
    t = service.get_ticket(db, ticket_id, lock=True)
    service.cancel(db, principal, t)
    return service.ticket_out(db, t, events=True)


@router.post("/{ticket_id}/resubmit")
def resubmit(ticket_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:orders"))):
    t = service.get_ticket(db, ticket_id, lock=True)
    service.resubmit_after_not_found(db, principal, t)
    return service.ticket_out(db, t, events=True)


@router.post("/reconcile/run")
def reconcile_now(db: DB = Depends(get_db, scope="function"), _=Depends(perm("write:orders"))):
    run = service.reconcile(db, trading_mode(db), "manual")
    return reconciliation_out(run)


def reconciliation_out(r: ReconciliationRun) -> dict:
    return {"id": str(r.id), "mode": r.mode, "trigger": r.trigger, "started_at": r.started_at,
            "finished_at": r.finished_at, "checked": r.checked, "changed": r.changed, "mismatches": r.mismatches,
            "details": r.details}


@router.get("/reconcile/history")
def reconcile_history(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:orders"))):
    rows = db.scalars(select(ReconciliationRun).where(ReconciliationRun.changed + ReconciliationRun.mismatches > 0)
                      .order_by(ReconciliationRun.started_at.desc()).limit(30))
    return [reconciliation_out(r) for r in rows]


class StopIn(BaseModel):
    engaged: bool
    reason: str | None = Field(default=None, max_length=300)


@router.post("/stop")
def stop(body: StopIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:orders"))):
    s = service.set_stop(db, principal, body.engaged, body.reason)
    return {"engaged": s.engaged, "changed_at": s.changed_at, "reason": s.reason,
            "explanation": "Stop blocks new orders and agent actions. It does not reverse fills and does not cancel "
                           "orders the broker has already accepted. Use 'Cancel open orders' for that."}


@router.post("/cancel-open")
def cancel_open(db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:orders"))):
    b = service.start_cancel_batch(db, principal)
    return {"id": str(b.id), "orders": b.ticket_ids, "results": b.results}


@router.get("/cancel-open/history")
def cancel_batches(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:orders"))):
    rows = db.scalars(select(CancelBatch).order_by(CancelBatch.created_at.desc()).limit(10))
    out = []
    for b in rows:
        current = {tid: service.get_ticket(db, uuid.UUID(tid)).status for tid in b.ticket_ids}
        out.append({"id": str(b.id), "created_at": b.created_at, "orders": len(b.ticket_ids), "current": current})
    return out
